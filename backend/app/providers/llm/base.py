"""
Abstract base class for all LLM providers.

Phase 1 implementations: GeminiProvider, GroqProvider
Phase N stub: LunaProvider

To add a new provider:
1. Subclass LLMProvider
2. Implement stream_chat() and health_check()
3. Register in providers/llm/__init__.py
4. Add env vars to settings.py
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


@dataclass
class Message:
    """A single message in a conversation."""
    role: str   # "user" | "assistant" | "system" | "tool"
    content: str
    name: str | None = None     # For tool messages


@dataclass
class LLMResponse:
    """Complete (non-streaming) response from an LLM."""
    content: str
    model: str
    provider: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None


class LLMProvider(ABC):
    """
    Abstract base for all LLM providers.

    Providers MUST support async streaming via stream_chat().
    The non-streaming complete_chat() is optional — default implementation
    collects the stream.
    """

    provider_name: str = "base"

    @abstractmethod
    async def stream_chat(
        self,
        messages: list[Message],
        system_prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """
        Yield text tokens as they arrive from the LLM.

        The caller is responsible for:
        - Sentence buffering for TTS chunking
        - Interrupt handling (cancellation of the async generator)
        """
        ...

    async def complete_chat(
        self,
        messages: list[Message],
        system_prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """
        Return a complete response by collecting the stream.
        Providers may override this for efficiency.
        """
        parts: list[str] = []
        async for token in self.stream_chat(
            messages, system_prompt, max_tokens, temperature
        ):
            parts.append(token)
        return LLMResponse(
            content="".join(parts),
            model="unknown",
            provider=self.provider_name,
        )

    @abstractmethod
    async def health_check(self) -> bool:
        """Return True if the provider is reachable and has a valid API key."""
        ...

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(provider={self.provider_name!r})"
