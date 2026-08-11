"""
Abstract base class for Speech-to-Text providers.

Phase 1: DeepgramSTT
Future: FasterWhisperSTT

Design: providers expose an async context manager that opens a streaming
connection, accepts audio chunks, and emits transcript events.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator


@dataclass
class TranscriptEvent:
    """A transcript event emitted by the STT provider."""
    text: str
    is_final: bool       # final transcript for this chunk
    is_utterance_end: bool  # speech endpoint detected (user stopped talking)
    confidence: float = 0.0
    words: list[dict] | None = None   # optional word-level timing


class STTProvider(ABC):
    """
    Abstract base for STT providers.

    Usage:
        async with provider.stream(options) as session:
            await session.send_audio(audio_bytes)
            async for event in session.events():
                if event.is_utterance_end:
                    process(event.text)
    """

    provider_name: str = "base"

    @abstractmethod
    async def stream(
        self,
        sample_rate: int = 16000,
        encoding: str = "linear16",
        language: str = "multi",
        model: str = "nova-3",
        endpointing_ms: int = 300,
    ) -> "STTSession":
        """
        Return an active STT streaming session.
        The returned session should be used as an async context manager.
        """
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        ...


class STTSession(ABC):
    """An active STT streaming session."""

    @abstractmethod
    async def send_audio(self, audio_bytes: bytes) -> None:
        """Send a chunk of raw audio to the STT provider."""
        ...

    @abstractmethod
    def events(self) -> AsyncIterator[TranscriptEvent]:
        """Async iterator yielding transcript events."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Cleanly close the STT session."""
        ...

    async def __aenter__(self) -> "STTSession":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
