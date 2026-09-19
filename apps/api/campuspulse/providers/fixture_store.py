"""Scenario-owned signal values. The runner writes, fixture providers read."""
from __future__ import annotations

from datetime import datetime
from typing import Any


class FixtureStore:
    def __init__(self) -> None:
        self.values: dict[str, dict[str, Any]] = {}
        self.observed_at: datetime | None = None

    def set_all(self, values: dict[str, dict[str, Any]], observed_at: datetime) -> None:
        self.values = {k: dict(v) for k, v in values.items()}
        self.observed_at = observed_at

    def update(self, kind: str, patch: dict[str, Any]) -> None:
        self.values.setdefault(kind, {}).update(patch)

    def get(self, kind: str) -> dict[str, Any] | None:
        return self.values.get(kind)
