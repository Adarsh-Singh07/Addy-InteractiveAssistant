"""
LiveSessionManager.

Orchestrates the bidirectional real-time audio/control streaming between
the browser WebSocket client and the Gemini Live API session.

Key architectural decisions:
  - session.receive() is a per-turn generator: MUST re-call in while True.
  - Audio to browser is queued via asyncio.Queue to decouple Gemini receive
    speed from WebSocket write speed (prevents backpressure stalls).
  - activity_start / activity_end signals let Gemini detect turn end faster.
  - MIME type is audio/pcm (no rate suffix — Gemini rejects rate qualifier).
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from google.genai import types

from app.agent.character import CharacterProfile, CharacterManager
from app.config.settings import Settings
from app.observability.logging import bind_trace_id, get_logger
from app.observability.metrics import TurnLatency, get_metrics
from app.providers.llm.live_provider import GeminiLiveProvider
from app.voice.transport import AudioChunk, VoiceTransport
from app.voice.permission_matrix import AccessMode, is_character_allowed

log = get_logger(__name__)
metrics = get_metrics()

# Audio MIME type for send_realtime_input — rate suffix causes rejection
_AUDIO_MIME = "audio/pcm"

# Audio output queue size — buffers Gemini audio before WS send
_AUDIO_QUEUE_SIZE = 256


class LiveSessionManager:
    """
    Manages a single user's real-time Gemini Live Voice session.

    Bidirectional loop:
      Browser  →(PCM 16kHz)→  Gemini Live  →(PCM 24kHz)→  Browser
    """

    def __init__(
        self,
        session_id: str,
        transport: VoiceTransport,
        provider: GeminiLiveProvider,
        character: CharacterProfile,
        model: str,
        voice: str,
        settings: Settings,
        access_mode: AccessMode = AccessMode.PUBLIC,
        thinking_level: str = "minimal",
        affective_dialogue: bool = False,
    ) -> None:
        self.session_id = session_id
        self._transport = transport
        self._provider = provider
        self._character = character
        self._model = model
        self._voice = voice
        self._settings = settings
        self._access_mode = access_mode
        self._thinking_level = thinking_level
        self._affective_dialogue = affective_dialogue


        # Session connection lifecycle
        self._gemini_session: Any = None
        self._connect_time = 0.0
        self._is_running = False

        # Tasks
        self._client_task: asyncio.Task | None = None
        self._gemini_task: asyncio.Task | None = None
        self._audio_sender_task: asyncio.Task | None = None
        self._rollover_task: asyncio.Task | None = None
        self._rollover_waiter_task: asyncio.Task | None = None

        # Audio output queue — decouples Gemini receive from WS writes
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=_AUDIO_QUEUE_SIZE)

        # State tracking
        self._agent_speaking = False
        self._user_speaking = False          # tracks client VAD state
        self._current_latency: TurnLatency | None = None
        self._recent_transcript: list[str] = []

        # Rollover flag
        self._rollover_requested = asyncio.Event()

        metrics.session_opened()

    # ── Run / Lifecycle ───────────────────────────────────────────────────

    async def run(self) -> None:
        """Start the live session, reconnecting to Gemini on rollover/drop."""
        self._is_running = True
        log.info(
            "Starting Gemini Live session",
            session_id=self.session_id,
            model=self._model,
            voice=self._voice,
        )

        # Client read loop runs for the entire session lifetime (one task)
        self._client_task = asyncio.create_task(
            self._read_client_loop(), name=f"client_{self.session_id}"
        )

        # Audio sender runs for the entire session lifetime
        self._audio_sender_task = asyncio.create_task(
            self._audio_sender_loop(), name=f"audio_{self.session_id}"
        )

        await self._transport.send_event(
            "status",
            {
                "state": "listening",
                "session_id": self.session_id,
                "character": self._character.character_id,
                "model": self._model,
                "voice": self._voice,
            },
        )

        while self._is_running:
            self._connect_time = time.time()
            self._rollover_requested.clear()

            if self._client_task.done():
                # Client disconnected — stop entirely
                break

            try:
                system_instruction = self._character.generate_system_instruction(
                    user_name=self._settings.user_name,
                    agent_name=self._settings.agent_name,
                    timezone=self._settings.user_timezone,
                )
                from app.voice.tool_registry import get_live_tools
                tools = get_live_tools(self._access_mode)
                config = self._provider.build_connect_config(
                    model=self._model,
                    system_instruction=system_instruction,
                    voice_name=self._voice,
                    thinking_level=self._thinking_level,
                    affective_dialogue=self._affective_dialogue,
                    tools=tools,
                )


                log.info("Connecting to Gemini Live", model=self._model)

                async with self._provider.connect(self._model, config) as session:
                    self._gemini_session = session
                    log.info("Gemini Live connected", session_id=self.session_id)

                    self._gemini_task = asyncio.create_task(
                        self._read_gemini_loop(), name=f"gemini_{self.session_id}"
                    )
                    self._rollover_task = asyncio.create_task(
                        self._session_rollover_loop(), name=f"rollover_{self.session_id}"
                    )
                    self._rollover_waiter_task = asyncio.create_task(
                        self._rollover_requested.wait(), name=f"rollover_wait_{self.session_id}"
                    )

                    # Wait: client disconnects, Gemini drops, or rollover
                    done, pending = await asyncio.wait(
                        [self._client_task, self._gemini_task, self._rollover_waiter_task],
                        return_when=asyncio.FIRST_COMPLETED,
                    )

                    for task in pending:
                        task.cancel()
                    if not self._rollover_task.done():
                        self._rollover_task.cancel()

                    self._gemini_session = None
                    self._agent_speaking = False

                    if self._client_task.done():
                        log.info("Client disconnected, stopping", session_id=self.session_id)
                        break

                    # Either Gemini dropped or explicit rollover — reconnect
                    log.info("Reconnecting to Gemini Live", session_id=self.session_id)
                    await self._transport.send_event("status", {"state": "listening"})
                    # Brief pause to avoid hammering the API on rapid drops
                    await asyncio.sleep(0.3)
                    continue

            except Exception as exc:
                log.error("Gemini connect error", session_id=self.session_id, error=str(exc))
                await self._transport.send_event("error", {"message": f"Connection error: {exc}"})
                if self._client_task.done():
                    break
                await asyncio.sleep(2)
                continue

        # Signal audio sender to stop
        await self._audio_queue.put(None)
        await self.cleanup()

    # ── Audio Sender Loop ─────────────────────────────────────────────────

    async def _audio_sender_loop(self) -> None:
        """
        Drain the audio queue and send bytes to the browser.

        This decouples the Gemini receive loop from WebSocket write speed.
        Without this, a slow browser WS write would block the Gemini receive
        loop causing missed events, audio stutter, and skipped content.
        """
        log.debug("Audio sender loop started", session_id=self.session_id)
        while True:
            try:
                chunk = await self._audio_queue.get()
                if chunk is None:
                    break  # Poison pill — session is ending
                await self._transport.send_audio(chunk)
                self._audio_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.warning("Audio sender error", error=str(exc))
        log.debug("Audio sender loop ended", session_id=self.session_id)

    # ── Client Read Loop ──────────────────────────────────────────────────

    async def _read_client_loop(self) -> None:
        """Receive audio PCM and control messages from the browser client."""
        log.debug("Client read loop started", session_id=self.session_id)
        async for message in self._transport.receive():
            if message.type == "audio" and message.audio:
                await self._handle_client_audio(message.audio)
            elif message.type == "interrupt":
                await self.handle_interrupt()
            elif message.type == "settings":
                await self._handle_settings_update(message.payload or {})
            elif message.type == "ping":
                await self._transport.send_event("pong", {})
            elif message.type == "activity_start":
                await self._send_activity_start()
            elif message.type == "activity_end":
                await self._send_activity_end()
        log.info("Client disconnected", session_id=self.session_id)

    async def _handle_client_audio(self, chunk: AudioChunk) -> None:
        """Stream raw PCM 16kHz audio into the Gemini Live session."""
        if self._gemini_session is None:
            return
        try:
            await self._gemini_session.send_realtime_input(
                audio=types.Blob(data=chunk.data, mime_type=_AUDIO_MIME)
            )
        except Exception as exc:
            log.warning("Audio stream error", error=str(exc))

    async def _send_activity_start(self) -> None:
        """Signal to Gemini that the user has started speaking."""
        if self._gemini_session and not self._user_speaking:
            self._user_speaking = True
            try:
                await self._gemini_session.send_realtime_input(activity_start=types.ActivityStart())
                log.debug("activity_start sent", session_id=self.session_id)
            except Exception as exc:
                log.debug("activity_start not supported or failed", error=str(exc))

    async def _send_activity_end(self) -> None:
        """Signal to Gemini that the user has stopped speaking (turn boundary)."""
        if self._gemini_session and self._user_speaking:
            self._user_speaking = False
            try:
                await self._gemini_session.send_realtime_input(activity_end=types.ActivityEnd())
                log.debug("activity_end sent", session_id=self.session_id)
            except Exception as exc:
                log.debug("activity_end not supported or failed", error=str(exc))

    async def handle_interrupt(self) -> None:
        """Stop local playback immediately."""
        log.info("Interrupt received", session_id=self.session_id)
        self._agent_speaking = False
        self._user_speaking = False
        if self._current_latency:
            self._current_latency.interrupted = True
            self._current_latency = None
        # Clear the audio queue to stop pending playback
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
                self._audio_queue.task_done()
            except asyncio.QueueEmpty:
                break
        await self._transport.send_event("status", {"state": "listening"})
        await self._transport.send_event("interrupted", {})

    # ── Gemini Read Loop ──────────────────────────────────────────────────

    async def _read_gemini_loop(self) -> None:
        """
        Consume all events from the Gemini Live session.

        CRITICAL: session.receive() is a PER-TURN generator that closes after
        turn_complete. The outer while True re-calls it for every new turn.
        """
        if self._gemini_session is None:
            return

        log.debug("Gemini receive loop started", session_id=self.session_id)
        try:
            while True:
                got_any = False
                async for response in self._gemini_session.receive():
                    got_any = True
                    if response.server_content is not None:
                        await self._handle_server_content(response.server_content)
                    elif response.tool_call is not None:
                        await self._handle_tool_call(response.tool_call)

                if not got_any:
                    # receive() returned immediately with nothing — session closed
                    log.info("Gemini session closed (receive returned empty)", session_id=self.session_id)
                    break

                # Turn ended — loop back to receive next turn
                # Small yield to prevent tight spin if Gemini sends empty turns
                await asyncio.sleep(0)

        except asyncio.CancelledError:
            log.debug("Gemini receive loop cancelled", session_id=self.session_id)
        except Exception as exc:
            log.error("Gemini receive loop error", session_id=self.session_id, error=str(exc))
            await self._transport.send_event("error", {"message": f"Stream error: {exc}"})
            raise

        log.info("Gemini receive loop ended", session_id=self.session_id)

    async def _handle_server_content(self, content: Any) -> None:
        """Dispatch a server_content event from Gemini."""

        # 1. Barge-in: server detected user spoke over the model
        if content.interrupted:
            log.info("Gemini detected barge-in", session_id=self.session_id)
            self._agent_speaking = False
            if self._current_latency:
                self._current_latency.interrupted = True
                self._current_latency = None
            # Flush pending audio
            while not self._audio_queue.empty():
                try:
                    self._audio_queue.get_nowait()
                    self._audio_queue.task_done()
                except asyncio.QueueEmpty:
                    break
            await self._transport.send_event("status", {"state": "listening"})
            await self._transport.send_event("interrupted", {})
            return

        # 2. Model audio / text turn
        if content.model_turn is not None:
            if not self._agent_speaking:
                self._agent_speaking = True
                trace_id = bind_trace_id()
                self._current_latency = TurnLatency(
                    trace_id=trace_id,
                    session_id=self.session_id,
                    transcript="[Live]",
                    speech_end_ts=time.time() - 0.3,
                    llm_first_token_ts=time.time(),
                )
                await self._transport.send_event("status", {"state": "speaking"})

            for part in content.model_turn.parts:
                if part.inline_data is not None:
                    if self._current_latency and not self._current_latency.tts_first_audio_ts:
                        self._current_latency.tts_first_audio_ts = time.time()
                        self._current_latency.client_audio_sent_ts = time.time()
                    # Queue audio — don't block the receive loop on WS writes
                    try:
                        self._audio_queue.put_nowait(part.inline_data.data)
                    except asyncio.QueueFull:
                        log.warning("Audio queue full, dropping chunk", session_id=self.session_id)

                if part.text:
                    self._recent_transcript.append(part.text)
                    await self._transport.send_event("response_token", {"token": part.text})

        # 3. User input transcription (what the user said)
        if content.input_transcription is not None:
            try:
                txt = content.input_transcription.text or ""
                is_final = getattr(content.input_transcription, "finished", True)
                if txt:
                    await self._transport.send_event(
                        "transcript", {"text": txt, "is_final": is_final}
                    )
            except Exception as exc:
                log.warning("Input transcription error", error=str(exc))

        # 4. Output/model transcription
        if hasattr(content, "output_transcription") and content.output_transcription:
            try:
                txt = content.output_transcription.text or ""
                if txt:
                    self._recent_transcript.append(txt)
            except Exception as exc:
                log.warning("Output transcription error", error=str(exc))

        # 5. Turn complete
        if content.turn_complete:
            log.info("Turn complete", session_id=self.session_id)
            self._agent_speaking = False
            await self._transport.send_event("response_complete", {})
            await self._transport.send_event("status", {"state": "listening"})

            if self._current_latency:
                self._current_latency.turn_complete_ts = time.time()
                await self._transport.send_event("metrics", self._current_latency.to_dict())
                metrics.record_turn(self._current_latency)
                self._current_latency = None

    async def _handle_tool_call(self, tool_call: Any) -> None:
        """Execute real tools and return results to Gemini."""
        if self._gemini_session is None:
            return
        from app.voice.tool_registry import execute_tool
        for call in tool_call.function_calls:
            try:
                log.info("Executing Live Tool", name=call.name, args=call.args)
                result = await execute_tool(call.name, call.args)
                
                # Check for agent handoff
                if result.get("action") == "TRANSFER" and result.get("target"):
                    await self.perform_handoff(result["target"])

                resp = types.LiveClientToolResponse(
                    function_responses=[
                        types.FunctionResponse(
                            id=call.id,
                            name=call.name,
                            response=result,
                        )
                    ]
                )
                await self._gemini_session.send(input=resp)
            except Exception as exc:
                log.warning("Tool response error", error=str(exc))

    async def perform_handoff(self, target: str) -> None:
        """Dynamically switches the active character profile (prompt and voice) in-place."""
        if not is_character_allowed(target, self._access_mode):
            log.warning("Handoff request rejected: character restricted in this session mode", target=target)
            return

        log.info("Performing character handoff", target=target)
        new_char = CharacterManager().get_character(target)
        self._character = new_char
        self._voice = new_char.voice

        # Notify visualizer UI to shift theme colors
        await self._transport.send_event(
            "character_shift",
            {
                "character": target,
                "voice": new_char.voice,
                "display_name": new_char.display_name,
            }
        )

        # Break connection to trigger dynamic rollover reconnect
        self._rollover_requested.set()


    # ── Dynamic Configuration Update ──────────────────────────────────────

    async def _handle_settings_update(self, payload: dict) -> None:
        """Apply run-time settings changes via session rollover."""
        changed = False

        char_id = payload.get("character")
        if char_id and char_id != self._character.character_id:
            self._character = CharacterManager().get_character(char_id)
            changed = True

        model = payload.get("model")
        if model and model != self._model:
            self._model = model
            changed = True

        voice = payload.get("voice")
        if voice and voice != self._voice:
            self._voice = voice
            changed = True

        thinking_level = payload.get("thinking_level")
        if thinking_level and thinking_level != self._thinking_level:
            self._thinking_level = thinking_level
            changed = True

        affective = payload.get("affective_dialogue")
        if affective is not None and bool(affective) != self._affective_dialogue:
            self._affective_dialogue = bool(affective)
            changed = True

        if changed:
            log.info("Settings changed, rolling over session", session_id=self.session_id)
            self._rollover_requested.set()

    # ── Session Rollover Loop ─────────────────────────────────────────────

    async def _session_rollover_loop(self) -> None:
        """Roll over after 10 minutes of idle time."""
        while self._is_running:
            await asyncio.sleep(60)
            if time.time() - self._connect_time > 600 and not self._agent_speaking:
                log.info("10-min rollover", session_id=self.session_id)
                self._rollover_requested.set()
                return

    # ── Cleanup ───────────────────────────────────────────────────────────

    async def cleanup(self) -> None:
        """Release all session resources."""
        self._is_running = False

        for task in [
            self._client_task,
            self._gemini_task,
            self._audio_sender_task,
            self._rollover_task,
            self._rollover_waiter_task,
        ]:
            if task and not task.done():
                task.cancel()

        metrics.session_closed()
        log.info("Session stopped", session_id=self.session_id)
