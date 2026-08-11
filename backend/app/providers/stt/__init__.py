from __future__ import annotations

from app.config.settings import Settings
from app.providers.stt.base import STTProvider


def get_stt_provider(settings: Settings) -> STTProvider:
    from app.providers.stt.deepgram import DeepgramSTT
    api_key = settings.deepgram_api_key
    if not api_key:
        raise ValueError("DEEPGRAM_API_KEY not set in environment")
    return DeepgramSTT(api_key=api_key.get_secret_value())
