from campuspulse.core.campus import Campus
from campuspulse.providers.fixture_store import FixtureStore
from campuspulse.providers.registry import build_providers
from campuspulse.providers.routing.fixture import FixtureRoutingProvider
from campuspulse.providers.routing.google_routes import GoogleRoutesProvider
from campuspulse.settings import Settings


def test_auto_mode_with_key_uses_google_routes():
    p = build_providers(Settings(provider_mode="auto", google_maps_api_key="k"), FixtureStore(), Campus.load())
    assert isinstance(p.routing, GoogleRoutesProvider)
    assert all(v == "fixture" for k, v in p.modes().items() if k != "routing")


def test_auto_mode_without_key_falls_back_to_fixture():
    p = build_providers(Settings(provider_mode="auto"), FixtureStore(), Campus.load())
    assert isinstance(p.routing, FixtureRoutingProvider)


def test_fixture_mode_ignores_keys():
    p = build_providers(Settings(provider_mode="fixture", google_maps_api_key="k"), FixtureStore(), Campus.load())
    assert isinstance(p.routing, FixtureRoutingProvider)


def test_signal_shells_stay_fixture_until_implemented():
    s = Settings(provider_mode="auto", google_maps_api_key="k", cwa_api_key="k", wra_api_key="k", tdx_client_id="k", tdx_client_secret="k")
    p = build_providers(s, FixtureStore(), Campus.load())
    assert all(v == "fixture" for k, v in p.modes().items() if k in ("rain", "flood", "bike", "transit", "parking"))


def test_implemented_shell_is_selected(monkeypatch):
    from campuspulse.providers.weather.cwa import CwaWeatherProvider

    monkeypatch.setattr(CwaWeatherProvider, "IMPLEMENTED", True)
    p = build_providers(Settings(provider_mode="auto", cwa_api_key="k"), FixtureStore(), Campus.load())
    assert isinstance(p.signals["rain"], CwaWeatherProvider) and p.modes()["rain"] == "live"