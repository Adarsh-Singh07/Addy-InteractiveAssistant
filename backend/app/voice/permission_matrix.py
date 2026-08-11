"""
Access permission matrix defining AccessMode (PUBLIC vs ADMIN),
allowed assistant characters, and registered tool lists.
"""

from __future__ import annotations

from enum import Enum


class AccessMode(Enum):
    PUBLIC = "PUBLIC"
    ADMIN = "ADMIN"


# Allowed characters mapping
_ALLOWED_CHARACTERS = {
    AccessMode.PUBLIC: ["addy", "nova"],
    AccessMode.ADMIN: ["addy", "nova", "atlas"],
}

# Registered tools mapping
_ALLOWED_TOOLS = {
    AccessMode.PUBLIC: [
        "portfolio_search",
        "collect_lead_info",
        "transfer_to_agent",
    ],
    AccessMode.ADMIN: [
        "portfolio_search",
        "collect_lead_info",
        "transfer_to_agent",
        "hermes_get_status",
        "hermes_check_deployment",
        "hermes_deploy_project",
        "hermes_restart_service",
        "hermes_git_update",
        "read_calendar_availability",
        "send_admin_email",
    ],
}


def get_allowed_characters(mode: AccessMode) -> list[str]:
    """Retrieve list of characters accessible under specified mode."""
    return _ALLOWED_CHARACTERS.get(mode, _ALLOWED_CHARACTERS[AccessMode.PUBLIC])


def is_character_allowed(character: str, mode: AccessMode) -> bool:
    """Check if a character profile is accessible under specified mode."""
    return character.lower() in get_allowed_characters(mode)


def get_allowed_tools(mode: AccessMode) -> list[str]:
    """Retrieve list of functions registered under specified mode."""
    return _ALLOWED_TOOLS.get(mode, _ALLOWED_TOOLS[AccessMode.PUBLIC])
