"""
Hermes integration client — abstract interface + factory.

The HermesClient represents the connection to the existing Hermes agent
running on a separate VPS.

CURRENT STATE (Phase 1):
  - Interface is defined
  - MockHermesClient is the active implementation
  - Real HTTP client is stubbed, waiting for HERMES_URL and HERMES_API_KEY

TOMORROW:
  - Set HERMES_URL and HERMES_API_KEY in .env
  - Set HERMES_MOCK=false
  - The HttpHermesClient will activate automatically

Addy (voice agent) delegates tasks to Hermes, monitors results, and reports
back. Addy NEVER assumes Hermes succeeded without verification.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class HermesCommandStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass
class HermesCommand:
    """A command sent to the Hermes agent."""
    action: str                    # e.g. "update_portfolio", "deploy_project"
    parameters: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None   # set by client if provided


@dataclass
class HermesResult:
    """Result of a command sent to Hermes."""
    correlation_id: str
    status: HermesCommandStatus
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass
class HermesHealth:
    healthy: bool
    version: str = "unknown"
    uptime_s: float | None = None
    message: str = ""


class HermesClient(ABC):
    """
    Abstract client for the Hermes agent.

    All methods are async. The agent loop calls these from VoiceSession
    via the hermes tool handler.
    """

    @abstractmethod
    async def send_command(self, command: HermesCommand) -> HermesResult:
        """
        Send a command to Hermes and wait for the result.

        Does NOT return until the command completes or times out.
        Never returns a "success" status if the outcome is uncertain.
        """
        ...

    @abstractmethod
    async def get_status(self, correlation_id: str) -> HermesResult:
        """
        Poll the status of a previously issued command.
        Used when commands are fire-and-forget.
        """
        ...

    @abstractmethod
    async def health_check(self) -> HermesHealth:
        """Return health status of the Hermes agent."""
        ...

    @abstractmethod
    async def list_capabilities(self) -> list[str]:
        """Return the list of actions this Hermes instance supports."""
        ...
