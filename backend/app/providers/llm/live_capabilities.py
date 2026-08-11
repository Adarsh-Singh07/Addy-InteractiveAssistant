"""
Model Capability Registry for Gemini Live API models.

Ensures the backend configures and filters configuration options dynamically
based on the capabilities of the selected Live API model.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ModelCapabilities(BaseModel):
    native_audio: bool = True
    function_calling: bool = True
    async_function_calling: bool = False
    affective_dialogue: bool = False
    proactive_audio: bool = False
    thinking: bool = True


MODEL_CAPABILITIES: dict[str, ModelCapabilities] = {
    "gemini-3.1-flash-live-preview": ModelCapabilities(
        native_audio=True,
        function_calling=True,
        async_function_calling=False,
        affective_dialogue=False,
        proactive_audio=False,
        thinking=True,
    ),
    "gemini-2.5-flash-native-audio-preview-12-2025": ModelCapabilities(
        native_audio=True,
        function_calling=True,
        async_function_calling=True,
        affective_dialogue=True,
        proactive_audio=True,
        thinking=False,
    ),
}


class ModelCapabilityRegistry:
    """Registry to query capability profiles of supported models."""

    @staticmethod
    def get_capabilities(model_name: str) -> ModelCapabilities:
        """Get capabilities configuration for a model, defaulting to gemini-3.1 capabilities."""
        return MODEL_CAPABILITIES.get(model_name, MODEL_CAPABILITIES["gemini-3.1-flash-live-preview"])

    @staticmethod
    def filter_unsupported_params(model_name: str, config_dict: dict) -> dict:
        """Filter out unsupported configuration keys from the payload before sending to model."""
        caps = ModelCapabilityRegistry.get_capabilities(model_name)
        filtered = config_dict.copy()

        # If thinking is not supported
        if "thinking_config" in filtered and not caps.thinking:
            filtered.pop("thinking_config", None)

        return filtered
