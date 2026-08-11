"""
LLM provider factory.

Usage:
    from app.providers.llm import get_llm_provider
    provider = get_llm_provider(settings)
"""

from __future__ import annotations

from app.config.settings import Settings
from app.observability.logging import get_logger
from app.providers.llm.base import LLMProvider

log = get_logger(__name__)


def get_llm_provider(settings: Settings, provider_name: str | None = None) -> LLMProvider:
    name = provider_name or settings.llm_provider

    if name == "gemini":
        from app.providers.llm.gemini import GeminiProvider
        api_key = settings.get_llm_api_key("gemini")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not set in environment")
        return GeminiProvider(api_key=api_key, model=settings.gemini_model)

    elif name == "groq":
        from app.providers.llm.groq import GroqProvider
        api_key = settings.get_llm_api_key("groq")
        if not api_key:
            raise ValueError("GROQ_API_KEY not set in environment")
        return GroqProvider(
            api_key=api_key,
            model_fast=settings.groq_model_fast,
            model_smart=settings.groq_model_smart,
        )

    elif name == "luna":
        from app.providers.llm.luna import LunaProvider
        return LunaProvider()

    else:
        raise ValueError(f"Unknown LLM provider: {name!r}. Choose: gemini, groq, luna")
