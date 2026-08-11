"""
In-memory metrics store for Phase 1.

Tracks:
- Total requests
- Latency histograms (STT, LLM first-token, TTS first-audio, end-to-end)
- Error counts
- Active sessions
- Interruption counts

Benchmarking instruments (per the latency requirements):
- speech_end_ts      → when Deepgram fires UtteranceEnd
- llm_first_token_ts → when first LLM token arrives
- tts_first_audio_ts → when first TTS audio chunk arrives
- client_played_ts   → when audio is sent to browser (proxy for playback start)

All times in milliseconds.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from threading import Lock
from typing import Deque


@dataclass
class TurnLatency:
    """Latency breakdown for a single voice turn."""
    trace_id: str
    session_id: str
    transcript: str = ""

    # Timestamps (Unix epoch ms)
    speech_end_ts: float = 0.0
    llm_first_token_ts: float = 0.0
    tts_first_audio_ts: float = 0.0
    client_audio_sent_ts: float = 0.0
    turn_complete_ts: float = 0.0

    interrupted: bool = False
    error: str | None = None

    # Derived (computed on completion)
    @property
    def stt_to_llm_ms(self) -> float | None:
        if self.speech_end_ts and self.llm_first_token_ts:
            return (self.llm_first_token_ts - self.speech_end_ts) * 1000
        return None

    @property
    def llm_to_tts_ms(self) -> float | None:
        if self.llm_first_token_ts and self.tts_first_audio_ts:
            return (self.tts_first_audio_ts - self.llm_first_token_ts) * 1000
        return None

    @property
    def tts_to_client_ms(self) -> float | None:
        if self.tts_first_audio_ts and self.client_audio_sent_ts:
            return (self.client_audio_sent_ts - self.tts_first_audio_ts) * 1000
        return None

    @property
    def end_to_end_ms(self) -> float | None:
        """speech_end → first audio reaches client."""
        if self.speech_end_ts and self.client_audio_sent_ts:
            return (self.client_audio_sent_ts - self.speech_end_ts) * 1000
        return None

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "transcript_preview": self.transcript[:80],
            "interrupted": self.interrupted,
            "error": self.error,
            "latency_ms": {
                "stt_to_llm": self.stt_to_llm_ms,
                "llm_to_tts": self.llm_to_tts_ms,
                "tts_to_client": self.tts_to_client_ms,
                "end_to_end": self.end_to_end_ms,
            },
        }


class MetricsStore:
    """Thread-safe in-memory metrics store."""

    MAX_HISTORY = 200  # keep last N turns

    def __init__(self) -> None:
        self._lock = Lock()
        self._start_time = time.time()

        # Counters
        self.total_turns: int = 0
        self.total_interruptions: int = 0
        self.total_errors: int = 0
        self.active_sessions: int = 0

        # Provider error counts
        self.provider_errors: dict[str, int] = {}

        # Latency history (recent turns)
        self._turns: Deque[TurnLatency] = deque(maxlen=self.MAX_HISTORY)

    # ── Session tracking ──────────────────────────────────────────────────

    def session_opened(self) -> None:
        with self._lock:
            self.active_sessions += 1

    def session_closed(self) -> None:
        with self._lock:
            self.active_sessions = max(0, self.active_sessions - 1)

    # ── Turn tracking ─────────────────────────────────────────────────────

    def record_turn(self, turn: TurnLatency) -> None:
        with self._lock:
            self.total_turns += 1
            if turn.interrupted:
                self.total_interruptions += 1
            if turn.error:
                self.total_errors += 1
            self._turns.append(turn)

    def record_provider_error(self, provider: str) -> None:
        with self._lock:
            self.provider_errors[provider] = self.provider_errors.get(provider, 0) + 1

    # ── Aggregation ───────────────────────────────────────────────────────

    def summary(self) -> dict:
        with self._lock:
            turns = list(self._turns)

        e2e_values = [t.end_to_end_ms for t in turns if t.end_to_end_ms is not None]

        def pct(values: list[float], p: int) -> float | None:
            if not values:
                return None
            sorted_v = sorted(values)
            idx = max(0, int(len(sorted_v) * p / 100) - 1)
            return round(sorted_v[idx], 1)

        return {
            "uptime_s": round(time.time() - self._start_time, 1),
            "active_sessions": self.active_sessions,
            "total_turns": self.total_turns,
            "total_interruptions": self.total_interruptions,
            "total_errors": self.total_errors,
            "provider_errors": dict(self.provider_errors),
            "end_to_end_latency_ms": {
                "p50": pct(e2e_values, 50),
                "p90": pct(e2e_values, 90),
                "p99": pct(e2e_values, 99),
                "samples": len(e2e_values),
            },
            "recent_turns": [t.to_dict() for t in list(self._turns)[-10:]],
        }


# Global singleton
_metrics = MetricsStore()


def get_metrics() -> MetricsStore:
    return _metrics
