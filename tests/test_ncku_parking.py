"""get_parking_availability Tool 測試。fixture 為真實錄製的停車頁 HTML 片段。"""
from pathlib import Path

import pytest
import requests

from commute_agent.tools import ncku_parking

FIXTURES = Path(__file__).resolve().parent.parent / "commute_agent" / "fixtures" / "ncku_parking"


def load(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, text="", status_code=200):
        self.text, self.status_code = text, status_code


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("PROVIDER_MODE", "live")


@pytest.fixture
def fixture_mode(monkeypatch):
    monkeypatch.setenv("PROVIDER_MODE", "fixture")


# ---------- 純解析 ----------

def test_parse_extracts_each_parking_lot():
    lots = ncku_parking.parse_parking_html(load("C_moto.html"))
    assert lots == [
        {"name": "奇美樓地下機車停車場", "campus": "自強校區", "available": 360},
        {"name": "林森路平面機車停車場", "campus": "自強校區", "available": 60},
    ]


def test_parse_no_data_message_returns_empty_list():
    # 勝利校區查機車的真實回應：查無符合條件之停車場資料
    assert ncku_parking.parse_parking_html(load("G_moto.html")) == []


def test_parse_unexpected_html_raises():
    with pytest.raises(ncku_parking.SchemaError):
        ncku_parking.parse_parking_html("<div>completely different markup</div>")


def test_parse_empty_string_raises():
    with pytest.raises(ncku_parking.SchemaError):
        ncku_parking.parse_parking_html("")


# ---------- 校區代碼 ----------

def test_all_seven_campuses_map_to_known_codes():
    # 使用者於 2026-09-19 逐一切換下拉選單並比對 Payload 中的 campus 值確認
    expected = {
        "光復": "A", "成功": "B", "自強": "C", "成杏": "D",
        "力行": "E", "敬業": "F", "勝利": "G",
    }
    assert ncku_parking.CAMPUS_CODES == expected


def test_unknown_campus_name_raises_valueerror(fixture_mode):
    with pytest.raises(ValueError):
        ncku_parking.get_parking_availability("火星校區", "機車")


@pytest.mark.parametrize("vehicle,expected_tab", [("機車", "moto"), ("汽車", "car")])
def test_vehicle_type_maps_to_tab_param(vehicle, expected_tab, live, monkeypatch):
    captured = {}

    def fake_post(url, data, timeout, headers):
        captured.update(url=url, data=data)
        return FakeResponse(load("C_moto.html"))

    monkeypatch.setattr(ncku_parking.requests, "post", fake_post)
    ncku_parking.get_parking_availability("自強", vehicle)
    assert captured["data"]["tab"] == expected_tab


def test_unknown_vehicle_type_raises_valueerror(fixture_mode):
    with pytest.raises(ValueError):
        ncku_parking.get_parking_availability("自強", "飛天車")


# ---------- live 模式 ----------

def test_live_posts_expected_endpoint_and_params(live, monkeypatch):
    captured = {}

    def fake_post(url, data, timeout, headers):
        captured.update(url=url, data=data, timeout=timeout)
        return FakeResponse(load("C_moto.html"))

    monkeypatch.setattr(ncku_parking.requests, "post", fake_post)
    result = ncku_parking.get_parking_availability("自強", "機車")

    assert captured["url"] == "https://apss.oga.ncku.edu.tw/park/index.php/park11215/read"
    assert captured["data"] == {"campus": "C", "tab": "moto"}
    assert captured["timeout"] > 0
    assert result["status"] == "ok"
    assert result["mode"] == "live"
    assert len(result["lots"]) == 2
    assert result["lots"][0]["available"] == 360
    assert "fetched_at" in result


def test_live_empty_result_is_ok_with_empty_lots(live, monkeypatch):
    # 「查無資料」是正常的業務情境（例如勝利校區沒有機車位），不是錯誤
    monkeypatch.setattr(ncku_parking.requests, "post", lambda *a, **k: FakeResponse(load("G_moto.html")))
    result = ncku_parking.get_parking_availability("勝利", "機車")
    assert result["status"] == "ok"
    assert result["lots"] == []


def test_live_timeout_returns_error_not_exception(live, monkeypatch):
    def boom(*a, **k):
        raise requests.Timeout("slow")
    monkeypatch.setattr(ncku_parking.requests, "post", boom)
    result = ncku_parking.get_parking_availability("自強", "機車")
    assert result["status"] == "error"
    assert "逾時" in result["error_message"]


def test_live_http_500_returns_error(live, monkeypatch):
    monkeypatch.setattr(ncku_parking.requests, "post", lambda *a, **k: FakeResponse(status_code=500))
    assert ncku_parking.get_parking_availability("自強", "機車")["status"] == "error"


def test_live_malformed_html_returns_error(live, monkeypatch):
    monkeypatch.setattr(ncku_parking.requests, "post", lambda *a, **k: FakeResponse("<div>???</div>"))
    result = ncku_parking.get_parking_availability("自強", "機車")
    assert result["status"] == "error"
    assert "格式" in result["error_message"]


# ---------- fixture 模式 ----------

def test_fixture_mode_reads_recorded_file_without_network(fixture_mode, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("fixture 模式不應打網路")
    monkeypatch.setattr(ncku_parking.requests, "post", no_network)
    result = ncku_parking.get_parking_availability("自強", "機車")
    assert result["status"] == "ok"
    assert result["mode"] == "fixture"
    assert result["lots"][0]["name"] == "奇美樓地下機車停車場"


def test_fixture_mode_missing_recording_is_error(fixture_mode):
    result = ncku_parking.get_parking_availability("成杏", "汽車")
    assert result["status"] == "error"
    assert "fixture" in result["error_message"]


def test_sorted_by_available_descending(live, monkeypatch):
    # Agent 拿到的第一筆應該就是車位最多的，方便直接推薦
    monkeypatch.setattr(ncku_parking.requests, "post", lambda *a, **k: FakeResponse(load("C_moto.html")))
    result = ncku_parking.get_parking_availability("自強", "機車")
    avail = [lot["available"] for lot in result["lots"]]
    assert avail == sorted(avail, reverse=True)
