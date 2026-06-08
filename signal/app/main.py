"""FastAPI application factory for sauce.ai/signal.

    uvicorn app.main:app --reload      # dev
    create_app()                       # programmatic
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import health, jurisdictions, projects, signals
from .config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="sauce.ai/signal",
                  description="Permit intelligence & distressed-project triage",
                  version="0.1.0")

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware, allow_origins=origins or ["*"],
        allow_methods=["*"], allow_headers=["*"])

    app.include_router(health.router)
    app.include_router(projects.router)
    app.include_router(jurisdictions.router)
    app.include_router(signals.router)

    @app.get("/")
    def root():
        return {"service": "sauce.ai/signal", "version": app.version,
                "docs": "/docs"}

    return app


app = create_app()
