"""模擬情境：讓 Demo 可以重現「環境突然改變」，而且每一筆都明確標示是模擬。

真實資料不會在 Demo 現場剛好下大雨、或剛好把 YouBike 借光，但「環境改變後自己重新
規畫」正是這個作品要展示的能力。這裡在 Tool 的回傳值上蓋一層覆寫：只有被指定的那一項
被換掉並加上 simulated=True，座標、站名、時間等其餘欄位仍是真的。

啟用範圍是「一次請求」：用 ContextVar 綁在當下的執行脈絡，請求結束就還原。
不用全域變數是因為 Cloud Run 可能同時有多個實例與使用者，全域狀態會互相干擾；
情境由前端每次請求帶上來，後端保持無狀態。

覆寫只發生在 Tool 的回傳，決策邏輯完全不知道有模擬這回事，走的是跟真實資料
相同的路——所以 Demo 展示的就是真正的決策流程，不是另一套假流程。
"""

from __future__ import annotations

import functools
from contextlib import contextmanager
from contextvars import ContextVar

SCENARIOS = {
    "heavy_rain": "豪雨：降雨機率 90%，雨量站正在下大雨",
    "bike_zero": "YouBike 歸零：附近借不到車、也還不了車",
    "parking_full": "停車場全滿：全校機車與汽車停車場都沒有車位",
    "bus_down": "公車停駛：附近站牌沒有任何班次",
}

_active: ContextVar[frozenset] = ContextVar("commute_scenarios", default=frozenset())


def parse_names(raw: str | None) -> list[str]:
    """把 "heavy_rain,bike_zero" 這種字串轉成清單，只留認得的名稱，順序與去重照舊。"""
    names: list[str] = []
    for part in (raw or "").split(","):
        name = part.strip()
        if name in SCENARIOS and name not in names:
            names.append(name)
    return names


def active() -> frozenset:
    """目前這次請求啟用的情境名稱。"""
    return _active.get()


@contextmanager
def use(names):
    """在這個區塊內啟用指定的模擬情境，離開時（含發生例外）一定還原。"""
    token = _active.set(frozenset(n for n in names if n in SCENARIOS))
    try:
        yield
    finally:
        _active.reset(token)


# ---- 各種資料的覆寫 ----

def _weather(result: dict) -> dict:
    # 不管真的查到沒有都覆寫：天氣本來就是「資料」，不是「能不能用」的問題
    kept = {k: v for k, v in result.items() if k != "error_message"}
    return {**kept, "status": "ok", "weather": "豪雨", "rain_probability": 90,
            "will_rain": True, "simulated": True}


def _rain_now(result: dict) -> dict:
    station = result.get("station") or {"name": "（模擬）", "distance_km": None,
                                        "obs_time": ""}
    return {**{k: v for k, v in result.items() if k != "error_message"},
            "status": "ok", "station": station, "now_mm": 6.0, "past10min_mm": 4.0,
            "past1hr_mm": 12.0, "is_raining": True, "level": "heavy", "simulated": True}


def _bikes(result: dict) -> dict:
    need = result.get("need", "bike")
    return {"status": "not_found", "place_name": result.get("place_name", ""),
            "need": need, "stations": [], "fetched_at": result.get("fetched_at", ""),
            "note": "（模擬）YouBike 歸零：附近" + ("借不到車" if need == "bike" else "還不了車"),
            "simulated": True}


def _parking(result: dict) -> dict:
    lots = [{**lot, "available": 0} for lot in result.get("lots", [])]
    kept = {k: v for k, v in result.items() if k != "error_message"}
    return {**kept, "status": "ok", "lots": lots, "simulated": True}


def _bus(result: dict) -> dict:
    return {**{k: v for k, v in result.items() if k != "error_message"},
            "status": "not_found", "stops": result.get("stops", []), "arrivals": [],
            "note": "（模擬）公車停駛：附近站牌沒有任何班次", "simulated": True}


# 哪一種資料、被哪個情境覆寫
_OVERLAYS = {
    "weather": (("heavy_rain", _weather),),
    "rain_now": (("heavy_rain", _rain_now),),
    "bikes": (("bike_zero", _bikes),),
    "parking": (("parking_full", _parking),),
    "bus": (("bus_down", _bus),),
}


def simulated(kind: str):
    """裝飾 Tool：情境沒啟用時原封不動，啟用時在回傳值上蓋覆寫。

    用 functools.wraps 保留原函式的名稱、說明與參數簽名——ADK 是靠這些
    自動產生工具說明的，包了之後不能讓它認不得。
    """
    overlays = _OVERLAYS[kind]

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            result = fn(*args, **kwargs)
            on = _active.get()
            for name, overlay in overlays:
                if name in on:
                    result = overlay(result)
            return result

        return wrapper

    return decorator
