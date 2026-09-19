from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from campuspulse.settings import Settings, load_settings, missing_live_credentials


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="CampusPulse API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "provider_mode": settings.provider_mode,
            "dry_run": settings.dry_run,
            "missing_credentials": missing_live_credentials(settings),
        }

    return app


app = create_app()
