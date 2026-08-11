"""
FastAPI application factory.
# Triggering auto-deploy via GitHub Actions

Startup sequence:
1. Load settings from environment
2. Configure structured logging
3. Register routes
4. Start lifespan tasks

All providers are initialised lazily (in route handlers) to avoid
startup failures from missing API keys during testing.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes.health import router as health_router
from app.api.routes.voice import router as voice_router
from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.config.settings import get_settings
from app.observability.logging import get_logger, setup_logging

settings = get_settings()
setup_logging(level=settings.log_level, fmt=settings.log_format)
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info(
        "Addy starting",
        agent=settings.agent_name,
        user=settings.user_name,
        llm=settings.llm_provider,
        env=settings.app_env,
    )
    try:
        from app.db import init_db
        init_db()
        log.info("SQLite database initialized successfully")
    except Exception as exc:
        log.error("Failed to initialize SQLite database", error=str(exc))
    yield
    log.info("Addy shutting down")



def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.agent_name} Voice Agent",
        description="Personal AI voice assistant for Adarsh",
        version="1.0.0-phase1",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — allow frontend origin
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    app.include_router(health_router)
    app.include_router(voice_router)
    app.include_router(auth_router)
    app.include_router(chat_router)

    return app


app = create_app()

