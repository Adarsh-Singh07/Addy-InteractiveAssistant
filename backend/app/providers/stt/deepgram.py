"""
Deepgram STT provider using the official deepgram-sdk.

Implements streaming speech-to-text via Deepgram's WebSocket Live API.
Supports Nova-3 with multilingual mode (English + Hindi + Hinglish code-switching).

Architecture:
  - Opens a WebSocket to Deepgram on session start
  - Receives raw audio bytes from VoiceSession, forwards to Deepgram
  - Emits TranscriptEvent objects via an async Queue
  - UtteranceEnd event triggers the agent loop in VoiceSession

Deepgram event flow:
  audio chunk → Deepgram → Transcript (is_final=False) [interim]
                         → Transcript (is_final=True)  [final for this chunk]
                         → UtteranceEnd                 [user finished speaking]
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from app.observability.logging import get_logger
from app.providers.stt.base import STTProvider, STTSession, TranscriptEvent

log = get_logger(__name__)


class DeepgramSTTSession(STTSession):
    """Active Deepgram streaming session."""

    def __init__(self, api_key: str, options: dict) -> None:
        self._api_key = api_key
        self._options = options
        self._queue: asyncio.Queue[TranscriptEvent | None] = asyncio.Queue()
        self._connection: object | None = None
        self._accumulated_transcript: str = ""

    async def _start(self) -> None:
        """Open the Deepgram WebSocket connection and register callbacks."""
        try:
            from deepgram import (  # type: ignore[import]
                DeepgramClient,
                LiveOptions,
                LiveTranscriptionEvents,
            )
        except ImportError:
            raise RuntimeError(
                "deepgram-sdk not installed — run: pip install deepgram-sdk"
            )

        deepgram = DeepgramClient(self._api_key)
        conn = deepgram.listen.asyncwebsocket.v("1")

        async def _on_transcript(_self: object, result: object, **_: object) -> None:
            try:
                alternatives = result.channel.alternatives  # type: ignore[attr-defined]
                if not alternatives:
                    return
                transcript = alternatives[0].transcript
                if not transcript:
                    return
                is_final = bool(result.is_final)  # type: ignore[attr-defined]

                if is_final:
                    self._accumulated_transcript += " " + transcript
                    self._accumulated_transcript = self._accumulated_transcript.strip()

                event = TranscriptEvent(
                    text=self._accumulated_transcript if is_final else transcript,
                    is_final=is_final,
                    is_utterance_end=False,
                )
                await self._queue.put(event)
            except Exception as exc:
                log.error("STT transcript callback error", error=str(exc))

        async def _on_utterance_end(_self: object, utterance_end: object, **_: object) -> None:
            try:
                text = self._accumulated_transcript.strip()
                self._accumulated_transcript = ""
                if not text:
                    return
                event = TranscriptEvent(
                    text=text,
                    is_final=True,
                    is_utterance_end=True,
                )
                await self._queue.put(event)
                log.debug("Utterance end", text=text[:80])
            except Exception as exc:
                log.error("STT utterance_end callback error", error=str(exc))

        async def _on_error(_self: object, error: object, **_: object) -> None:
            log.error("Deepgram STT error", error=str(error))

        conn.on(LiveTranscriptionEvents.Transcript, _on_transcript)  # type: ignore[attr-defined]
        conn.on(LiveTranscriptionEvents.UtteranceEnd, _on_utterance_end)  # type: ignore[attr-defined]
        conn.on(LiveTranscriptionEvents.Error, _on_error)  # type: ignore[attr-defined]

        kwargs = {
            "model": self._options.get("model", "nova-3"),
            "language": self._options.get("language", "multi"),
            "punctuate": True,
            "endpointing": self._options.get("endpointing_ms", 300),
            "utterance_end_ms": str(self._options.get("utterance_end_ms", 1000)),
            "interim_results": True,
            "smart_format": True,
        }

        # Only set encoding and sample_rate if we are using raw (non-containerized) linear16 PCM.
        # Containerized audio (like webm/opus from browser MediaRecorder) handles format detection automatically.
        enc = self._options.get("encoding")
        if enc == "linear16":
            kwargs["encoding"] = "linear16"
            kwargs["sample_rate"] = self._options.get("sample_rate", 16000)
            kwargs["channels"] = 1
        elif enc and enc not in ("webm", "webm/opus", "ogg", "ogg/opus", "mp3"):
            kwargs["encoding"] = enc
            kwargs["sample_rate"] = self._options.get("sample_rate", 16000)

        live_options = LiveOptions(**kwargs)

        started = await conn.start(live_options)
        if not started:
            raise RuntimeError("Failed to start Deepgram live connection")

        self._connection = conn
        log.info(
            "Deepgram STT session started",
            model=self._options.get("model"),
            language=self._options.get("language"),
        )

    async def send_audio(self, audio_bytes: bytes) -> None:
        if self._connection is None:
            return
        try:
            await self._connection.send(audio_bytes)  # type: ignore[attr-defined]
        except Exception as exc:
            log.error("STT send_audio error", error=str(exc))

    async def events(self) -> AsyncIterator[TranscriptEvent]:  # type: ignore[override]
        while True:
            event = await self._queue.get()
            if event is None:
                break
            yield event

    async def close(self) -> None:
        if self._connection is not None:
            try:
                # Gracefully close: send CloseStream and wait a short duration so final transcripts can be read
                import json
                log.debug("Sending CloseStream to Deepgram...")
                await self._connection.send(json.dumps({"type": "CloseStream"}))
                await asyncio.sleep(0.8)
                log.debug("Calling finish on Deepgram connection...")
                await self._connection.finish()  # type: ignore[attr-defined]
            except Exception as exc:
                log.warning("STT close error", error=str(exc))
            finally:
                self._connection = None
        # Signal events() to stop
        await self._queue.put(None)
        log.info("Deepgram STT session closed")


class DeepgramSTT(STTProvider):
    provider_name = "deepgram"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def stream(
        self,
        sample_rate: int = 16000,
        encoding: str = "linear16",
        language: str = "multi",
        model: str = "nova-3",
        endpointing_ms: int = 300,
    ) -> DeepgramSTTSession:
        session = DeepgramSTTSession(
            api_key=self._api_key,
            options={
                "model": model,
                "language": language,
                "encoding": encoding,
                "sample_rate": sample_rate,
                "endpointing_ms": endpointing_ms,
                "utterance_end_ms": 1000,
            },
        )
        await session._start()
        return session

    async def health_check(self) -> bool:
        try:
            from deepgram import DeepgramClient  # type: ignore[import]
            client = DeepgramClient(self._api_key)
            # Simple connectivity check
            return client is not None
        except Exception:
            return False
