"""
Abstract base class for Text-to-Speech providers.

Phase 1: DeepgramTTS (REST per-sentence → audio bytes)
Future: KokoroTTS, Deepgram WebSocket streaming TTS

The interface is designed to support both:
  - Chunked REST (sentence → bytes)
  - True streaming WebSocket (text stream → audio stream)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator


class TTSProvider(ABC):
    """
    Abstract base for TTS providers.

    synthesize_stream() is the primary method: it accepts a text string
    and yields raw PCM audio bytes as they become available.

    For REST-based providers (Phase 1), this yields the full audio once.
    For streaming-capable providers, this yields chunks progressively.

    Callers (voice/streaming.py) do not need to know which variant is used.
    """

    provider_name: str = "base"

    @abstractmethod
    async def synthesize_stream(
        self,
        text: str,
        model: str | None = None,
        sample_rate: int = 24000,
        encoding: str = "linear16",
    ) -> AsyncIterator[bytes]:
        """
        Yield PCM audio bytes for the given text.

        Raising asyncio.CancelledError from outside (via task cancellation)
        MUST cleanly terminate the synthesis.
        """
        ...

    async def synthesize(
        self,
        text: str,
        model: str | None = None,
        sample_rate: int = 24000,
        encoding: str = "linear16",
    ) -> bytes:
        """Collect stream into a single bytes object (convenience wrapper)."""
        chunks: list[bytes] = []
        async for chunk in self.synthesize_stream(text, model, sample_rate, encoding):
            chunks.append(chunk)
        return b"".join(chunks)

    @abstractmethod
    async def health_check(self) -> bool:
        ...
