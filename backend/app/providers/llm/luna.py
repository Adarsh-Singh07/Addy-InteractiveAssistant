"""
Luna LLM provider — STUB.

This will be implemented when the Luna endpoint becomes available.
The interface is already defined; only the implementation is pending.
"""

from __future__ import annotations

from typing import AsyncIterator

from app.providers.llm.base import LLMProvider, Message


class LunaProvider(LLMProvider):
    """
    Placeholder for GPT Luna integration.

    TODO:
    - Set LLM_PROVIDER=luna in .env when ready
    - Implement stream_chat() using Luna's API endpoint
    - Add LUNA_API_KEY, LUNA_BASE_URL, LUNA_MODEL to settings.py
    """

    provider_name = "luna"

    def __init__(self) -> None:
        pass

    async def stream_chat(
        self,
        messages: list[Message],
        system_prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        raise NotImplementedError(
            "LunaProvider is not yet implemented. "
            "Set LLM_PROVIDER=gemini or LLM_PROVIDER=groq."
        )
        yield  # make this a generator

    async def health_check(self) -> bool:
        return False
