"""
WebSocket implementation of VoiceTransport.

Bridges FastAPI WebSocket ↔ VoiceTransport abstraction.

Protocol:
  Browser → Backend (binary): raw audio bytes
  Browser → Backend (text/JSON): control messages
    {"type": "interrupt"}
    {"type": "ping"}
    {"type": "settings", "payload": {...}}

  Backend → Browser (binary): PCM audio bytes for playback
  Backend → Browser (text/JSON): events
    {"type": "status", "state": "listening"|"thinking"|"speaking"|"interrupted"|"error"}
    {"type": "transcript", "text": "...", "is_final": bool}
    {"type": "response_token", "token": "..."}
    {"type": "response_complete", "text": "..."}
    {"type": "metrics", ...latency_data...}
    {"type": "error", "message": "..."}
    {"type": "pong"}
"""

from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import WebSocket, WebSocketDisconnect

from app.observability.logging import get_logger
from app.voice.transport import AudioChunk, AudioFormat, TransportMessage, VoiceTransport

log = get_logger(__name__)


class WebSocketTransport(VoiceTransport):
    """
    Phase 1 transport implementation using FastAPI WebSocket.

    Audio format: webm/opus (MediaRecorder default).
    Deepgram STT accepts webm directly, so no transcoding needed.

    Upgrade notes:
    - To switch to raw PCM: change audio_format hint and update STT options
    - To switch to WebRTC: implement WebRTCTransport with same interface
    """

    def __init__(self, websocket: WebSocket) -> None:
        self._ws = websocket
        self._connected = True

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def receive(self) -> AsyncIterator[TransportMessage]:
        """Yield messages from the browser until disconnect."""
        try:
            while self._connected:
                try:
                    # FastAPI WebSocket can receive either bytes or text
                    data = await self._ws.receive()
                except WebSocketDisconnect:
                    self._connected = False
                    return

                if data["type"] == "websocket.receive":
                    if "bytes" in data and data["bytes"]:
                        # Binary = audio chunk
                        yield TransportMessage(
                            type="audio",
                            audio=AudioChunk(
                                data=data["bytes"],
                                format=AudioFormat.WEBM_OPUS,
                                sample_rate=16000,
                            ),
                        )
                    elif "text" in data and data["text"]:
                        try:
                            payload = json.loads(data["text"])
                            msg_type = payload.get("type", "unknown")
                            yield TransportMessage(
                                type=msg_type,
                                payload=payload,
                            )
                        except json.JSONDecodeError:
                            log.warning("Invalid JSON from client", data=data["text"][:100])

                elif data["type"] == "websocket.disconnect":
                    self._connected = False
                    return

        except Exception as exc:
            log.error("WebSocket receive error", error=str(exc))
            self._connected = False

    async def send_audio(self, audio_bytes: bytes) -> None:
        """Send PCM audio bytes to the browser for playback."""
        if not self._connected:
            return
        try:
            await self._ws.send_bytes(audio_bytes)
        except Exception as exc:
            log.warning("WebSocket send_audio error", error=str(exc))
            self._connected = False

    async def send_event(self, event_type: str, payload: dict | None = None) -> None:
        """Send a JSON control event to the browser."""
        if not self._connected:
            return
        try:
            msg = {"type": event_type}
            if payload:
                msg.update(payload)
            await self._ws.send_text(json.dumps(msg))
        except Exception as exc:
            log.warning("WebSocket send_event error", event=event_type, error=str(exc))
            self._connected = False

    async def close(self) -> None:
        if self._connected:
            try:
                await self._ws.close()
            except Exception:
                pass
            finally:
                self._connected = False
