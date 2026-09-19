"""Provider contracts. Live and fixture implementations return the same normalized models."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from campuspulse.core.models import IndoorGuidance, LatLng, Mode, RouteResult, Signal, SourceMode


class ProviderError(Exception):
    """codes: unavailable | unauthorized | rate_limited | invalid_response | stale | not_implemented"""

    def __init__(self, code: str, message: str = "") -> None:
        self.code = code
        super().__init__(message or code)


class RoutingProvider(Protocol):
    name: str
    source_mode: SourceMode

    def route(self, origin: LatLng, destination: LatLng, mode: Mode, depart_at: datetime) -> RouteResult: ...


class SignalProvider(Protocol):
    kind: str
    source_mode: SourceMode

    def fetch(self, at: datetime, context: dict[str, Any]) -> Signal: ...


class IndoorProvider(Protocol):
    source_mode: SourceMode

    def locate(self, building_id: str, room: str) -> IndoorGuidance: ...


class EmailProvider(Protocol):
    def preview(self, to: list[str], subject: str, body: str) -> dict[str, Any]: ...

    def send(self, preview: dict[str, Any]) -> dict[str, Any]: ...


class CalendarProvider(Protocol):
    def preview_change(self, change: dict[str, Any]) -> dict[str, Any]: ...

    def execute_change(self, preview: dict[str, Any]) -> dict[str, Any]: ...
