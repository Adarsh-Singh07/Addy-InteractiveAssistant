"""
Authentication endpoints.
Handles admin passcode verification and sets secure HTTP-only cookies.
"""

from __future__ import annotations

import hmac
import hashlib
import base64
from fastapi import APIRouter, Response, Request, HTTPException
from pydantic import BaseModel
from app.config.settings import get_settings
from app.observability.logging import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])
settings = get_settings()

COOKIE_NAME = "session_token"


class LoginRequest(BaseModel):
    passcode: str


def _sign_payload(payload: str) -> str:
    """Generate secure HMAC signature for the session payload."""
    secret = settings.app_secret_key.get_secret_value().encode("utf-8")
    sig = hmac.new(secret, payload.encode("utf-8"), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).decode("utf-8").rstrip("=")
    return f"{payload}.{sig_b64}"


def verify_token(token: str | None) -> bool:
    """Verify if the token is a valid signed admin session token."""
    if not token:
        return False
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return False
        payload, signature = parts
        if payload != "admin":
            return False
        expected = _sign_payload(payload)
        return hmac.compare_digest(token, expected)
    except Exception as exc:
        log.warning("Token verification failed", error=str(exc))
        return False


@router.post("/login")
async def login(request: LoginRequest, response: Response):
    """Verify passcode and set an HTTP-only secure cookie."""
    entered = request.passcode
    expected = settings.admin_password.get_secret_value()

    if entered != expected:
        log.warning("Failed admin login attempt")
        raise HTTPException(status_code=401, detail="Invalid passcode")

    token = _sign_payload("admin")
    # Set secure cookie
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.app_env == "production",
        samesite="lax",
        max_age=3600 * 24,  # 24 hours
    )
    log.info("Admin logged in successfully")
    return {"success": True, "access_mode": "ADMIN"}


@router.post("/logout")
async def logout(response: Response):
    """Clear the session token cookie."""
    response.delete_cookie(key=COOKIE_NAME)
    log.info("Admin logged out")
    return {"success": True}


@router.get("/status")
async def status(request: Request):
    """Check active access mode."""
    token = request.cookies.get(COOKIE_NAME)
    if verify_token(token):
        return {"access_mode": "ADMIN"}
    return {"access_mode": "PUBLIC"}

@router.get("/diag")
async def diag():
    """Run diagnostics on VPS."""
    import subprocess
    diagnostics = {}
    commands = {
        "portfolio_env": "cat /home/ubuntu/portfolio/backend/.env | grep 'LARK' | sed 's/=.*/=SET/' || true",
        "portfolio_status": "systemctl status portfolio.service --no-pager -l || true",
        "portfolio_cat": "cat /etc/systemd/system/portfolio.service || true",
        "portfolio_git": "cd /home/ubuntu/portfolio && git log -1 --oneline || true",
        "portfolio_git_status": "cd /home/ubuntu/portfolio && git status || true",
        "portfolio_pwd": "cd /home/ubuntu/portfolio/backend && pwd || true",
        "nginx_portfolio": "cat /etc/nginx/sites-enabled/api.adarshsingh.in.conf || true",
        "nginx_access": "tail -n 50 /var/log/nginx/access.log | grep -i 'webhook' || true"
    }
    for key, cmd in commands.items():
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            diagnostics[key] = result.stdout + result.stderr
        except Exception as e:
            diagnostics[key] = str(e)
    return {"status": "ok", "diagnostics": diagnostics}
