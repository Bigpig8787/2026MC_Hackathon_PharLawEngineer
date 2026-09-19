"""Google Routes API (computeRoutes). Scooter uses DRIVE as a proxy; TWO_WHEELER is not offered in Taiwan."""
from __future__ import annotations

from datetime import datetime, timezone

import httpx

from campuspulse.core.campus import Campus
from campuspulse.core.models import LatLng, Mode, RouteResult, SourceMode
from campuspulse.providers.base import ProviderError
from campuspulse.providers.routing.polyline import decode_polyline
from campuspulse.settings import Settings

URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
FIELD_MASK = ",".join([
    "routes.duration",
    "routes.distanceMeters",
    "routes.polyline.encodedPolyline",
    "routes.description",
    "routes.legs.steps.navigationInstruction.instructions",
])
MODE_MAP = {Mode.walk: "WALK", Mode.bike: "BICYCLE", Mode.scooter: "DRIVE", Mode.transit: "TRANSIT"}


class GoogleRoutesProvider:
    IMPLEMENTED = True
    name = "google-routes"
    source_mode = SourceMode.live

    def __init__(self, settings: Settings, campus: Campus, client: httpx.Client | None = None, timeout: float = 8.0) -> None:
        self._key = settings.google_maps_api_key
        self.campus = campus
        self.client = client or httpx.Client(timeout=timeout)

    def _body(self, origin: LatLng, destination: LatLng, mode: Mode, depart_at: datetime) -> dict:
        body: dict = {
            "origin": {"location": {"latLng": {"latitude": origin.lat, "longitude": origin.lng}}},
            "destination": {"location": {"latLng": {"latitude": destination.lat, "longitude": destination.lng}}},
            "travelMode": MODE_MAP[mode],
            "computeAlternativeRoutes": mode != Mode.transit,
            "languageCode": "zh-TW",
            "units": "METRIC",
        }
        if mode == Mode.scooter:
            body["routeModifiers"] = {"avoidHighways": True, "avoidTolls": True}
        if mode == Mode.transit and depart_at > datetime.now(timezone.utc):
            body["departureTime"] = depart_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return body

    def _parse(self, raw: dict, mode: Mode) -> RouteResult:
        seconds = float(str(raw.get("duration", "0s")).rstrip("s") or 0)
        text = " ".join(
            step.get("navigationInstruction", {}).get("instructions", "")
            for leg in raw.get("legs", []) for step in leg.get("steps", [])
        )
        return RouteResult(
            mode=mode,
            duration_min=round(seconds / 60, 1),
            distance_m=float(raw.get("distanceMeters", 0)),
            polyline=decode_polyline(raw.get("polyline", {}).get("encodedPolyline", "")),
            summary=raw.get("description", ""),
            corridor_ids=self.campus.corridor_ids_in_text(text + " " + raw.get("description", "")),
            source_mode=SourceMode.live,
            mode_proxy="DRIVE" if mode == Mode.scooter else None,
        )

    def route(self, origin: LatLng, destination: LatLng, mode: Mode, depart_at: datetime) -> RouteResult:
        headers = {"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": FIELD_MASK, "Content-Type": "application/json"}
        try:
            resp = self.client.post(URL, json=self._body(origin, destination, mode, depart_at), headers=headers)
        except httpx.HTTPError as e:
            raise ProviderError("unavailable", f"routes api: {type(e).__name__}") from e
        if resp.status_code in (401, 403):
            raise ProviderError("unauthorized", "routes api rejected the key")
        if resp.status_code == 429:
            raise ProviderError("rate_limited", "routes api rate limited")
        if resp.status_code != 200:
            raise ProviderError("invalid_response", f"routes api status {resp.status_code}")
        routes = (resp.json() or {}).get("routes") or []
        if not routes:
            raise ProviderError("unavailable", f"no {MODE_MAP[mode]} route returned")
        primary = self._parse(routes[0], mode)
        if len(routes) > 1:
            primary.alternative = self._parse(routes[1], mode)
        return primary
