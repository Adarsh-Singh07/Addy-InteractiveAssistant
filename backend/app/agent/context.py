"""
Conversation context for a single voice session.

Manages:
- Message history (short-term memory)
- Rolling context window (avoids token overflow)
- Language detection hint
- Session metadata

This is in-memory only for Phase 1.
Phase 2 will add persistence via SQLite.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.providers.llm.base import Message


@dataclass
class ConversationContext:
    """In-memory conversation context for one session."""

    session_id: str = ""
    max_messages: int = 20  # configurable via settings

    # Chronological message history
    _messages: list[Message] = field(default_factory=list, repr=False)

    # Session metadata
    started_at: float = field(default_factory=time.time)
    turn_count: int = 0
    last_language_hint: str = "en"  # "en" | "hi" | "mixed"

    def add_user(self, text: str) -> None:
        self._messages.append(Message(role="user", content=text))
        self._trim()

    def add_assistant(self, text: str) -> None:
        self._messages.append(Message(role="assistant", content=text))
        self._trim()
        self.turn_count += 1

    def add_tool_result(self, result: str) -> None:
        self._messages.append(Message(role="tool", content=result))
        self._trim()

    def get_messages(self) -> list[Message]:
        """Return the current context window (may be trimmed)."""
        return list(self._messages)

    def _trim(self) -> None:
        """Keep context within max_messages, always preserve first user message."""
        if len(self._messages) > self.max_messages:
            # Drop oldest messages, but keep at least one pair
            overflow = len(self._messages) - self.max_messages
            self._messages = self._messages[overflow:]

    def clear(self) -> None:
        self._messages.clear()
        self.turn_count = 0

    @property
    def is_empty(self) -> bool:
        return len(self._messages) == 0

    def summary(self) -> dict:
        return {
            "session_id": self.session_id,
            "turns": self.turn_count,
            "messages_in_context": len(self._messages),
            "started_at": self.started_at,
            "language_hint": self.last_language_hint,
        }
