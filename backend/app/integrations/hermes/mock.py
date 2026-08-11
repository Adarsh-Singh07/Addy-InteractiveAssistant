"""
Mock Hermes client for Phase 1 development.

Returns plausible fake responses so the agent can handle Hermes-delegated
tasks without a real connection. When HERMES_URL and HERMES_API_KEY are
provided tomorrow, switch HERMES_MOCK=false to activate the real client.
"""

from __future__ import annotations

import asyncio
import uuid

from app.integrations.hermes.client import (
    HermesClient,
    HermesCommand,
    HermesCommandStatus,
    HermesHealth,
    HermesResult,
)
from app.observability.logging import get_logger

log = get_logger(__name__)

MOCK_CAPABILITIES = [
    "update_portfolio",
    "deploy_project",
    "check_deployment_status",
    "restart_service",
    "get_portfolio_info",
    "run_github_action",
]


class MockHermesClient(HermesClient):
    """
    Mock implementation of HermesClient.

    Simulates network delay and returns realistic-looking responses.
    All actions are logged so you can verify the agent is calling the
    right commands with the right parameters.
    """

    async def send_command(self, command: HermesCommand) -> HermesResult:
        correlation_id = command.correlation_id or uuid.uuid4().hex[:12]
        log.info(
            "[MOCK] Hermes command received",
            action=command.action,
            params=command.parameters,
            correlation_id=correlation_id,
        )
        # Simulate network + processing delay
        await asyncio.sleep(0.8)

        # Return mock success for known actions
        if command.action in MOCK_CAPABILITIES:
            return HermesResult(
                correlation_id=correlation_id,
                status=HermesCommandStatus.SUCCESS,
                message=f"[MOCK] {command.action} completed successfully.",
                data={
                    "action": command.action,
                    "params": command.parameters,
                    "mock": True,
                },
            )

        return HermesResult(
            correlation_id=correlation_id,
            status=HermesCommandStatus.FAILED,
            message=f"[MOCK] Unknown action: {command.action!r}",
            error=f"Action {command.action!r} not in mock capabilities",
        )

    async def get_status(self, correlation_id: str) -> HermesResult:
        log.info("[MOCK] Hermes get_status", correlation_id=correlation_id)
        await asyncio.sleep(0.2)
        return HermesResult(
            correlation_id=correlation_id,
            status=HermesCommandStatus.SUCCESS,
            message="[MOCK] Status: completed.",
        )

    async def health_check(self) -> HermesHealth:
        log.debug("[MOCK] Hermes health check")
        return HermesHealth(
            healthy=True,
            version="mock-1.0.0",
            uptime_s=3600.0,
            message="Mock Hermes is always healthy. Set HERMES_MOCK=false when ready.",
        )

    async def list_capabilities(self) -> list[str]:
        return MOCK_CAPABILITIES


class HttpHermesClient(HermesClient):
    """
    Real HTTP client for the Hermes VPS agent.

    STUB — activate when HERMES_URL and HERMES_API_KEY are provided.

    TODO:
    - Implement send_command() via POST to {HERMES_URL}/api/command
    - Implement get_status() via GET {HERMES_URL}/api/status/{correlation_id}
    - Implement health_check() via GET {HERMES_URL}/health
    - Add retry with exponential backoff (max 3 retries)
    - Verify result before reporting success to Addy
    """

    def __init__(self, base_url: str, api_key: str, timeout_s: int = 30) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_s

    async def send_command(self, command: HermesCommand) -> HermesResult:
        raise NotImplementedError(
            "HttpHermesClient.send_command() is not yet implemented. "
            "Set HERMES_MOCK=true to use MockHermesClient."
        )

    async def get_status(self, correlation_id: str) -> HermesResult:
        raise NotImplementedError("HttpHermesClient.get_status() not yet implemented.")

    async def health_check(self) -> HermesHealth:
        raise NotImplementedError("HttpHermesClient.health_check() not yet implemented.")

    async def list_capabilities(self) -> list[str]:
        raise NotImplementedError("HttpHermesClient.list_capabilities() not yet implemented.")


def get_hermes_client(
    mock: bool = True,
    url: str | None = None,
    api_key: str | None = None,
    timeout_s: int = 30,
) -> HermesClient:
    """Factory: return MockHermesClient or HttpHermesClient based on config."""
    if mock:
        log.info("Using MockHermesClient (HERMES_MOCK=true)")
        return MockHermesClient()
    if not url or not api_key:
        log.warning(
            "HERMES_MOCK=false but HERMES_URL or HERMES_API_KEY not set; "
            "falling back to MockHermesClient"
        )
        return MockHermesClient()
    log.info("Using HttpHermesClient", url=url)
    return HttpHermesClient(base_url=url, api_key=api_key, timeout_s=timeout_s)
