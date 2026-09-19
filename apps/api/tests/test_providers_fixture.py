from datetime import datetime, timedelta, timezone

from campuspulse.core.campus import Campus
from campuspulse.core.models import LatLng, Mode, SourceMode
from campuspulse.providers.base import ProviderError
from campuspulse.providers.fixture_store import FixtureStore
from campuspulse.providers.registry import build_providers
from campuspulse.settings import Settings

TPE = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 7, 50, tzinfo=TPE)


def _providers():
    store = FixtureStore()
    return build_providers(Settings(provider_mode="fixture"), store, Campus.load()), store


def test_fixture_routing_returns_all_four_modes_with_alternatives():
    providers, _ = _providers()
    origin, dest = LatLng(lat=22.9905, lng=120.2280), LatLng(lat=22.9997, lng=120.2220)
    for mode in Mode:
        r = providers.routing.route(origin, dest, mode, NOW)
        assert r.mode == mode and r.source_mode == SourceMode.fixture and r.polyline
    assert providers.routing.route(origin, dest, Mode.scooter, NOW).alternative.corridor_ids == ["changrong-rd"]


def test_fixture_signal_reads_store_and_marks_fixture():
    providers, store = _providers()
    store.set_all({"rain": {"mm_per_hour": 25, "forecast_next_hour_mm": 30}}, NOW)
    sig = providers.signals["rain"].fetch(NOW, {})
    assert sig.value["mm_per_hour"] == 25 and sig.source_mode == SourceMode.fixture and sig.observed_at == NOW


def test_fixture_signal_missing_raises_unavailable():
    providers, _ = _providers()
    try:
        providers.signals["flood"].fetch(NOW, {})
    except ProviderError as e:
        assert e.code == "unavailable"
    else:
        raise AssertionError("expected ProviderError")


def test_fixture_indoor_and_email_are_dry_run():
    providers, _ = _providers()
    g = providers.indoor.locate("csie", "4263")
    assert g.floor == "4F" and g.source_mode == SourceMode.fixture
    preview = providers.email.preview(["ta@example.com"], "遲到通知", "內文")
    assert providers.email.send(preview)["status"] == "dry_run"
