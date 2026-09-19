"""Assemble providers. Live only when PROVIDER_MODE=auto, the key exists, and the class is implemented."""
from __future__ import annotations

from dataclasses import dataclass, field

from campuspulse.core.campus import Campus
from campuspulse.providers.base import CalendarProvider, EmailProvider, IndoorProvider, RoutingProvider, SignalProvider
from campuspulse.providers.bike.fixture import FixtureBikeProvider
from campuspulse.providers.calendar.fixture import FixtureCalendarProvider
from campuspulse.providers.email.fixture import FixtureEmailProvider
from campuspulse.providers.fixture_store import FixtureStore
from campuspulse.providers.flood.fixture import FixtureFloodProvider
from campuspulse.providers.indoor.fixture import FixtureIndoorProvider
from campuspulse.providers.parking.fixture import FixtureParkingProvider
from campuspulse.providers.routing.fixture import FixtureRoutingProvider
from campuspulse.providers.transit.fixture import FixtureTransitProvider
from campuspulse.providers.weather.fixture import FixtureWeatherProvider
from campuspulse.settings import Settings
from campuspulse.providers.routing.google_routes import GoogleRoutesProvider
from campuspulse.providers.bike.tdx_youbike import TdxYouBikeProvider
from campuspulse.providers.flood.wra import WraFloodProvider
from campuspulse.providers.transit.tdx_bus import TdxBusProvider
from campuspulse.providers.weather.cwa import CwaWeatherProvider

# kind -> (live class, settings attribute names that must be non-empty). Task 9/11 fill these.
LIVE_SIGNAL_CLASSES: dict[str, tuple[type, tuple[str, ...]]] = {
    "rain": (CwaWeatherProvider, ("cwa_api_key",)),
    "flood": (WraFloodProvider, ("wra_api_key",)),
    "bike": (TdxYouBikeProvider, ("tdx_client_id", "tdx_client_secret")),
    "transit": (TdxBusProvider, ("tdx_client_id", "tdx_client_secret")),
    # parking: 校方無即時資料前永遠 fixture（owner D 查總務處）
}
LIVE_ROUTING_CLASS: tuple[type, tuple[str, ...]] | None = (GoogleRoutesProvider, ("google_maps_api_key",))


@dataclass
class Providers:
    routing: RoutingProvider
    signals: dict[str, SignalProvider] = field(default_factory=dict)
    indoor: IndoorProvider | None = None
    email: EmailProvider | None = None
    calendar: CalendarProvider | None = None

    def modes(self) -> dict[str, str]:
        out = {"routing": self.routing.source_mode.value}
        out.update({k: p.source_mode.value for k, p in self.signals.items()})
        if self.indoor is not None:
            out["indoor"] = self.indoor.source_mode.value
        return out


def _wants_live(settings: Settings, keys: tuple[str, ...], cls: type) -> bool:
    return settings.provider_mode == "auto" and getattr(cls, "IMPLEMENTED", True) and all(getattr(settings, k) for k in keys)


def build_providers(settings: Settings, store: FixtureStore, campus: Campus) -> Providers:
    if LIVE_ROUTING_CLASS and _wants_live(settings, LIVE_ROUTING_CLASS[1], LIVE_ROUTING_CLASS[0]):
        routing = LIVE_ROUTING_CLASS[0](settings, campus)
    else:
        routing = FixtureRoutingProvider()

    fixture_signals = {
        "rain": FixtureWeatherProvider(store),
        "flood": FixtureFloodProvider(store),
        "bike": FixtureBikeProvider(store),
        "transit": FixtureTransitProvider(store),
        "parking": FixtureParkingProvider(store),
    }
    signals: dict[str, SignalProvider] = {}
    for kind, fixture in fixture_signals.items():
        live = LIVE_SIGNAL_CLASSES.get(kind)
        if live and _wants_live(settings, live[1], live[0]):
            signals[kind] = live[0](settings, campus)
        else:
            signals[kind] = fixture

    return Providers(
        routing=routing,
        signals=signals,
        indoor=FixtureIndoorProvider(campus),
        email=FixtureEmailProvider(),
        calendar=FixtureCalendarProvider(),
    )
