"""TODO(live, owner B): 水利署水資源物聯網（iot.wra.gov.tw）都市積淹水感測器。
把感測器座標對到 data/ncku/corridors.json 的走廊；水深 ≥ 10cm 為 warning、≥ 30cm 為 danger。
回傳 Signal(kind="flood", value={"alerts": [{"corridor_id", "level", "depth_cm"}]}, source_mode=live)。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from campuspulse.core.campus import Campus
from campuspulse.core.models import Signal, SourceMode
from campuspulse.providers.base import ProviderError
from campuspulse.settings import Settings


class WraFloodProvider:
    IMPLEMENTED = False
    kind = "flood"
    source_mode = SourceMode.live

    def __init__(self, settings: Settings, campus: Campus) -> None:
        self._key = settings.wra_api_key
        self.campus = campus

    def fetch(self, at: datetime, context: dict[str, Any]) -> Signal:
        raise ProviderError("not_implemented", "TODO(live, owner B): WRA flood adapter")
