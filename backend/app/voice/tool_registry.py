"""
Tool registry containing Gemini function declarations
and Python function handlers for all Addy capabilities.
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
        # Default venv python path for Hermes on the VPS
        hermes_home = os.environ.get("HERMES_HOME", "/home/ubuntu/.hermes")
        hermes_cli_py = os.path.join(hermes_home, "hermes-agent", "cli.py")
        hermes_python = os.path.join(hermes_home, "hermes-agent", "venv", "bin", "python")

        if not os.path.exists(hermes_cli_py):
            # Fallback path if we are running locally/differently
            hermes_cli_py = "E:\\Projects\\hermes-agent\\cli.py"
            hermes_python = "python"

        log.info("Invoking Hermes CLI subprocess", query=query)
        env = os.environ.copy()
        env["HERMES_HOME"] = hermes_home

        # Execute subprocess
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

        log.info("Hermes CLI finished execution", exit_code=exit_code)

        if exit_code == 0:
            return {"success": True, "output": stdout}
        else:
            return {"success": False, "error": stderr or f"Process exited with code {exit_code}"}

    except subprocess.TimeoutExpired:
        log.warning("Hermes CLI execution timed out")
        return {"success": False, "error": "Hermes execution timed out after 45 seconds"}
    except Exception as exc:
        log.error("Hermes CLI subprocess invocation failed", error=str(exc))
        return {"success": False, "error": str(exc)}


# ── Typed Python Tool Handlers ────────────────────────────────────────────────

async def handle_portfolio_search(query: str) -> dict[str, Any]:
    """Search Adarsh's portfolio CV database via the local API endpoint."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            url = "http://127.0.0.1:8000/api/v1/portfolio/rag/playground"
            resp = await client.get(url, params={"query": query})
            if resp.status_code == 200:
                return {"success": True, "results": resp.json()}
            return {"success": False, "error": f"API returned code {resp.status_code}"}
    except Exception as exc:
        log.error("Portfolio RAG tool failed", error=str(exc))
        return {"success": False, "error": str(exc)}


async def handle_collect_lead_info(name: str, email: str, requirements: str) -> dict[str, Any]:
    """Collect outreach contact information and save to SQLite db."""
    try:
        save_lead(name, email, requirements)
        log.info("Lead collected successfully", name=name, email=email)
        return {"success": True, "message": "Outreach contact details saved successfully."}
    except Exception as exc:
        log.error("Lead collection tool failed", error=str(exc))
        return {"success": False, "error": str(exc)}


async def handle_transfer_to_agent(agent_name: str) -> dict[str, Any]:
    """Switches the session's active assistant agent persona."""
    # Handled at the session level; return routing state to session loop
    return {"success": True, "action": "TRANSFER", "target": agent_name.lower()}


async def handle_hermes_get_status() -> dict[str, Any]:
    """Check Hermes server, active gateway status, and systems."""
    return _run_hermes_cli("Check server and gateway status.")


async def handle_hermes_check_deployment(project: str) -> dict[str, Any]:
    """Check project deployment logs and branch health."""
    return _run_hermes_cli(f"Check deployment status for project {project}.")


async def handle_hermes_deploy_project(project: str, target: str, confirm: bool = False) -> dict[str, Any]:
    """Deploy a target project to environment."""
    if not confirm:
        return {
            "success": False,
            "status": "CONFIRMATION_REQUIRED",
            "message": f"Deploying {project} to {target} requires verbal confirmation. Ask user to confirm."
        }
    return _run_hermes_cli(f"Deploy project {project} to target environment {target}.")


async def handle_hermes_restart_service(service: str, confirm: bool = False) -> dict[str, Any]:
    """Restart a system service."""
    if not confirm:
        return {
            "success": False,
            "status": "CONFIRMATION_REQUIRED",
            "message": f"Restarting system service {service} requires verbal confirmation. Ask user to confirm."
        }
    return _run_hermes_cli(f"Restart system service {service}.")


async def handle_hermes_git_update(project: str, confirm: bool = False) -> dict[str, Any]:
    """Fetch updates, clean conflict, and pull git repository."""
    if not confirm:
        return {
            "success": False,
            "status": "CONFIRMATION_REQUIRED",
            "message": f"Git pulling and updating {project} requires verbal confirmation. Ask user to confirm."
        }
    return _run_hermes_cli(f"Git pull updates and resolve conflicts for {project}.")


async def handle_read_calendar_availability() -> dict[str, Any]:
    """Read calendar availability (Admin only)."""
    # Placeholder integration
    return {"success": True, "availability": "Adarsh is free between 2:00 PM and 5:00 PM IST today."}


async def handle_send_admin_email(to: str, subject: str, body: str) -> dict[str, Any]:
    """Send administrative email via Zoho Mail (Admin only)."""
    # Placeholder integration
    log.info("Sending admin email", to=to, subject=subject)
    return {"success": True, "message": f"Email sent successfully to {to}."}


# ── Function Declaration Registries ──────────────────────────────────────────

_PUBLIC_DECLARATIONS = [
    types.FunctionDeclaration(
        name="portfolio_search",
        description="Search Adarsh's portfolio CV database to answer questions about projects, experience, or skills.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "query": types.Schema(
                    type="STRING",
                    description="The search keywords to retrieve relevant CV chunks."
                )
            },
            required=["query"]
        )
    ),
    types.FunctionDeclaration(
        name="collect_lead_info",
        description="Collect outreach name, email, and description from a recruiter or client looking to hire Adarsh.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "name": types.Schema(type="STRING", description="Visitor's name"),
                "email": types.Schema(type="STRING", description="Visitor's email address"),
                "requirements": types.Schema(type="STRING", description="Outreach details/message"),
            },
            required=["name", "email", "requirements"]
        )
    ),
    types.FunctionDeclaration(
        name="transfer_to_agent",
        description="Switch the conversation to another assistant agent (addy, nova, or atlas).",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "agent_name": types.Schema(
                    type="STRING",
                    description="The character profile ID to switch to: 'addy' (public twin), 'nova' (concierge), or 'atlas' (senior engineer)."
                )
            },
            required=["agent_name"]
        )
    )
]

_ADMIN_DECLARATIONS = _PUBLIC_DECLARATIONS + [
    types.FunctionDeclaration(
        name="hermes_get_status",
        description="Check active server status, messaging gateway processes, and general systems.",
        parameters=types.Schema(type="OBJECT", properties={})
    ),
    types.FunctionDeclaration(
        name="hermes_check_deployment",
        description="Check deployment status, Git branch sync status, and deployment logs of a project.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "project": types.Schema(type="STRING", description="Name of the project to check")
            },
            required=["project"]
        )
    ),
    types.FunctionDeclaration(
        name="hermes_deploy_project",
        description="Deploy a target project to environment (requires verbal confirmation).",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "project": types.Schema(type="STRING", description="Project name"),
                "target": types.Schema(type="STRING", description="Target environment (e.g. production)"),
                "confirm": types.Schema(
                    type="BOOLEAN",
                    description="Set to true ONLY if the user verbally confirmed proceeding with deployment."
                ),
            },
            required=["project", "target"]
        )
    ),
    types.FunctionDeclaration(
        name="hermes_restart_service",
        description="Restart a system systemd service on the VPS (requires verbal confirmation).",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "service": types.Schema(type="STRING", description="Service name (e.g., nginx, addy)"),
                "confirm": types.Schema(
                    type="BOOLEAN",
                    description="Set to true ONLY if the user verbally confirmed proceeding with restart."
                ),
            },
            required=["service"]
        )
    ),
    types.FunctionDeclaration(
        name="hermes_git_update",
        description="Git pull updates and resolve conflicts for a code repository (requires verbal confirmation).",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "project": types.Schema(type="STRING", description="Project repo name"),
                "confirm": types.Schema(
                    type="BOOLEAN",
                    description="Set to true ONLY if the user verbally confirmed proceeding with git pull."
                ),
            },
            required=["project"]
        )
    ),
    types.FunctionDeclaration(
        name="read_calendar_availability",
        description="Read Adarsh's calendar availability timeline for scheduling.",
        parameters=types.Schema(type="OBJECT", properties={})
    ),
    types.FunctionDeclaration(
        name="send_admin_email",
        description="Send an administrative email to a target recipient.",
        parameters=types.Schema(
            type="OBJECT",
            properties={
                "to": types.Schema(type="STRING", description="Recipient email address"),
                "subject": types.Schema(type="STRING", description="Email subject"),
                "body": types.Schema(type="STRING", description="Body text content of email")
            },
            required=["to", "subject", "body"]
        )
    )
]

# Handler map matching function names to python functions
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


def get_live_tools(mode: AccessMode) -> list[types.Tool]:
    """Retrieve Tool list containing appropriate function declarations for AccessMode."""
    declarations = _ADMIN_DECLARATIONS if mode == AccessMode.ADMIN else _PUBLIC_DECLARATIONS
    return [types.Tool(function_declarations=declarations)]


async def execute_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute tool handler by function name."""
    handler = _HANDLER_MAP.get(name)
    if not handler:
        return {"success": False, "error": f"Tool '{name}' not registered."}
    try:
        return await handler(**arguments)
    except Exception as exc:
        log.error("Tool execution failed", name=name, error=str(exc))
        return {"success": False, "error": str(exc)}
