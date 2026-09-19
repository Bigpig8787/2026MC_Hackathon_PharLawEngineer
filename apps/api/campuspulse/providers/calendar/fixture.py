from __future__ import annotations

from typing import Any


class FixtureCalendarProvider:
    def preview_change(self, change: dict[str, Any]) -> dict[str, Any]:
        return {"change": change, "provider": "fixture"}

    def execute_change(self, preview: dict[str, Any]) -> dict[str, Any]:
        return {"status": "dry_run", "change": preview.get("change")}
