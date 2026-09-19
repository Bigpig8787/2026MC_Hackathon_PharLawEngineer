"""TODO(live, owner B): TDX 台南公車預估到站（/v2/Bus/EstimatedTimeOfArrival/City/Tainan/{RouteName}）。
以 data/ncku/bus_stops.json 的站名對應 StopUID；EstimateTime 秒 → next_eta_min。
回傳 Signal(kind="transit", value={"route_name", "next_eta_min", "board_stop_id", "alight_stop_id"}, source_mode=live)。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from campuspulse.core.campus import Campus
from campuspulse.core.models import Signal, SourceMode
from campuspulse.providers.base import ProviderError
from campuspulse.settings import Settings


class TdxBusProvider:
    IMPLEMENTED = False
    kind = "transit"
    source_mode = SourceMode.live

    def __init__(self, settings: Settings, campus: Campus) -> None:
        self._client_id = settings.tdx_client_id
        self._client_secret = settings.tdx_client_secret
        self.campus = campus

    def fetch(self, at: datetime, context: dict[str, Any]) -> Signal:
        raise ProviderError("not_implemented", "TODO(live, owner B): TDX bus ETA adapter")
