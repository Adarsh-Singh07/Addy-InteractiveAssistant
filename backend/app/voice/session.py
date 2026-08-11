"""
VoiceSession — orchestrates the complete voice pipeline for one WebSocket session.

State machine:
    IDLE → LISTENING → PROCESSING → SPEAKING → LISTENING (barge-in) → IDLE

Full pipeline:
    1. Browser sends audio chunks via WebSocket
    2. Audio forwarded to Deepgram STT
    3. Deepgram fires UtteranceEnd (with final transcript)
    4. Transcript → AgentCore.stream_response()
    5. LLM tokens → SentenceBuffer
    6. Each complete sentence → DeepgramTTS → audio bytes
    7. Audio bytes → WebSocket → browser plays

Barge-in:
    Browser VAD detects user speaking during TTS
    → sends {"type": "interrupt"}
    → VoiceSession cancels speaking task
    → sends {"type": "interrupted"} event to browser
    → resumes STT forwarding

Latency instruments (TurnLatency):
    speech_end_ts       — Deepgram UtteranceEnd fires
    llm_first_token_ts  — AgentCore yields first token
    tts_first_audio_ts  — DeepgramTTS returns first audio chunk
    client_audio_sent_ts — audio bytes sent through WebSocket
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from enum import Enum
from typing import TYPE_CHECKING

from app.agent.agent import AgentCore
from app.agent.context import ConversationContext
from app.observability.logging import bind_trace_id, get_logger
from app.observability.metrics import TurnLatency, get_metrics
from app.providers.stt.base import STTProvider, TranscriptEvent
from app.providers.tts.base import TTSProvider
from app.voice.streaming import SentenceBuffer
from app.voice.transport import AudioChunk, AudioFormat, TransportMessage, VoiceTransport

if TYPE_CHECKING:
    pass

log = get_logger(__name__)
metrics = get_metrics()


class SessionState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    ERROR = "error"


class VoiceSession:
    """
    Manages a single user's voice conversation session.

    One VoiceSession is created per WebSocket connection.
    It owns the Deepgram STT connection and all async tasks for that session.
    """

    def __init__(
        self,
        session_id: str,
        transport: VoiceTransport,
        stt: STTProvider,
        tts: TTSProvider,
        agent: AgentCore,
        stt_model: str = "nova-3",
        stt_language: str = "multi",
        stt_sample_rate: int = 16000,
        stt_encoding: str = "linear16",
        stt_endpointing_ms: int = 300,
    ) -> None:
        self.session_id = session_id
        self._transport = transport
        self._stt = stt
        self._tts = tts
        self._agent = agent
        self._stt_opts = {
            "model": stt_model,
            "language": stt_language,
            "sample_rate": stt_sample_rate,
            "encoding": stt_encoding,
            "endpointing_ms": stt_endpointing_ms,
        }

        self._state = SessionState.IDLE
        self._context = ConversationContext(
            session_id=session_id,
            max_messages=20,
        )

        # Task references for cancellation
        self._speaking_task: asyncio.Task | None = None
        self._stt_session = None

        metrics.session_opened()

    # ── Public entry point ────────────────────────────────────────────────

    async def run(self) -> None:
        """Main session loop. Runs until the transport disconnects."""
        log.info("Voice session started", session_id=self.session_id)
        await self._transport.send_event("status", {"state": "listening", "session_id": self.session_id})

        try:
            # Open Deepgram STT connection
            self._stt_session = await self._stt.stream(**self._stt_opts)
            self._state = SessionState.LISTENING

            # Start the STT event consumer in background
            stt_task = asyncio.create_task(
                self._consume_stt_events(),
                name=f"stt_events_{self.session_id}",
            )

            # Main transport receive loop
            await self._receive_loop()

            # Cleanup
            stt_task.cancel()
            try:
                await stt_task
            except asyncio.CancelledError:
                pass

        except Exception as exc:
            log.error("Voice session error", session_id=self.session_id, error=str(exc))
            await self._transport.send_event("error", {"message": str(exc)})

        finally:
            await self._cleanup()

    # ── Transport receive loop ────────────────────────────────────────────

    async def _receive_loop(self) -> None:
        """Receive messages from browser, route audio to STT or handle control events."""
        async for message in self._transport.receive():
            if message.type == "audio" and message.audio:
                await self._handle_audio(message.audio)

            elif message.type == "interrupt":
                await self._handle_interrupt()

            elif message.type == "ping":
                await self._transport.send_event("pong", {})

            elif message.type == "settings":
                log.debug("Settings message", payload=message.payload)

    async def _handle_audio(self, chunk: AudioChunk) -> None:
        """Forward audio to the active Deepgram STT session."""
        if self._stt_session is not None:
            await self._stt_session.send_audio(chunk.data)

    # ── STT event consumer ────────────────────────────────────────────────

    async def _consume_stt_events(self) -> None:
        """Background task: process transcript events from Deepgram."""
        if self._stt_session is None:
            return

        async for event in self._stt_session.events():
            if event.is_utterance_end and event.text.strip():
                await self._handle_utterance_end(event)
            elif not event.is_utterance_end and event.text.strip():
                # Send interim transcript to UI for display
                await self._transport.send_event(
                    "transcript",
                    {"text": event.text, "is_final": event.is_final},
                )

    async def _handle_utterance_end(self, event: TranscriptEvent) -> None:
        """User finished speaking — run agent, synthesize, play."""
        transcript = event.text.strip()
        if not transcript:
            return

        # Cancel any ongoing speech (barge-in case)
        if self._speaking_task and not self._speaking_task.done():
            self._speaking_task.cancel()
            try:
                await self._speaking_task
            except asyncio.CancelledError:
                pass

        # Set up latency tracking for this turn
        trace_id = bind_trace_id()
        latency = TurnLatency(
            trace_id=trace_id,
            session_id=self.session_id,
            transcript=transcript,
            speech_end_ts=time.time(),
        )

        log.info("Utterance end", session_id=self.session_id, transcript=transcript[:100])

        # Inform UI
        await self._transport.send_event("transcript", {"text": transcript, "is_final": True})
        await self._transport.send_event("status", {"state": "thinking"})
        self._state = SessionState.PROCESSING

        # Launch speaking task
        self._speaking_task = asyncio.create_task(
            self._process_and_speak(transcript, latency),
            name=f"speak_{self.session_id}_{trace_id}",
        )

    # ── Agent + TTS pipeline ──────────────────────────────────────────────

    async def _process_and_speak(self, transcript: str, latency: TurnLatency) -> None:
        """Run agent and stream response through TTS in a pipelined fashion."""
        sentence_queue: asyncio.Queue[str | None] = asyncio.Queue()
        tts_first_audio_recorded = False
        full_response_parts: list[str] = []

        async def tts_worker() -> None:
            nonlocal tts_first_audio_recorded
            while True:
                sentence = await sentence_queue.get()
                if sentence is None:
                    sentence_queue.task_done()
                    break
                try:
                    await self._synthesize_and_send(
                        sentence, latency, tts_first_audio_recorded
                    )
                    if not tts_first_audio_recorded:
                        tts_first_audio_recorded = True
                except Exception as exc:
                    log.error("TTS worker sentence error", error=str(exc))
                finally:
                    sentence_queue.task_done()

        worker_task = asyncio.create_task(tts_worker())

        try:
            await self._transport.send_event("status", {"state": "speaking"})
            self._state = SessionState.SPEAKING

            sentence_buffer = SentenceBuffer()

            # Stream LLM response and push sentences to the queue concurrently
            async for token in self._agent.stream_response(
                transcript=transcript,
                context=self._context,
                latency=latency,
            ):
                full_response_parts.append(token)

                # Send token to UI for transcript display
                await self._transport.send_event("response_token", {"token": token})

                # Buffer until sentence boundary
                sentence = sentence_buffer.push(token)
                if sentence:
                    await sentence_queue.put(sentence)

            # Flush remaining buffer
            remainder = sentence_buffer.flush()
            if remainder:
                await sentence_queue.put(remainder)

            # Signal worker to exit
            await sentence_queue.put(None)
            await worker_task

            # Mark turn complete
            latency.turn_complete_ts = time.time()
            full_response = "".join(full_response_parts)
            await self._transport.send_event(
                "response_complete",
                {"text": full_response},
            )

            # Report latency to UI
            await self._transport.send_event("metrics", latency.to_dict())

            log.info(
                "Turn complete",
                session_id=self.session_id,
                end_to_end_ms=latency.end_to_end_ms,
            )

        except asyncio.CancelledError:
            latency.interrupted = True
            worker_task.cancel()
            await self._transport.send_event("status", {"state": "interrupted"})
            log.info("Speaking task cancelled", session_id=self.session_id)
            raise

        except Exception as exc:
            latency.error = str(exc)
            log.error("Speaking task error", session_id=self.session_id, error=str(exc))
            await self._transport.send_event("error", {"message": "Response generation failed."})

        finally:
            metrics.record_turn(latency)
            self._state = SessionState.LISTENING
            await self._transport.send_event("status", {"state": "listening"})

    async def _synthesize_and_send(
        self,
        sentence: str,
        latency: TurnLatency,
        first_recorded: bool,
    ) -> bytes | None:
        """Synthesize a sentence and send audio to the client."""
        try:
            audio_chunks: list[bytes] = []
            async for audio in self._tts.synthesize_stream(sentence):
                audio_chunks.append(audio)

            if not audio_chunks:
                return None

            audio_bytes = b"".join(audio_chunks)

            if not first_recorded:
                latency.tts_first_audio_ts = time.time()
                log.debug(
                    "TTS first audio",
                    llm_to_tts_ms=round(
                        (latency.tts_first_audio_ts - latency.llm_first_token_ts) * 1000, 1
                    ) if latency.llm_first_token_ts else None,
                )

            # Send to browser
            await self._transport.send_audio(audio_bytes)

            if not first_recorded:
                latency.client_audio_sent_ts = time.time()

            return audio_bytes

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("TTS synthesis error", sentence=sentence[:50], error=str(exc))
            return None

    # ── Interrupt handling ────────────────────────────────────────────────

    async def _handle_interrupt(self) -> None:
        """Browser signals barge-in — cancel TTS immediately."""
        if self._speaking_task and not self._speaking_task.done():
            log.info("Interrupt received — cancelling speech", session_id=self.session_id)
            self._speaking_task.cancel()
            try:
                await self._speaking_task
            except asyncio.CancelledError:
                pass
        await self._transport.send_event("status", {"state": "listening"})
        self._state = SessionState.LISTENING

    # ── Cleanup ───────────────────────────────────────────────────────────

    async def _cleanup(self) -> None:
        if self._speaking_task and not self._speaking_task.done():
            self._speaking_task.cancel()
            try:
                await self._speaking_task
            except asyncio.CancelledError:
                pass

        if self._stt_session is not None:
            try:
                await self._stt_session.close()
            except Exception:
                pass

        metrics.session_closed()
        log.info(
            "Voice session ended",
            session_id=self.session_id,
            turns=self._context.turn_count,
        )
