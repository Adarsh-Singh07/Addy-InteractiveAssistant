"""
Unit and integration tests for Phase 1.5 - Gemini Live Voice Engine & Character System.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.agent.character import CharacterManager, CharacterProfile, NOVA_PRESET, ATLAS_PRESET
from app.config.settings import get_settings
from app.providers.llm.live_capabilities import ModelCapabilityRegistry, ModelCapabilities
from app.providers.llm.live_provider import GeminiLiveProvider
from app.voice.engine import GeminiLiveEngine, CascadedVoiceEngine
from app.voice.session_manager import LiveSessionManager
from google.genai import types
from app.voice.transport import AudioChunk, AudioFormat


# ── 1. Model Capability Registry Tests ────────────────────────────────────────

def test_capability_registry_lookups():
    # Verify prebuilt profiles
    caps_31 = ModelCapabilityRegistry.get_capabilities("gemini-3.1-flash-live-preview")
    assert caps_31.native_audio is True
    assert caps_31.thinking is True
    assert caps_31.affective_dialogue is False  # Only 2.5 has affective dialog

    caps_25 = ModelCapabilityRegistry.get_capabilities("gemini-2.5-flash-native-audio-preview-12-2025")
    assert caps_25.native_audio is True
    assert caps_25.affective_dialogue is True
    assert caps_25.proactive_audio is True


def test_capability_registry_filtering():
    # Filter unsupported keys for 3.1
    config_dict = {"thinking_config": {"thinking_budget": 1024}, "other_param": "val"}
    # Thinking is supported on both, so thinking_config should NOT be removed
    res_31 = ModelCapabilityRegistry.filter_unsupported_params("gemini-3.1-flash-live-preview", config_dict)
    assert "thinking_config" in res_31


# ── 2. Character System Tests ───────────────────────────────────────────────

def test_character_manager_presets():
    manager = CharacterManager()
    
    # Get Nova — voice is now Kore (distinct from Addy's Aoede)
    nova = manager.get_character("nova")
    assert nova.name == "Nova"
    assert nova.voice == "Kore"
    
    # Get Atlas
    atlas = manager.get_character("atlas")
    assert atlas.name == "Atlas"
    assert atlas.voice == "Charon"

    # Default to Addy on unknown ID
    unknown = manager.get_character("unknown_id")
    assert unknown.name == "Addy"



def test_character_prompt_generation():
    # CharacterProfile now requires public and admin instruction variants
    char = CharacterProfile(
        character_id="test_char",
        name="TestBot",
        display_name="Test Bot",
        description="Testing bot profile",
        voice="Kore",
        personality="helpful",
        warmth=0.9,
        technical_level=0.1,
        system_instructions_public="Public test instruction.",
        system_instructions_admin="Admin test instruction.",
    )

    # Test public mode prompt
    prompt_public = char.generate_system_instruction(
        user_name="Adarsh",
        agent_name="Addy",
        timezone="Asia/Kolkata",
        access_context="public",
    )
    assert "TestBot" in prompt_public
    assert "Asia/Kolkata" in prompt_public
    assert "Public test instruction." in prompt_public
    assert "Highly warm" in prompt_public
    # Public mode must NOT reference Adarsh as the visitor
    assert "visitor" in prompt_public

    # Test admin mode prompt
    prompt_admin = char.generate_system_instruction(
        user_name="Adarsh",
        agent_name="Addy",
        timezone="Asia/Kolkata",
        access_context="admin",
    )
    assert "Admin test instruction." in prompt_admin
    # Admin mode should address Adarsh as the user
    assert "Adarsh" in prompt_admin


def test_character_manager_updates():
    manager = CharacterManager()
    updated = manager.update_character_params("nova", {"voice": "Kore", "warmth": 0.95})
    assert updated.voice == "Kore"
    assert updated.warmth == 0.95
    
    # Retrieve again to verify persistence
    retrieved = manager.get_character("nova")
    assert retrieved.voice == "Kore"


# ── 3. Gemini Live Connection & Config Tests ──────────────────────────────────

@patch("google.genai.Client")
def test_live_provider_config_builder(mock_client):
    settings = get_settings()
    provider = GeminiLiveProvider(settings)

    # Build config for 3.1
    config_31 = provider.build_connect_config(
        model="gemini-3.1-flash-live-preview",
        system_instruction="Instruction text",
        voice_name="Aoede",
        thinking_level="medium",
    )
    assert config_31.response_modalities == [types.Modality.AUDIO]
    assert config_31.speech_config.voice_config.prebuilt_voice_config.voice_name == "Aoede"
    
    # Build config for 2.5
    config_25 = provider.build_connect_config(
        model="gemini-2.5-flash-native-audio-preview-12-2025",
        system_instruction="Instruction text",
        voice_name="Charon",
        affective_dialogue=True,
    )
    assert config_25.speech_config.voice_config.prebuilt_voice_config.voice_name == "Charon"


# ── 4. Engine Abstraction Tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_engine_delegations():
    # 1. Test Cascaded delegator
    mock_session = MagicMock()
    mock_session.run = AsyncMock()
    mock_session._handle_audio = AsyncMock()
    mock_session._handle_interrupt = AsyncMock()
    
    cascaded_engine = CascadedVoiceEngine(mock_session)
    await cascaded_engine.run()
    mock_session.run.assert_called_once()
    
    chunk = AudioChunk(data=b"\x00\x00", format=AudioFormat.LINEAR16)
    await cascaded_engine.handle_audio(chunk)
    mock_session._handle_audio.assert_called_once_with(chunk)
    
    await cascaded_engine.handle_interrupt()
    mock_session._handle_interrupt.assert_called_once()

    # 2. Test GeminiLive delegator
    mock_manager = MagicMock()
    mock_manager.run = AsyncMock()
    mock_manager.handle_audio = AsyncMock()
    mock_manager.handle_interrupt = AsyncMock()
    
    live_engine = GeminiLiveEngine(mock_manager)
    await live_engine.run()
    mock_manager.run.assert_called_once()
    
    await live_engine.handle_audio(chunk)
    mock_manager.handle_audio.assert_called_once_with(chunk)
    
    await live_engine.handle_interrupt()
    mock_manager.handle_interrupt.assert_called_once()
