"""Thin Gemini wrapper. Returns None on any failure so callers always have a deterministic fallback."""
from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel

from campuspulse.settings import Settings

T = TypeVar("T", bound=BaseModel)


class GeminiClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client: Any = None

    @property
    def available(self) -> bool:
        return bool(self.settings.gemini_api_key)

    def _get(self) -> Any:
        if self._client is None:
            from google import genai

            self._client = genai.Client(api_key=self.settings.gemini_api_key)
        return self._client

    def generate_text(self, prompt: str, model: str | None = None, parts: list[Any] | None = None) -> str | None:
        if not self.available:
            return None
        try:
            resp = self._get().models.generate_content(
                model=model or self.settings.gemini_flash_model, contents=[*(parts or []), prompt],
            )
            text = (getattr(resp, "text", None) or "").strip()
            return text or None
        except Exception:
            return None

    def generate_json(self, prompt: str, schema: type[T], model: str | None = None, parts: list[Any] | None = None) -> T | None:
        if not self.available:
            return None
        try:
            from google.genai import types

            resp = self._get().models.generate_content(
                model=model or self.settings.gemini_flash_model,
                contents=[*(parts or []), prompt],
                config=types.GenerateContentConfig(response_mime_type="application/json", response_schema=schema),
            )
            return schema.model_validate_json(resp.text or "")
        except Exception:
            return None
