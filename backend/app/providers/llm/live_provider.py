"""
Gemini Live Provider.

Orchestrates connecting to the official Google Gemini Live API.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from google import genai
from google.genai import types

from app.config.settings import Settings
from app.observability.logging import get_logger
from app.providers.llm.live_capabilities import ModelCapabilityRegistry

log = get_logger(__name__)

# Mapping of thinking level string → ThinkingLevel enum
_THINKING_LEVEL_MAP: dict[str, Any] = {}
try:
    _THINKING_LEVEL_MAP = {
        "minimal": types.ThinkingLevel.MINIMAL,
        "low": types.ThinkingLevel.LOW,
        "medium": types.ThinkingLevel.MEDIUM,
        "high": types.ThinkingLevel.HIGH,
    }
except AttributeError:
    # ThinkingLevel not available in this SDK version; thinking will be disabled
    log.warning("ThinkingLevel enum not found in google-genai SDK; thinking config disabled")


class GeminiLiveProvider:
    """Provider for establishing and configuring Gemini Live API bidirectional sessions."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        api_key = settings.get_llm_api_key("gemini")
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set in settings")
        self._client = genai.Client(api_key=api_key)

    def build_connect_config(
        self,
        model: str,
        system_instruction: str,
        voice_name: str,
        thinking_level: str = "minimal",
        affective_dialogue: bool = False,
        tools: list[types.Tool] | None = None,
    ) -> types.LiveConnectConfig:
        """
        Construct the LiveConnectConfig based on model capability registry.

        IMPORTANT: LiveConnectConfig has `thinking_config` as a top-level field —
        NOT nested inside `generation_config`. The two are separate.
        """
        caps = ModelCapabilityRegistry.get_capabilities(model)

        # 1. Response modalities: audio only
        response_modalities = [types.Modality.AUDIO]

        # 2. Voice config
        voice_config = types.VoiceConfig(
            prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
        )
        speech_config = types.SpeechConfig(voice_config=voice_config)

        # 3. System instruction as Content
        system_content = types.Content(
            parts=[types.Part(text=system_instruction)]
        )

        # 4. Build kwargs for LiveConnectConfig
        config_kwargs: dict[str, Any] = {
            "response_modalities": response_modalities,
            "speech_config": speech_config,
            "system_instruction": system_content,
        }

        # Inject tools if supplied
        if tools:
            config_kwargs["tools"] = tools


        # 5. Thinking config — top-level on LiveConnectConfig (NOT inside generation_config)
        if caps.thinking and _THINKING_LEVEL_MAP:
            try:
                selected_level = _THINKING_LEVEL_MAP.get(
                    thinking_level.lower(), types.ThinkingLevel.MINIMAL
                )
                thinking_config = types.ThinkingConfig(
                    thinking_level=selected_level,
                )
                config_kwargs["thinking_config"] = thinking_config
                log.debug("Thinking config applied", level=thinking_level)
            except Exception as exc:
                log.warning("Failed to build thinking config, skipping", error=str(exc))

        # 6. Affective dialogue — top-level on LiveConnectConfig
        if caps.affective_dialogue and affective_dialogue:
            config_kwargs["enable_affective_dialog"] = True

        # 7. Input audio transcription (nice to have for UI display)
        try:
            config_kwargs["input_audio_transcription"] = types.AudioTranscriptionConfig()
        except Exception:
            pass  # Not critical if not supported

        # 8. Output audio transcription for response_token events
        try:
            config_kwargs["output_audio_transcription"] = types.AudioTranscriptionConfig()
        except Exception:
            pass  # Not critical if not supported

        config = types.LiveConnectConfig(**config_kwargs)
        return config

    @asynccontextmanager
    async def connect(
        self,
        model: str,
        config: types.LiveConnectConfig,
    ) -> AsyncIterator[Any]:
        """Establish the live connection WebSocket via the asynchronous genai client."""
        log.info("Connecting to Gemini Live API WebSocket", model=model)
        try:
            async with self._client.aio.live.connect(model=model, config=config) as session:
                yield session
        except Exception as exc:
            log.error("Failed to connect to Gemini Live WebSocket", error=str(exc))
            raise
