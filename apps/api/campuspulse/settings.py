"""Environment-backed settings. Never put secret values in code or logs."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

API_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(API_ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _bool_env(name: str, default: bool) -> bool:
    return _env(name, str(default)).lower() not in {"0", "false", "no", "off"}


@dataclass(frozen=True)
class Settings:
    provider_mode: str = "fixture"
    dry_run: bool = True
    timezone: str = "Asia/Taipei"
    gemini_api_key: str = ""
    gemini_flash_model: str = "gemini-3-flash-preview"
    gemini_pro_model: str = "gemini-3-pro-preview"
    google_maps_api_key: str = ""
    tdx_client_id: str = ""
    tdx_client_secret: str = ""
    cwa_api_key: str = ""
    wra_api_key: str = ""


def load_settings() -> Settings:
    return Settings(
        provider_mode=_env("PROVIDER_MODE", "fixture") or "fixture",
        dry_run=_bool_env("DRY_RUN", True),
        timezone=_env("TIMEZONE", "Asia/Taipei") or "Asia/Taipei",
        gemini_api_key=_env("GEMINI_API_KEY"),
        gemini_flash_model=_env("GEMINI_FLASH_MODEL", "gemini-3-flash-preview"),
        gemini_pro_model=_env("GEMINI_PRO_MODEL", "gemini-3-pro-preview"),
        google_maps_api_key=_env("GOOGLE_MAPS_API_KEY"),
        tdx_client_id=_env("TDX_CLIENT_ID"),
        tdx_client_secret=_env("TDX_CLIENT_SECRET"),
        cwa_api_key=_env("CWA_API_KEY"),
        wra_api_key=_env("WRA_API_KEY"),
    )


def missing_live_credentials(settings: Settings) -> list[str]:
    """Names only. Never return values."""
    required = {
        "GEMINI_API_KEY": settings.gemini_api_key,
        "GOOGLE_MAPS_API_KEY": settings.google_maps_api_key,
        "TDX_CLIENT_ID": settings.tdx_client_id,
        "TDX_CLIENT_SECRET": settings.tdx_client_secret,
        "CWA_API_KEY": settings.cwa_api_key,
        "WRA_API_KEY": settings.wra_api_key,
    }
    return [name for name, value in required.items() if not value]
