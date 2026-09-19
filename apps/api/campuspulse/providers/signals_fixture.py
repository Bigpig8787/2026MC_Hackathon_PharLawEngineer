from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from campuspulse.core.models import Signal, SourceMode
from campuspulse.providers.base import ProviderError
from campuspulse.providers.fixture_store import FixtureStore

VALID_FOR = timedelta(minutes=10)


class FixtureSignalProvider:
    kind: str = ""
    source_mode = SourceMode.fixture

    def __init__(self, store: FixtureStore, kind: str | None = None) -> None:
        self.store = store
        if kind:
            self.kind = kind

    def fetch(self, at: datetime, context: dict[str, Any]) -> Signal:
        value = self.store.get(self.kind)
        if value is None:
            raise ProviderError("unavailable", f"fixture has no {self.kind} value")
        observed = self.store.observed_at or at
        return Signal(kind=self.kind, observed_at=observed, valid_until=observed + VALID_FOR, value=value, source_mode=self.source_mode)
