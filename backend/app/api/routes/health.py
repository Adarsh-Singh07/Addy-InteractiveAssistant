"""
Health and diagnostics endpoints.

GET /api/health      — simple liveness probe (no auth required)
GET /api/metrics     — latency metrics (auth required)
GET /api/diagnostics — detailed system info (auth required)
"""

from __future__ import annotations

import platform
import time

import psutil
from fastapi import APIRouter, Depends

from app.observability.metrics import get_metrics
from app.config.settings import get_settings

router = APIRouter(prefix="/api", tags=["health"])
_start_time = time.time()
settings = get_settings()


@router.get("/health")
async def health():
    """Liveness probe — no auth required. Used by Docker health checks."""
    return {
        "status": "ok",
        "agent": settings.agent_name,
        "uptime_s": round(time.time() - _start_time, 1),
    }


@router.get("/metrics")
async def metrics_endpoint():
    """Latency metrics and session stats."""
    return get_metrics().summary()


@router.get("/diagnostics")
async def diagnostics():
    """Detailed system + provider diagnostics."""
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        sys_info = {
            "cpu_percent": cpu,
            "ram_used_mb": round(mem.used / 1024 / 1024),
            "ram_total_mb": round(mem.total / 1024 / 1024),
            "ram_percent": mem.percent,
            "disk_used_gb": round(disk.used / 1024 / 1024 / 1024, 1),
            "disk_total_gb": round(disk.total / 1024 / 1024 / 1024, 1),
            "platform": platform.system(),
        }
    except Exception:
        sys_info = {"error": "psutil not available"}

    return {
        "agent": settings.agent_name,
        "user": settings.user_name,
        "uptime_s": round(time.time() - _start_time, 1),
        "providers": {
            "llm": settings.llm_provider,
            "llm_fallback": settings.llm_fallback_provider,
            "stt": "deepgram",
            "tts": "deepgram",
            "hermes_mock": settings.hermes_mock,
        },
        "system": sys_info,
        "metrics": get_metrics().summary(),
    }
