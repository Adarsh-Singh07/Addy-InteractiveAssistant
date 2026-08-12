"""
Tool registry containing Gemini function declarations
and Python function handlers for all Addy capabilities.

Security model:
  PUBLIC  → portfolio_search, collect_lead_info, transfer_to_agent (addy/nova only)
  ADMIN   → all above + hermes_*, calendar, email, transfer_to_agent (includes atlas)
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Callable, Dict, List
from google.genai import types
from app.config.settings import get_settings
from app.observability.logging import get_logger
from app.db import save_lead
from app.voice.permission_matrix import AccessMode

log = get_logger(__name__)
settings = get_settings()

# Type alias for tool execution handler
ToolHandler = Callable[..., Any]


# ── Subprocess Hermes CLI Executor ───────────────────────────────────────────

def _run_hermes_cli(query: str) -> dict[str, Any]:
    """Execute a single query against Hermes CLI using a secure subprocess."""
    try:
        hermes_home = os.environ.get("HERMES_HOME", "/home/ubuntu/.hermes")
        hermes_cli_py = os.path.join(hermes_home, "hermes-agent", "cli.py")
        hermes_python = os.path.join(hermes_home, "hermes-agent", "venv", "bin", "python")

        if not os.path.exists(hermes_cli_py):
            log.warning(
                "Hermes CLI not found at configured path",
                path=hermes_cli_py,
            )
            return {
                "success": False,
                "error": (
                    f"Hermes is not reachable. CLI not found at: {hermes_cli_py}. "
                    "Please verify HERMES_HOME is correctly configured on the VPS."
                ),
            }

        log.info("Invoking Hermes CLI subprocess", query_preview=query[:60])
        env = os.environ.copy()
        env["HERMES_HOME"] = hermes_home

        res = subprocess.run(
            [hermes_python, hermes_cli_py, "-q", query, "--quiet"],
            capture_output=True,
            text=True,
            timeout=45,
            env=env,
        )

        stdout = res.stdout.strip()
        stderr = res.stderr.strip()
        exit_code = res.returncode

        log.info("Hermes CLI execution complete", exit_code=exit_code)

        if exit_code == 0:
            return {"success": True, "output": stdout}
        else:
            return {"success": False, "error": stderr or f"Process exited with code {exit_code}"}

    except subprocess.TimeoutExpired:
        log.warning("Hermes CLI execution timed out")
        return {"success": False, "error": "Hermes execution timed out after 45 seconds."}
    except Exception as exc:
        log.error("Hermes CLI subprocess failed", error=str(exc))
        return {"success": False, "error": str(exc)}


# ── Python Tool Handlers ──────────────────────────────────────────────────────

async def handle_portfolio_search(query: str) -> dict[str, Any]:
    """Search Adarsh's portfolio CV database via the portfolio backend API."""
    import httpx
    portfolio_url = settings.portfolio_backend_url
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            url = f"{portfolio_url}/api/v1/portfolio/rag/playground"
            resp = await client.get(url, params={"query": query})
            if resp.status_code == 200:
                return {"success": True, "results": resp.json()}
            return {
                "success": False,
                "error": f"Portfolio API returned status {resp.status_code}",
            }
    except httpx.ConnectError:
        log.warning("Portfolio backend unreachable", url=portfolio_url)
        return {
            "success": False,
            "error": (
                "Portfolio information is temporarily unavailable. "
                "I'll answer based on what I know, but cannot retrieve real-time details right now."
            ),
        }
    except Exception as exc:
        log.error("Portfolio RAG tool failed", error=str(exc))
        return {"success": False, "error": str(exc)}


async def handle_collect_lead_info(name: str, email: str, requirements: str) -> dict[str, Any]:
    """Collect outreach contact information and save to SQLite db."""
    try:
        save_lead(name, email, requirements)
        log.info("Lead collected successfully", name=name)
        return {
            "success": True,
            "message": f"Contact request saved. Adarsh has been notified about {name}'s enquiry.",
        }
    except Exception as exc:
        log.error("Lead collection tool failed", error=str(exc))
        return {"success": False, "error": str(exc)}


async def handle_transfer_to_agent(agent_name: str) -> dict[str, Any]:
    """
    Switches the session's active assistant persona.

    Note: The transfer target is validated at the session level against
    the current AccessMode. Public sessions cannot transfer to 'atlas'.
    """
    return {"success": True, "action": "TRANSFER", "target": agent_name.lower()}


async def handle_hermes_get_status() -> dict[str, Any]:
    """Check Hermes server, active gateway status, and systems (admin only)."""
    return _run_hermes_cli("Check server and gateway status.")


async def handle_hermes_check_deployment(project: str) -> dict[str, Any]:
    """Check project deployment logs and branch health (admin only)."""
    return _run_hermes_cli(f"Check deployment status for project {project}.")


async def handle_hermes_deploy_project(
    project: str, target: str, confirm: bool = False
) -> dict[str, Any]:
    """Deploy a target project to environment (requires verbal confirmation, admin only)."""
    if not confirm:
        return {
            "success": False,
            "status": "CONFIRMATION_REQUIRED",
            "message": (
                f"Deploying {project} to {target} will restart the service and apply code changes. "
                "Please ask Adarsh to confirm before proceeding."
            ),
        }
    return _run_hermes_cli(f"Deploy project {project} to target environment {target}.")


async def handle_hermes_restart_service(service: str, confirm: bool = False) -> dict[str, Any]:
    """Restart a system service (requires verbal confirmation, admin only)."""
    if not confirm:
        return {
            "success": False,
            "status": "CONFIRMATION_REQUIRED",
            "message": (
                f"Restarting service '{service}' will cause a brief outage. "
                "Please ask Adarsh to confirm before proceeding."
            ),
        }
    return _run_hermes_cli(f"Restart system service {service}.")


async def handle_hermes_git_update(project: str, confirm: bool = False) -> dict[str, Any]:
    """Fetch and pull git repository updates (requires verbal confirmation, admin only)."""
    if not confirm:
        return {
            "success": False,
            "status": "CONFIRMATION_REQUIRED",
            "message": (
                f"Pulling updates for {project} will apply the latest code changes. "
                "Please ask Adarsh to confirm before proceeding."
            ),
        }
    return _run_hermes_cli(f"Git pull updates and resolve conflicts for {project}.")


async def handle_read_calendar_availability() -> dict[str, Any]:
    """Read calendar availability (Admin only)."""
    # Placeholder — real integration pending
    return {
        "success": True,
        "availability": "Calendar integration is not yet configured. Contact Adarsh directly for scheduling.",
    }


async def handle_send_admin_email(to: str, subject: str, body: str) -> dict[str, Any]:
    """Send administrative email (Admin only)."""
    # Placeholder — real Zoho integration pending
    log.info("Admin email requested", to=to, subject=subject)
    return {
        "success": False,
        "error": "Email integration is not yet configured. This feature is coming soon.",
    }


# ── Function Declarations ─────────────────────────────────────────────────────

# Public tools — safe for any visitor
_PUBLIC_DECLARATIONS = [
    types.FunctionDeclaration(
        name="portfolio_search",
        description=(
            "Search Adarsh's portfolio and CV database to answer questions about "
            "his projects, skills, experience, or services."
        ),
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "query": types.Schema(
                    type="STRING",
                    description="The search query to retrieve relevant portfolio information.",
                )
            },
            required=["query"],
        ),
    ),
    types.FunctionDeclaration(
        name="collect_lead_info",
        description=(
            "Collect contact information (name, email, requirements) from a visitor "
            "who wants to get in touch with or hire Adarsh. "
            "Only call this AFTER the visitor has confirmed their details."
        ),
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "name": types.Schema(type="STRING", description="Visitor's name"),
                "email": types.Schema(type="STRING", description="Visitor's email address"),
                "requirements": types.Schema(
                    type="STRING",
                    description="What the visitor wants to discuss or request",
                ),
            },
            required=["name", "email", "requirements"],
        ),
    ),
    types.FunctionDeclaration(
        name="transfer_to_agent",
        description=(
            "Switch the conversation to another assistant persona. "
            "Public users can only transfer to 'addy' or 'nova'. "
            "'atlas' is restricted to authenticated administrators only."
        ),
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "agent_name": types.Schema(
                    type="STRING",
                    description=(
                        "Target persona ID: 'addy' (public AI twin) or 'nova' (contact specialist). "
                        "Do NOT transfer to 'atlas' for public visitors."
                    ),
                )
            },
            required=["agent_name"],
        ),
    ),
]

# Admin tools — includes hermes, email, calendar, and atlas access
_ADMIN_DECLARATIONS = _PUBLIC_DECLARATIONS + [
    types.FunctionDeclaration(
        name="hermes_get_status",
        description="Check active server status, messaging gateway processes, and system health.",
        parameters=types.Schema(type="OBJECT", properties={}),
    ),
    types.FunctionDeclaration(
        name="hermes_check_deployment",
        description="Check deployment status, Git branch sync status, and deployment logs of a project.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "project": types.Schema(type="STRING", description="Name of the project to check")
            },
            required=["project"],
        ),
    ),
    types.FunctionDeclaration(
        name="hermes_deploy_project",
        description="Deploy a target project to environment (requires verbal confirmation from Adarsh).",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "project": types.Schema(type="STRING", description="Project name"),
                "target": types.Schema(
                    type="STRING", description="Target environment (e.g. production)"
                ),
                "confirm": types.Schema(
                    type="BOOLEAN",
                    description="Set to true ONLY after Adarsh has verbally confirmed the deployment.",
                ),
            },
            required=["project", "target"],
        ),
    ),
    types.FunctionDeclaration(
        name="hermes_restart_service",
        description="Restart a systemd service on the VPS (requires verbal confirmation from Adarsh).",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "service": types.Schema(
                    type="STRING", description="Service name (e.g. nginx, addy, portfolio)"
                ),
                "confirm": types.Schema(
                    type="BOOLEAN",
                    description="Set to true ONLY after Adarsh has verbally confirmed the restart.",
                ),
            },
            required=["service"],
        ),
    ),
    types.FunctionDeclaration(
        name="hermes_git_update",
        description="Git pull and update a code repository (requires verbal confirmation from Adarsh).",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "project": types.Schema(type="STRING", description="Project repo name"),
                "confirm": types.Schema(
                    type="BOOLEAN",
                    description="Set to true ONLY after Adarsh has verbally confirmed the git pull.",
                ),
            },
            required=["project"],
        ),
    ),
    types.FunctionDeclaration(
        name="read_calendar_availability",
        description="Read Adarsh's calendar availability for scheduling.",
        parameters=types.Schema(type="OBJECT", properties={}),
    ),
    types.FunctionDeclaration(
        name="send_admin_email",
        description="Send an administrative email to a recipient.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "to": types.Schema(type="STRING", description="Recipient email address"),
                "subject": types.Schema(type="STRING", description="Email subject"),
                "body": types.Schema(type="STRING", description="Email body content"),
            },
            required=["to", "subject", "body"],
        ),
    ),
]

# Handler map
_HANDLER_MAP: dict[str, ToolHandler] = {
    "portfolio_search": handle_portfolio_search,
    "collect_lead_info": handle_collect_lead_info,
    "transfer_to_agent": handle_transfer_to_agent,
    "hermes_get_status": handle_hermes_get_status,
    "hermes_check_deployment": handle_hermes_check_deployment,
    "hermes_deploy_project": handle_hermes_deploy_project,
    "hermes_restart_service": handle_hermes_restart_service,
    "hermes_git_update": handle_hermes_git_update,
    "read_calendar_availability": handle_read_calendar_availability,
    "send_admin_email": handle_send_admin_email,
}

# Admin-only handler names — rejected if called in PUBLIC mode
_ADMIN_ONLY_TOOLS = {
    "hermes_get_status",
    "hermes_check_deployment",
    "hermes_deploy_project",
    "hermes_restart_service",
    "hermes_git_update",
    "read_calendar_availability",
    "send_admin_email",
}


def get_live_tools(mode: AccessMode) -> list[types.Tool]:
    """Retrieve Tool list with appropriate function declarations for the AccessMode."""
    declarations = _ADMIN_DECLARATIONS if mode == AccessMode.ADMIN else _PUBLIC_DECLARATIONS
    return [types.Tool(function_declarations=declarations)]


async def execute_tool(
    name: str,
    arguments: dict[str, Any],
    mode: AccessMode = AccessMode.PUBLIC,
) -> dict[str, Any]:
    """Execute tool handler by function name, enforcing access control."""
    # Hard enforcement: admin-only tools cannot be called in PUBLIC sessions
    if name in _ADMIN_ONLY_TOOLS and mode != AccessMode.ADMIN:
        log.warning("Public session attempted to call admin-only tool", tool=name)
        return {
            "success": False,
            "error": f"Tool '{name}' is restricted to authenticated administrators.",
        }

    handler = _HANDLER_MAP.get(name)
    if not handler:
        return {"success": False, "error": f"Tool '{name}' is not registered."}

    try:
        return await handler(**arguments)
    except Exception as exc:
        log.error("Tool execution failed", name=name, error=str(exc))
        return {"success": False, "error": str(exc)}
