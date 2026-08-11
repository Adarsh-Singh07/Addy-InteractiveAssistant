from __future__ import annotations

from app.config.settings import Settings
from app.providers.tts.base import TTSProvider


def get_tts_provider(settings: Settings) -> TTSProvider:
    from app.providers.tts.deepgram import DeepgramTTS
    api_key = settings.deepgram_api_key
    if not api_key:
        raise ValueError("DEEPGRAM_API_KEY not set in environment")
    return DeepgramTTS(
        api_key=api_key.get_secret_value(),
        model=settings.tts_model,
        sample_rate=settings.tts_sample_rate,
        encoding=settings.tts_encoding,
    )
