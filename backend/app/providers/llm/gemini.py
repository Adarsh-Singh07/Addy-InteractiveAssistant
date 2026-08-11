"""
Gemini LLM provider using the google-genai SDK.

Model: gemini-2.5-flash (default — fast, free tier)
Streaming: yes, via generate_content_stream
Async: wrapped with asyncio.to_thread (SDK is sync-first; async wrapper planned)
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from app.observability.logging import get_logger
from app.providers.llm.base import LLMProvider, Message

log = get_logger(__name__)


class GeminiProvider(LLMProvider):
    provider_name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        self._api_key = api_key
        self._model = model
        self._client: object | None = None
        self._init_client()

    def _init_client(self) -> None:
        try:
            from google import genai  # type: ignore[import]
            self._client = genai.Client(api_key=self._api_key)
            log.info("Gemini client initialised", model=self._model)
        except ImportError:
            log.error("google-genai not installed — run: pip install google-genai")
            self._client = None

    def _build_contents(self, messages: list[Message]) -> list[dict]:
        """
        Convert our Message objects to Gemini's content format.
        Gemini does not use a separate system role in the messages list;
        system prompt is passed separately.
        """
        contents = []
        for m in messages:
            if m.role == "system":
                continue  # handled separately
            role = "model" if m.role == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m.content}]})
        return contents

    async def stream_chat(
        self,
        messages: list[Message],
        system_prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        if self._client is None:
            log.error("Gemini client not available")
            yield "[Gemini unavailable — check API key]"
            return

        contents = self._build_contents(messages)

        def _sync_stream():
            from google.genai import types  # type: ignore[import]
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=max_tokens,
                temperature=temperature,
            )
            return list(
                self._client.models.generate_content_stream(  # type: ignore[union-attr]
                    model=self._model,
                    contents=contents,
                    config=config,
                )
            )

        try:
            # Run the synchronous SDK in a thread to avoid blocking the event loop
            chunks = await asyncio.to_thread(_sync_stream)
            for chunk in chunks:
                if chunk.text:
                    yield chunk.text
        except Exception as exc:
            log.error("Gemini stream error", error=str(exc))
            raise

    async def health_check(self) -> bool:
        if self._client is None:
            return False
        try:
            result = await asyncio.to_thread(
                self._client.models.generate_content,  # type: ignore[union-attr]
                model=self._model,
                contents=[{"role": "user", "parts": [{"text": "ping"}]}],
            )
            return bool(result)
        except Exception as exc:
            log.warning("Gemini health check failed", error=str(exc))
            return False
