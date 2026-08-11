"""
Deepgram TTS provider.

Phase 1: REST API per sentence — simple, reliable, well-supported.
  POST /v1/speak?model=aura-2-asteria-en&encoding=linear16&sample_rate=24000
  Body: {"text": "..."}
  Returns: raw audio bytes (linear16 PCM)

Latency profile:
  - Network round-trip to Deepgram (~50–150ms)
  - TTS generation (~100–300ms for short sentences)
  - Total per-sentence: typically 200–500ms

Upgrade path to WebSocket TTS streaming:
  - Replace synthesize_stream() with WebSocket-based streaming
  - Audio arrives in chunks during generation (lower perceived latency)
  - No changes needed to VoiceSession or calling code (interface stays the same)
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import httpx

from app.observability.logging import get_logger
from app.providers.tts.base import TTSProvider

log = get_logger(__name__)

DEEPGRAM_TTS_URL = "https://api.deepgram.com/v1/speak"


class DeepgramTTS(TTSProvider):
    provider_name = "deepgram"

    def __init__(
        self,
        api_key: str,
        model: str = "aura-2-asteria-en",
        sample_rate: int = 24000,
        encoding: str = "linear16",
    ) -> None:
        self._api_key = api_key
        self._default_model = model
        self._default_sample_rate = sample_rate
        self._default_encoding = encoding
        # Shared async HTTP client (reuse connections)
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"Token {api_key}"},
            timeout=httpx.Timeout(30.0, connect=10.0),
        )

    async def synthesize_stream(
        self,
        text: str,
        model: str | None = None,
        sample_rate: int | None = None,
        encoding: str | None = None,
    ) -> AsyncIterator[bytes]:
        """
        Synthesize text via Deepgram REST API.

        Yields audio bytes as a single chunk (Phase 1 REST implementation).
        When upgraded to WebSocket TTS, this will yield multiple smaller chunks.
        """
        if not text.strip():
            return

        m = model or self._default_model
        sr = sample_rate or self._default_sample_rate
        enc = encoding or self._default_encoding

        params = {"model": m, "encoding": enc, "sample_rate": sr, "container": "none"}

        try:
            response = await self._http.post(
                DEEPGRAM_TTS_URL,
                params=params,
                json={"text": text},
            )
            response.raise_for_status()
            audio_bytes = response.content
            if audio_bytes:
                yield audio_bytes
        except asyncio.CancelledError:
            log.debug("TTS synthesis cancelled")
            raise
        except httpx.HTTPStatusError as exc:
            log.error(
                "Deepgram TTS HTTP error",
                status=exc.response.status_code,
                body=exc.response.text[:200],
            )
            raise
        except Exception as exc:
            log.error("Deepgram TTS error", error=str(exc))
            raise

    async def health_check(self) -> bool:
        try:
            # Very short synthesis as health check
            audio = await self.synthesize("Hello.")
            return len(audio) > 0
        except Exception as exc:
            log.warning("Deepgram TTS health check failed", error=str(exc))
            return False

    async def close(self) -> None:
        await self._http.aclose()
