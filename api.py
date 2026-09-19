"""Local CampusPulse API configuration.

Keep secrets in environment variables or a local secret manager.  This module
only exposes configuration values to the application and contains no keys.
Stage 1 can run with ``PROVIDER_MODE=fixture`` and no external credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _bool_env(name: str, default: bool) -> bool:
    value = _env(name, str(default)).lower()
    return value not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class Settings:
    # Runtime
    app_env: str = _env("APP_ENV", "development")
    timezone: str = _env("TIMEZONE", "Asia/Taipei")
    provider_mode: str = _env("PROVIDER_MODE", "fixture")
    dry_run: bool = _bool_env("DRY_RUN", True)

    # AI
    openai_api_key: str = _env("OPENAI_API_KEY")
    openai_vision_model: str = _env("OPENAI_VISION_MODEL")
    openai_reasoning_model: str = _env("OPENAI_REASONING_MODEL")

    # Taiwan live data providers
    cwa_api_key: str = _env("CWA_API_KEY")
    ptx_app_id: str = _env("PTX_APP_ID")
    ptx_app_key: str = _env("PTX_APP_KEY")
    youbike_feed_url: str = _env("YOUBIKE_FEED_URL")
    aqi_api_key: str = _env("AQI_API_KEY")
    aqi_api_url: str = _env("AQI_API_URL")
    flood_api_key: str = _env("FLOOD_API_KEY")
    flood_api_url: str = _env("FLOOD_API_URL")

    # Route-time providers
    google_maps_api_key: str = _env("GOOGLE_MAPS_API_KEY")
    mapbox_access_token: str = _env("MAPBOX_ACCESS_TOKEN")

    # Google Gmail / Calendar OAuth
    google_client_id: str = _env("GOOGLE_CLIENT_ID")
    google_client_secret: str = _env("GOOGLE_CLIENT_SECRET")
    google_redirect_uri: str = _env("GOOGLE_REDIRECT_URI")
    google_refresh_token: str = _env("GOOGLE_REFRESH_TOKEN")

    # Application secret
    session_secret: str = _env("SESSION_SECRET")


settings = Settings()


def missing_live_credentials() -> list[str]:
    """Return missing credentials without exposing any secret values."""

    required = {
        "GEMINI_API_KEY": settings.openai_api_key,
        "CWA_API_KEY": settings.cwa_api_key,
        "PTX_APP_ID": settings.ptx_app_id,
        "PTX_APP_KEY": settings.ptx_app_key,
    }
    return [name for name, value in required.items() if not value]

