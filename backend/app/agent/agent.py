"""
Core agent loop for Phase 1.

Responsibilities:
- Accept a user transcript
- Retrieve relevant context (Phase 3: RAG will hook in here)
- Call LLM with fallback support
- Return streaming text response

The agent loop is intentionally simple in Phase 1:
  user input → LLM → streamed response

Phase 3 will add:
  user input → retrieve(knowledge) → LLM + context → response

Phase 4+ will add:
  user input → plan → tool calls → observe → respond

The VoiceSession calls the agent; the agent does NOT know about audio.
"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

from app.agent.context import ConversationContext
from app.agent.prompts import get_system_prompt, get_voice_response_reminder
from app.config.settings import Settings
from app.observability.logging import get_logger
from app.observability.metrics import TurnLatency, get_metrics
from app.providers.llm.base import LLMProvider

log = get_logger(__name__)
metrics = get_metrics()


class AgentCore:
    """
    Phase 1 agent core — LLM with context and fallback.

    Public API:
        async for token in agent.stream_response(transcript, context, latency):
            ...  # send to TTS pipeline
    """

    def __init__(
        self,
        primary_llm: LLMProvider,
        fallback_llm: LLMProvider | None,
        settings: Settings,
    ) -> None:
        self._primary = primary_llm
        self._fallback = fallback_llm
        self._settings = settings
        self._system_prompt = get_system_prompt(
            agent_name=settings.agent_name,
            user_name=settings.user_name,
            user_timezone=settings.user_timezone,
        )
        log.info(
            "AgentCore initialised",
            primary=primary_llm.provider_name,
            fallback=fallback_llm.provider_name if fallback_llm else "none",
        )

    async def stream_response(
        self,
        transcript: str,
        context: ConversationContext,
        latency: TurnLatency,
    ) -> AsyncIterator[str]:
        """
        Stream LLM response tokens.

        Sets latency.llm_first_token_ts on first token.
        Falls back to secondary provider if primary fails.
        """
        context.add_user(transcript)
        messages = context.get_messages()
        system = self._system_prompt + get_voice_response_reminder()

        max_tokens = self._settings.voice_max_response_tokens
        first_token = True

        async def _try_provider(provider: LLMProvider) -> AsyncIterator[str]:
            nonlocal first_token
            async for token in provider.stream_chat(
                messages=messages,
                system_prompt=system,
                max_tokens=max_tokens,
                temperature=0.7,
            ):
                if first_token:
                    latency.llm_first_token_ts = time.time()
                    first_token = False
                    log.debug(
                        "LLM first token",
                        provider=provider.provider_name,
                        stt_to_llm_ms=round(
                            (latency.llm_first_token_ts - latency.speech_end_ts) * 1000, 1
                        ) if latency.speech_end_ts else None,
                    )
                yield token

        # Try primary
        try:
            full_response_parts: list[str] = []
            async for token in _try_provider(self._primary):
                full_response_parts.append(token)
                yield token

            full_response = "".join(full_response_parts)
            context.add_assistant(full_response)
            log.info(
                "Agent response complete",
                provider=self._primary.provider_name,
                length=len(full_response),
                turns=context.turn_count,
            )
            return

        except asyncio.CancelledError:
            # Barge-in: user interrupted. Do not record partial response.
            log.info("Agent stream cancelled (barge-in)")
            raise

        except Exception as exc:
            log.warning(
                "Primary LLM failed, trying fallback",
                provider=self._primary.provider_name,
                error=str(exc),
            )
            metrics.record_provider_error(self._primary.provider_name)

        # Try fallback
        if self._fallback is None:
            log.error("No fallback LLM configured")
            yield "I'm having trouble connecting right now. Please try again in a moment."
            return

        try:
            first_token = True
            full_response_parts = []
            async for token in _try_provider(self._fallback):
                full_response_parts.append(token)
                yield token

            full_response = "".join(full_response_parts)
            context.add_assistant(full_response)
            log.info(
                "Fallback response complete",
                provider=self._fallback.provider_name,
                length=len(full_response),
            )

        except asyncio.CancelledError:
            raise

        except Exception as exc:
            log.error(
                "Fallback LLM also failed",
                provider=self._fallback.provider_name,
                error=str(exc),
            )
            metrics.record_provider_error(self._fallback.provider_name)
            yield "Both LLM providers are unavailable right now. Please check your API keys."
