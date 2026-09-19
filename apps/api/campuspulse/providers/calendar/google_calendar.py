"""TODO(live, owner E): Google Calendar API。preview_change() 回將建立/更新的事件；execute_change() 需 idempotency key（用 commitment.id + 日期）。
"""
from __future__ import annotations

from typing import Any

from campuspulse.providers.base import ProviderError
from campuspulse.settings import Settings


class GoogleCalendarProvider:
    IMPLEMENTED = False

    def __init__(self, settings: Settings) -> None:
        self.dry_run = settings.dry_run

    def preview_change(self, change: dict[str, Any]) -> dict[str, Any]:
        return {"change": change, "provider": "google-calendar"}

    def execute_change(self, preview: dict[str, Any]) -> dict[str, Any]:
        if self.dry_run:
            return {"status": "dry_run", "change": preview.get("change")}
        raise ProviderError("not_implemented", "TODO(live, owner E): Calendar write")
