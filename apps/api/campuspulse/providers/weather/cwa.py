"""TODO(live, owner B): 中央氣象署開放資料。
建議來源：O-A0001-001（自動氣象站即時雨量）取最近測站的 HOUR_RAIN；F-C0032-001 或鄉鎮預報取下一小時降雨。
回傳 Signal(kind="rain", value={"mm_per_hour": float, "forecast_next_hour_mm": float}, source_mode=live, observed_at=資料時間)。
逾時 8 秒；資料時間超過 30 分鐘標 stale；失敗拋 ProviderError。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from campuspulse.core.campus import Campus
from campuspulse.core.models import Signal, SourceMode
from campuspulse.providers.base import ProviderError
from campuspulse.settings import Settings


class CwaWeatherProvider:
    IMPLEMENTED = False
    kind = "rain"
    source_mode = SourceMode.live

    def __init__(self, settings: Settings, campus: Campus) -> None:
        self._key = settings.cwa_api_key
        self.campus = campus

    def fetch(self, at: datetime, context: dict[str, Any]) -> Signal:
        raise ProviderError("not_implemented", "TODO(live, owner B): CWA rain adapter")
