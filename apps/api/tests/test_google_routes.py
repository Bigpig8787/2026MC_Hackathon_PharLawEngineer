import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from campuspulse.core.campus import Campus
from campuspulse.core.models import LatLng, Mode, SourceMode
from campuspulse.providers.base import ProviderError
from campuspulse.providers.routing.google_routes import GoogleRoutesProvider
from campuspulse.providers.routing.polyline import decode_polyline
from campuspulse.settings import Settings

TPE = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 7, 50, tzinfo=TPE)
O, D = LatLng(lat=22.9905, lng=120.2280), LatLng(lat=22.9997, lng=120.2220)

RESPONSE = {
    "routes": [
        {"duration": "720s", "distanceMeters": 3200, "description": "小東路",
         "polyline": {"encodedPolyline": "_p~iF~ps|U_ulLnnqC_mqNvxq`@"},
         "legs": [{"steps": [{"navigationInstruction": {"instructions": "Turn left onto 小東路"}}]}]},
        {"duration": "900s", "distanceMeters": 3900, "description": "長榮路",
         "polyline": {"encodedPolyline": "_p~iF~ps|U_ulLnnqC_mqNvxq`@"},
         "legs": [{"steps": [{"navigationInstruction": {"instructions": "Head north on Changrong Rd"}}]}]},
    ]
}


def _provider(handler):
    settings = Settings(provider_mode="auto", google_maps_api_key="test-key")
    return GoogleRoutesProvider(settings, Campus.load(), client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_decode_polyline_matches_google_example():
    pts = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")
    assert [(round(p.lat, 5), round(p.lng, 5)) for p in pts] == [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]


def test_scooter_uses_drive_proxy_and_maps_corridors():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(req.content)
        seen["mask"] = req.headers.get("X-Goog-FieldMask")
        assert "test-key" == req.headers.get("X-Goog-Api-Key")
        return httpx.Response(200, json=RESPONSE)

    r = _provider(handler).route(O, D, Mode.scooter, NOW)
    assert seen["body"]["travelMode"] == "DRIVE" and seen["body"]["routeModifiers"]["avoidHighways"] is True
    assert "routes.duration" in seen["mask"]
    assert r.source_mode == SourceMode.live and r.mode_proxy == "DRIVE"
    assert r.duration_min == 12 and r.distance_m == 3200 and r.corridor_ids == ["xiaodong-rd"]
    assert r.alternative is not None and r.alternative.corridor_ids == ["changrong-rd"]
    assert len(r.polyline) == 3


def test_transit_has_no_alternative_flag_and_no_route_modifiers():
    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        assert body["travelMode"] == "TRANSIT" and "routeModifiers" not in body and body.get("computeAlternativeRoutes") is False
        return httpx.Response(200, json=RESPONSE)

    r = _provider(handler).route(O, D, Mode.transit, NOW)
    assert r.mode == Mode.transit and r.mode_proxy is None


@pytest.mark.parametrize("status,code", [(403, "unauthorized"), (401, "unauthorized"), (429, "rate_limited"), (500, "invalid_response")])
def test_http_errors_map_to_provider_errors(status, code):
    p = _provider(lambda req: httpx.Response(status, json={"error": {"message": "x"}}))
    with pytest.raises(ProviderError) as e:
        p.route(O, D, Mode.walk, NOW)
    assert e.value.code == code


def test_empty_routes_is_unavailable():
    p = _provider(lambda req: httpx.Response(200, json={}))
    with pytest.raises(ProviderError) as e:
        p.route(O, D, Mode.bike, NOW)
    assert e.value.code == "unavailable"
