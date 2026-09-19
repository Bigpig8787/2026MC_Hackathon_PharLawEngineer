"""Tool 層：中央氣象署臺南市鄉鎮天氣預報（需要免費的 CWA_API_KEY）。

用的是 F-D0047-077（臺南市未來 2 天、逐 3 小時），不是 F-D0047-089——
後者是全台縣市層級，查不到「東區」這種鄉鎮，成大所在的東區必須用市級資料集。

各個氣象要素的時間切分不一定一致，所以不做「第幾筆對第幾筆」的假設，
而是依查詢時刻去找涵蓋它的那個時段，缺值就回 None 而不是猜一個。
"""

from __future__ import annotations

import ssl
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter

from api import load_settings
from commute_agent.scenario import simulated

DATASET = "F-D0047-077"          # 臺南市 逐3小時預報
ENDPOINT = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"
USER_AGENT = "NCKU-Smart-Commute/0.1 (DevJam TW 2026 hackathon prototype)"

# 成大主要校區都在東區
DEFAULT_DISTRICT = "東區"

# 降雨機率達這個值就值得提醒帶傘或改搭有遮蔽的交通工具
RAIN_ALERT_THRESHOLD = 40


class SchemaError(ValueError):
    """CWA 回應格式與預期不符。"""


class _RelaxedStrictAdapter(HTTPAdapter):
    """只關閉 Python 3.13 新增的 VERIFY_X509_STRICT，其餘驗證照舊。

    憑證鏈與主機名稱仍然會驗證，放寬的只有「憑證必須帶 Subject Key Identifier」
    這類格式上的嚴格檢查，不是整個關掉 SSL 驗證。
    """

    def init_poolmanager(self, *args, **kwargs):
        context = ssl.create_default_context()
        context.verify_flags &= ~ssl.VERIFY_X509_STRICT
        kwargs["ssl_context"] = context
        return super().init_poolmanager(*args, **kwargs)


def _get_with_ssl_fallback(url: str, **kwargs) -> requests.Response:
    """先用一般連線；憑證驗證失敗時，才改用放寬嚴格檢查的連線重試一次。

    氣象署 opendata.cwa.gov.tw 的憑證缺少 Subject Key Identifier，Python 3.13
    （OpenSSL 3.5）預設的嚴格模式會以 CERTIFICATE_VERIFY_FAILED 拒絕，
    舊版 Python 則沒事。所以原本的連線方式維持第一選擇，真的被擋下才換；
    連線逾時等其他錯誤不重試，憑證真的有問題時重試也一樣會失敗並照實回報。
    """
    try:
        return requests.get(url, **kwargs)
    except requests.exceptions.SSLError:
        with requests.Session() as session:
            session.mount("https://", _RelaxedStrictAdapter())
            return session.get(url, **kwargs)


def _elements(location: dict) -> dict[str, dict]:
    return {w["ElementName"]: w for w in location.get("WeatherElement", [])}


def element_value_at(element: dict, when: datetime) -> dict | None:
    """找出涵蓋指定時刻的那一筆值。

    有些要素用 StartTime/EndTime 區間，有些只有單一 DataTime；
    後者取「最後一個不晚於 when」的那筆，也就是當下最新的觀測或預報。
    """
    latest = None
    for entry in element.get("Time", []):
        start = entry.get("StartTime") or entry.get("DataTime")
        if not start:
            continue
        start_dt = datetime.fromisoformat(start)
        end = entry.get("EndTime")
        if end:
            if start_dt <= when < datetime.fromisoformat(end):
                return entry["ElementValue"][0]
        elif start_dt <= when:
            latest = entry["ElementValue"][0]
    return latest


def parse_forecast(location: dict, when: datetime) -> dict:
    """把 CWA 的要素陣列整理成單一時刻的天氣摘要。"""
    elements = _elements(location)
    if not elements:
        raise SchemaError("回應缺少 WeatherElement")

    def value(name: str, key: str) -> str | None:
        entry = elements.get(name)
        if not entry:
            return None
        found = element_value_at(entry, when)
        return found.get(key) if found else None

    pop_raw = value("3小時降雨機率", "ProbabilityOfPrecipitation")
    try:
        pop = int(pop_raw) if pop_raw not in (None, "", "-") else None
    except ValueError:
        pop = None

    return {
        "weather": value("天氣現象", "Weather"),
        "rain_probability": pop,
        "temperature": value("溫度", "Temperature"),
        "apparent_temperature": value("體感溫度", "ApparentTemperature"),
        "description": value("天氣預報綜合描述", "WeatherDescription"),
        "will_rain": pop is not None and pop >= RAIN_ALERT_THRESHOLD,
    }


@simulated("weather")
def get_weather(district: str = DEFAULT_DISTRICT, when_iso: str = "") -> dict:
    """查成大所在地區的天氣預報，用來判斷要不要帶傘或改交通方式。

    適用時機：使用者問天氣、問要不要帶傘，或你要建議出發方式時；
    降雨機率高時騎機車與 YouBike 都會被淋濕，適合改建議公車。

    Args:
        district: 臺南市的鄉鎮區名稱，例如 "東區"（成大主校區所在地）、"北區"。
        when_iso: 要查的時刻（ISO 格式）。留空表示現在。
            想知道出發當下會不會下雨，就傳出發時刻。

    Returns:
        dict，包含：
        - status: "ok"、"not_found"（查無該行政區）或 "error"
        - weather: 天氣現象，例如 "晴"、"短暫陣雨"
        - rain_probability: 降雨機率（百分比整數），無資料時為 None
        - will_rain: 降雨機率是否達到需要提醒的門檻（40%）
        - temperature、apparent_temperature: 氣溫與體感溫度（攝氏）
        - description: 氣象署的綜合描述原文
        - valid_at: 這筆預報對應的時刻
    """
    settings = load_settings()
    tz = settings.timezone
    when = datetime.fromisoformat(when_iso) if when_iso else datetime.now(ZoneInfo(tz))

    result = {"status": "ok", "district": district,
              "valid_at": when.isoformat(timespec="seconds")}

    if not settings.cwa_api_key:
        return {**result, "status": "error", "error_message": "未設定 CWA_API_KEY"}

    try:
        resp = _get_with_ssl_fallback(
            f"{ENDPOINT}/{DATASET}",
            params={"Authorization": settings.cwa_api_key, "format": "JSON",
                    "LocationName": district},
            timeout=max(settings.http_timeout_seconds, 20),
            headers={"User-Agent": USER_AGENT})
    except requests.Timeout:
        return {**result, "status": "error", "error_message": "中央氣象署查詢逾時"}
    except requests.RequestException as exc:
        return {**result, "status": "error",
                "error_message": f"無法連線中央氣象署（{type(exc).__name__}）"}

    if resp.status_code != 200:
        return {**result, "status": "error",
                "error_message": f"中央氣象署回應 HTTP {resp.status_code}"}

    try:
        payload = resp.json()
        locations = payload["records"]["Locations"][0]["Location"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        return {**result, "status": "error", "error_message": f"回應格式異常：{exc}"}

    if not locations:
        return {**result, "status": "not_found",
                "error_message": f"臺南市沒有「{district}」這個行政區"}

    try:
        return {**result, **parse_forecast(locations[0], when)}
    except SchemaError as exc:
        return {**result, "status": "error", "error_message": f"回應格式異常：{exc}"}
