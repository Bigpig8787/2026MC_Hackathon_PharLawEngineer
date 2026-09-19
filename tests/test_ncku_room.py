"""lookup_room Tool 測試。fixture 皆為真實錄製的 nckumap 回應。"""
import json
from pathlib import Path

import pytest
import requests

from commute_agent.tools import ncku_room

FIXTURES = Path(__file__).resolve().parent.parent / "commute_agent" / "fixtures" / "ncku_gis" / "roominfo"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeResponse:
    def __init__(self, payload=None, status_code=200, bad_json=False):
        self._payload, self.status_code, self._bad = payload, status_code, bad_json

    def json(self):
        if self._bad:
            raise ValueError("not json")
        return self._payload


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("PROVIDER_MODE", "live")


@pytest.fixture
def fixture_mode(monkeypatch):
    monkeypatch.setenv("PROVIDER_MODE", "fixture")


# ---------- 純解析 ----------

def test_parse_4264_maps_fields():
    cands = ncku_room.parse_room_response(load("4264.json"), "4264")
    assert cands == [{
        "room_code": "4264",
        "room_name": "",
        "floor": "2F",
        "space_id": "B02902005",
        "building_id": "B029",
        "building_name": "B501 資訊工程系館",
        "building_name_en": "B501 Computer Science and Information Engineering Old Bldg.",
        "exact_match": True,
    }]


def test_parse_65304_marks_only_exact_code_as_exact():
    # 模糊搜尋會同時回傳 65304-A（資訊機房）與 65304（電腦教室）
    cands = ncku_room.parse_room_response(load("65304.json"), "65304")
    exact = [c for c in cands if c["exact_match"]]
    assert len(cands) == 2
    assert [c["room_code"] for c in exact] == ["65304"]
    assert exact[0]["building_name"] == "B502 資訊工程系大樓"


def test_old_and_new_csie_buildings_are_distinguished():
    # 課表都寫「資訊系館」，但 4264 在舊館 B501、65304 在新館 B502
    old = ncku_room.parse_room_response(load("4264.json"), "4264")[0]
    new = [c for c in ncku_room.parse_room_response(load("65304.json"), "65304") if c["exact_match"]][0]
    assert old["building_id"] != new["building_id"]


def test_parse_rejects_unexpected_schema():
    with pytest.raises(ncku_room.SchemaError):
        ncku_room.parse_room_response({"rows": []}, "4264")


# ---------- live 模式（網路以 monkeypatch 取代） ----------

def test_live_calls_real_endpoint_with_expected_params(live, monkeypatch):
    captured = {}

    def fake_get(url, params, timeout, headers):
        captured.update(url=url, params=params, timeout=timeout)
        return FakeResponse(load("4264.json"))

    monkeypatch.setattr(ncku_room.requests, "get", fake_get)
    result = ncku_room.lookup_room("4264")

    assert captured["url"] == "https://db.nckumap.ncku.edu.tw/nckugis/public/roominfo.htm"
    assert captured["params"]["action"] == "search"
    assert captured["params"]["q"] == "4264"
    assert captured["params"]["exactlyMatch"] == "false"
    assert captured["timeout"] > 0
    assert result["status"] == "ok"
    assert result["mode"] == "live"
    assert result["exact_match_count"] == 1
    assert result["source"].startswith("https://db.nckumap.ncku.edu.tw/")
    assert "fetched_at" in result


def test_live_empty_result_is_not_found(live, monkeypatch):
    monkeypatch.setattr(ncku_room.requests, "get",
                        lambda *a, **k: FakeResponse({"data": [], "totalCount": 0}))
    result = ncku_room.lookup_room("不存在的教室")
    assert result["status"] == "not_found"
    assert result["candidates"] == []


def test_live_timeout_returns_error_not_exception(live, monkeypatch):
    def boom(*a, **k):
        raise requests.Timeout("slow")
    monkeypatch.setattr(ncku_room.requests, "get", boom)
    result = ncku_room.lookup_room("4264")
    assert result["status"] == "error"
    assert "逾時" in result["error_message"]


def test_live_http_500_returns_error(live, monkeypatch):
    monkeypatch.setattr(ncku_room.requests, "get", lambda *a, **k: FakeResponse(status_code=500))
    assert ncku_room.lookup_room("4264")["status"] == "error"


def test_live_non_json_returns_error(live, monkeypatch):
    monkeypatch.setattr(ncku_room.requests, "get", lambda *a, **k: FakeResponse(bad_json=True))
    assert ncku_room.lookup_room("4264")["status"] == "error"


# ---------- fixture 模式 ----------

def test_fixture_mode_reads_recorded_file_without_network(fixture_mode, monkeypatch):
    def no_network(*a, **k):
        raise AssertionError("fixture 模式不應打網路")
    monkeypatch.setattr(ncku_room.requests, "get", no_network)
    result = ncku_room.lookup_room("4264")
    assert result["status"] == "ok"
    assert result["mode"] == "fixture"
    assert result["candidates"][0]["floor"] == "2F"


def test_fixture_mode_missing_recording_is_error(fixture_mode):
    result = ncku_room.lookup_room("99999")
    assert result["status"] == "error"
    assert "fixture" in result["error_message"]


# ---------- 輸入驗證 ----------

@pytest.mark.parametrize("bad", ["", "   ", "x" * 51])
def test_invalid_query_returns_error(fixture_mode, bad):
    assert ncku_room.lookup_room(bad)["status"] == "error"


def test_query_is_stripped(fixture_mode):
    assert ncku_room.lookup_room("  4264  ")["status"] == "ok"
