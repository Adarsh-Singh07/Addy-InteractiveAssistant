"""
Groq LLM provider.

Models:
  groq_model_fast  = llama-3.1-8b-instant   ← voice turns (speed priority)
  groq_model_smart = llama-3.3-70b-versatile ← complex reasoning tasks

Groq is the recommended fallback because of its extreme token throughput
(500+ tokens/second), which directly reduces voice response latency.
"""

from __future__ import annotations

from typing import AsyncIterator

from app.observability.logging import get_logger
from app.providers.llm.base import LLMProvider, Message

log = get_logger(__name__)


class GroqProvider(LLMProvider):
    provider_name = "groq"

    def __init__(
        self,
        api_key: str,
        model_fast: str = "llama-3.1-8b-instant",
        model_smart: str = "llama-3.3-70b-versatile",
        use_fast: bool = True,
    ) -> None:
        self._api_key = api_key
        self._model_fast = model_fast
        self._model_smart = model_smart
        self._use_fast = use_fast
        self._client: object | None = None
        self._init_client()

    def _init_client(self) -> None:
        try:
            from groq import AsyncGroq  # type: ignore[import]
            self._client = AsyncGroq(api_key=self._api_key)
            model = self._model_fast if self._use_fast else self._model_smart
            log.info("Groq client initialised", model=model)
        except ImportError:
            log.error("groq not installed — run: pip install groq")
            self._client = None

    @property
    def active_model(self) -> str:
        return self._model_fast if self._use_fast else self._model_smart

    def _build_messages(self, system_prompt: str, messages: list[Message]) -> list[dict]:
        result = [{"role": "system", "content": system_prompt}]
        for m in messages:
            if m.role == "system":
                continue
            result.append({"role": m.role, "content": m.content})
        return result

    async def stream_chat(
        self,
        messages: list[Message],
        system_prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        if self._client is None:
            log.error("Groq client not available")
            yield "[Groq unavailable — check API key]"
            return

        groq_messages = self._build_messages(system_prompt, messages)

        try:
            stream = await self._client.chat.completions.create(  # type: ignore[union-attr]
                messages=groq_messages,
                model=self.active_model,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as exc:
            log.error("Groq stream error", error=str(exc))
            raise

    async def health_check(self) -> bool:
        if self._client is None:
            return False
        try:
            resp = await self._client.chat.completions.create(  # type: ignore[union-attr]
                messages=[{"role": "user", "content": "ping"}],
                model=self._model_fast,
                max_tokens=4,
            )
            return bool(resp.choices)
        except Exception as exc:
            log.warning("Groq health check failed", error=str(exc))
            return False
