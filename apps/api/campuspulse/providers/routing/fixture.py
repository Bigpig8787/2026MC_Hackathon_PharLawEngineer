"""Canned routes for the canonical NCKU scenario. Ignores origin/destination on purpose."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from campuspulse.core.models import LatLng, Mode, RouteResult, SourceMode
from campuspulse.providers.base import ProviderError
from campuspulse.settings import API_ROOT

ROUTES_DIR = API_ROOT / "fixtures" / "routes"


def _to_route(raw: dict) -> RouteResult:
    alt = raw.get("alternative")
    return RouteResult(
        mode=Mode(raw["mode"]),
        duration_min=raw["duration_min"],
        distance_m=raw["distance_m"],
        polyline=[LatLng(lat=p[0], lng=p[1]) for p in raw.get("polyline", [])],
        summary=raw.get("summary", ""),
        corridor_ids=raw.get("corridor_ids", []),
        source_mode=SourceMode.fixture,
        mode_proxy=raw.get("mode_proxy"),
        alternative=_to_route(alt) if alt else None,
    )


class FixtureRoutingProvider:
    name = "fixture-routes"
    source_mode = SourceMode.fixture

    def __init__(self, routes_dir: Path = ROUTES_DIR) -> None:
        self.routes_dir = routes_dir

    def route(self, origin: LatLng, destination: LatLng, mode: Mode, depart_at: datetime) -> RouteResult:
        path = self.routes_dir / f"{mode.value}.json"
        if not path.exists():
            raise ProviderError("unavailable", f"no fixture route for {mode.value}")
        with path.open(encoding="utf-8") as f:
            return _to_route(json.load(f))
