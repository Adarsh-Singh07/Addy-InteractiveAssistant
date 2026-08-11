"""
Voice Transport Abstraction.

WHY THIS EXISTS
===============
Phase 1 uses browser MediaRecorder → WebSocket → backend.
This works well for getting the prototype running, but:

  - MediaRecorder outputs webm/opus, not raw PCM (requires transcoding)
  - WebSocket has no built-in jitter buffer or echo cancellation
  - Future: WebRTC gives us echo cancellation, adaptive jitter buffer,
    and better NAT traversal for the VPS deployment

This abstraction isolates the transport layer so we can benchmark
MediaRecorder/WebSocket vs raw PCM/WebSocket vs WebRTC without touching
the voice session or agent logic.

LATENCY BENCHMARKING
====================
Once Phase 1 is working, benchmark:
  1. speech_end → llm_first_token   (STT + agent overhead)
  2. llm_first_token → tts_first_audio (LLM + sentence buffer + TTS request)
  3. tts_first_audio → client_audio_sent (TTS streaming + WebSocket)
  4. end-to-end: speech_end → client_audio_sent

If (1) or (2) dominates, upgrade STT/LLM first.
If (3) dominates, switch to WebSocket TTS streaming (vs REST).

AUDIO FORMAT NEGOTIATION
========================
The transport advertises what format it will deliver audio in.
The STT provider must accept it or transcode.
MediaRecorder typically delivers webm/opus; Deepgram accepts webm directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import AsyncIterator


class AudioFormat(str, Enum):
    WEBM_OPUS = "webm/opus"         # MediaRecorder default (Phase 1)
    LINEAR16 = "audio/l16"          # Raw PCM (future WebRTC / direct)
    LINEAR16_FLOAT = "audio/f32"    # 32-bit float PCM


@dataclass
class AudioChunk:
    data: bytes
    format: AudioFormat
    sample_rate: int = 16000
    channels: int = 1


@dataclass
class TransportMessage:
    """
    A message received from the client via the transport.
    type: "audio" | "interrupt" | "ping" | "settings"
    """
    type: str
    audio: AudioChunk | None = None
    payload: dict | None = None


class VoiceTransport(ABC):
    """
    Abstract transport layer between the browser client and backend.

    Implementations:
      - WebSocketTransport (Phase 1) — FastAPI WebSocket
      - WebRTCTransport (future)    — aiortc or similar
    """

    @abstractmethod
    async def receive(self) -> AsyncIterator[TransportMessage]:
        """
        Async iterator yielding messages from the client.
        Raises StopAsyncIteration when the connection closes.
        """
        ...

    @abstractmethod
    async def send_audio(self, audio_bytes: bytes) -> None:
        """Send raw audio bytes to the client for playback."""
        ...

    @abstractmethod
    async def send_event(self, event_type: str, payload: dict | None = None) -> None:
        """
        Send a JSON control event to the client.

        Standard event types:
          "listening"   — session is now listening
          "thinking"    — LLM processing started
          "speaking"    — TTS audio incoming
          "interrupted" — agent interrupted, back to listening
          "error"       — error occurred
          "transcript"  — interim or final transcript text
          "response"    — agent response text (for UI display)
          "metrics"     — latency report for this turn
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Close the transport connection gracefully."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """True if the underlying transport connection is still open."""
        ...
