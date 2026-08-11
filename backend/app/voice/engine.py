"""
VoiceEngine Abstraction Layer.

Defines the interface and instantiates GeminiLiveEngine (Primary)
and CascadedVoiceEngine (Fallback).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from app.voice.transport import AudioChunk

if TYPE_CHECKING:
    from app.voice.session import VoiceSession
    from app.voice.session_manager import LiveSessionManager


class VoiceEngine(ABC):
    """Abstract Base Class for voice engines (Live vs Cascaded)."""

    @abstractmethod
    async def run(self) -> None:
        """Run the engine's main loop."""
        pass

    @abstractmethod
    async def handle_audio(self, chunk: AudioChunk) -> None:
        """Process incoming audio bytes from client."""
        pass

    @abstractmethod
    async def handle_interrupt(self) -> None:
        """Handle user barge-in interrupt request."""
        pass


class CascadedVoiceEngine(VoiceEngine):
    """Fallback voice engine mapping to the Phase 1 Deepgram STT -> LLM -> Deepgram TTS pipeline."""

    def __init__(self, session: VoiceSession) -> None:
        self._session = session

    async def run(self) -> None:
        await self._session.run()

    async def handle_audio(self, chunk: AudioChunk) -> None:
        await self._session._handle_audio(chunk)

    async def handle_interrupt(self) -> None:
        await self._session._handle_interrupt()


class GeminiLiveEngine(VoiceEngine):
    """Primary voice engine mapping to the Gemini Live API real-time WebSocket connection."""

    def __init__(self, manager: LiveSessionManager) -> None:
        self._manager = manager

    async def run(self) -> None:
        await self._manager.run()

    async def handle_audio(self, chunk: AudioChunk) -> None:
        await self._manager.handle_audio(chunk)

    async def handle_interrupt(self) -> None:
        await self._manager.handle_interrupt()
