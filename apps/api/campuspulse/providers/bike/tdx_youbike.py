"""TODO(live, owner B): TDX YouBike 台南即時站點（/v2/Bike/Availability/City/Tainan + /v2/Bike/Station/City/Tainan）。
先用 client_credentials 換 token（快取到過期前 60 秒）。以 data/ncku/bike_stations.json 的站名對應 TDX StationUID。
回傳 Signal(kind="bike", value={"origin_station_id", "available", "dest_station_id", "docks", "next_station_id", "next_station_docks"}, source_mode=live)。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from campuspulse.core.campus import Campus
from campuspulse.core.models import Signal, SourceMode
from campuspulse.providers.base import ProviderError
from campuspulse.settings import Settings


class TdxYouBikeProvider:
    IMPLEMENTED = False
    kind = "bike"
    source_mode = SourceMode.live

    def __init__(self, settings: Settings, campus: Campus) -> None:
        self._client_id = settings.tdx_client_id
        self._client_secret = settings.tdx_client_secret
        self.campus = campus

    def fetch(self, at: datetime, context: dict[str, Any]) -> Signal:
        raise ProviderError("not_implemented", "TODO(live, owner B): TDX YouBike adapter")
