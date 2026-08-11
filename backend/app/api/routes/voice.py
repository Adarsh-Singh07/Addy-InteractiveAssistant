"""
Voice WebSocket endpoint.

ws://localhost:8000/ws/voice
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.agent.agent import AgentCore
from app.agent.character import CharacterManager
from app.config.settings import get_settings
from app.integrations.hermes.mock import get_hermes_client
from app.observability.logging import bind_trace_id, get_logger
from app.providers.llm import get_llm_provider
from app.providers.stt import get_stt_provider
from app.providers.tts import get_tts_provider
from app.voice.session import VoiceSession
from app.voice.websocket_transport import WebSocketTransport

log = get_logger(__name__)
router = APIRouter(tags=["voice"])
settings = get_settings()


def _build_agent() -> AgentCore:
    """Build the agent with primary + fallback LLM providers."""
    primary = get_llm_provider(settings)
    fallback = None
    if settings.llm_fallback_provider and settings.llm_fallback_provider != settings.llm_provider:
        try:
            fallback = get_llm_provider(settings, settings.llm_fallback_provider)
        except ValueError as exc:
            log.warning("Fallback LLM not configured", reason=str(exc))
    return AgentCore(primary_llm=primary, fallback_llm=fallback, settings=settings)


# Build agent once at import time
_agent = _build_agent()
_stt = None
_tts = None


def _get_lazy_stt():
    global _stt
    if _stt is None:
        _stt = get_stt_provider(settings)
    return _stt


def _get_lazy_tts():
    global _tts
    if _tts is None:
        _tts = get_tts_provider(settings)
    return _tts



@router.websocket("/ws/voice")
async def voice_websocket(
    websocket: WebSocket,
    character: str = "addy",
    model: str = "gemini-2.5-flash",
    voice: str = "Aoede",
    engine: str = "gemini_live",
):
    """Main voice WebSocket endpoint supporting Gemini Live and Cascaded fallback."""
    await websocket.accept()
    session_id = uuid.uuid4().hex[:12]
    bind_trace_id()

    # Determine AccessMode based on HTTP-only session cookie
    from app.api.routes.auth import verify_token, COOKIE_NAME
    from app.voice.permission_matrix import AccessMode, is_character_allowed

    cookie_token = websocket.cookies.get(COOKIE_NAME)
    access_mode = AccessMode.ADMIN if verify_token(cookie_token) else AccessMode.PUBLIC

    # Guard against unauthorized characters
    if not is_character_allowed(character, access_mode):
        log.warning("Unauthorized character requested. Falling back to default 'addy'.", character=character, mode=access_mode)
        character = "addy"

    log.info(
        "WebSocket connected",
        session_id=session_id,
        character=character,
        model=model,
        voice=voice,
        engine=engine,
        access_mode=access_mode.value,
        client=str(websocket.client),
    )

    transport = WebSocketTransport(websocket)
    engine_instance = None
    warning_sent = False

    # Check if we should initialize primary Gemini Live engine
    if engine == "gemini_live":
        try:
            # Check for API key
            gemini_key = settings.get_llm_api_key("gemini")
            if not gemini_key:
                raise ValueError("GEMINI_API_KEY not configured in environment settings")

            from app.providers.llm.live_provider import GeminiLiveProvider
            from app.voice.session_manager import LiveSessionManager
            from app.voice.engine import GeminiLiveEngine

            provider = GeminiLiveProvider(settings)
            char_mgr = CharacterManager()
            char_profile = char_mgr.get_character(character)

            # Match voice to character profile default if not custom requested
            if voice == "Aoede" and char_profile.voice != "Aoede":
                voice = char_profile.voice

            manager = LiveSessionManager(
                session_id=session_id,
                transport=transport,
                provider=provider,
                character=char_profile,
                model=model,
                voice=voice,
                settings=settings,
                access_mode=access_mode,
            )
            engine_instance = GeminiLiveEngine(manager)
            log.info("Successfully initialized GeminiLiveEngine", session_id=session_id)
        except Exception as exc:
            log.warning("Failed to initialize Gemini Live Engine. Falling back to cascaded.", error=str(exc))
            warning_sent = True


    # Initialize fallback CascadedVoiceEngine if Gemini Live was not selected or failed
    if engine_instance is None:
        from app.voice.engine import CascadedVoiceEngine
        try:
            stt_inst = _get_lazy_stt()
            tts_inst = _get_lazy_tts()
            session = VoiceSession(
                session_id=session_id,
                transport=transport,
                stt=stt_inst,
                tts=tts_inst,
                agent=_agent,
                stt_model=settings.stt_model,
                stt_language=settings.stt_language,
                stt_sample_rate=settings.stt_sample_rate,
                stt_encoding=settings.stt_encoding,
                stt_endpointing_ms=settings.stt_endpointing_ms,
            )
            engine_instance = CascadedVoiceEngine(session)
            log.info("Successfully initialized CascadedVoiceEngine fallback", session_id=session_id)
        except Exception as exc:
            log.error("Failed to initialize Cascaded fallback engine", error=str(exc))
            # Send error status to client
            await transport.send_event("error", {"message": "Voice service currently unavailable. Please verify API configuration."})
            return


    try:
        if warning_sent:
            await transport.send_event(
                "error",
                {"message": "Gemini Live API connection failed. Switched to cascaded fallback mode."}
            )
        await engine_instance.run()
    except WebSocketDisconnect:
        log.info("WebSocket disconnected", session_id=session_id)
    except Exception as exc:
        log.error("Unhandled session error", session_id=session_id, error=str(exc))
