"""floor_plan 測試：只讀本地對照表，不打網路。"""
import json

import pytest

from commute_agent.tools import floor_plan as fp
from commute_agent.tools.floor_plan import (describe_floor, floor_from_room_code,
                                            get_floor_plan)

MANIFEST = {
    "campus_map": {"file": "NCKU.png", "caption": "成大光復校區全圖"},
    "plans": [
        {"file": "42.png", "caption": "資訊系館 2F", "building_name": "B501 資訊工程系館",
         "room_prefix": "42", "floor": "2F", "rooms": ["4261", "4264"]},
        {"file": "資訊大樓.png", "caption": "資訊大樓 B1", "building_name": "資訊大樓",
         "room_prefix": "", "floor": "B1", "rooms": ["35X01"],
         "name_keywords": ["格致廳"]},
    ],
}


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(fp, "load_manifest", lambda: json.loads(json.dumps(MANIFEST)))
    # 測試不依賴圖檔真的在不在，available 另外驗
    monkeypatch.setattr(fp.Path, "is_file", lambda self: True)


def test_two_digit_building_code_puts_the_floor_in_the_third_digit():
    # 27103 → 雲平東棟 1F、65304 → 資工大樓 3F
    assert floor_from_room_code("27103")["floor"] == "1F"
    assert floor_from_room_code("65304")["floor"] == "3F"
    assert floor_from_room_code("6021")["floor"] == "2F"


def test_one_digit_building_code_puts_the_floor_in_the_second_digit():
    # 42、72 開頭的大樓代號只有一碼，實測 4264 與 7208 都在 2F
    assert floor_from_room_code("4264")["floor"] == "2F"
    assert floor_from_room_code("7208")["floor"] == "2F"


def test_the_rule_explains_which_digit_it_used():
    assert "第 2 碼" in floor_from_room_code("4264")["rule"]
    assert "第 3 碼" in floor_from_room_code("27103")["rule"]


def test_a_zero_is_not_a_floor():
    # 規則解釋不了的代碼寧可不答，也不要湊出「0 樓」
    found = floor_from_room_code("1203")
    assert found["floor"] is None
    assert "0" in found["rule"]


def test_non_numeric_codes_give_no_floor():
    assert floor_from_room_code("格致廳")["floor"] is None
    assert floor_from_room_code("")["floor"] is None


def test_describe_floor_reads_as_chinese():
    assert describe_floor("2F") == "2 樓"
    assert describe_floor("B1") == "地下 1 樓"
    assert describe_floor("") == ""


def test_known_room_finds_its_plan(world):
    found = get_floor_plan("4264", floor="2F")
    assert found["status"] == "ok"
    assert found["plan"]["url"] == "/picture/42.png"


def test_plan_of_another_floor_is_not_reused(world):
    # 42.png 只有 2F；4464 在 4F，拿 2F 的圖給他比沒有圖更糟
    found = get_floor_plan("4464", floor="4F")
    assert found["status"] == "not_found"
    assert found["plan"] is None


def test_room_name_keyword_matches_when_there_is_no_code(world):
    found = get_floor_plan("", "格致廳小講堂")
    assert found["status"] == "ok"
    assert found["plan"]["file"] == "資訊大樓.png"


def test_floor_falls_back_to_the_room_code_rule(world):
    found = get_floor_plan("4261")
    assert found["floor"] == "2F"
    assert found["floor_source"] == "room_code"


def test_given_floor_wins_over_the_rule(world):
    # 成大 GIS 說 3F 就是 3F，代碼推算只是備援
    found = get_floor_plan("4264", floor="3F")
    assert found["floor"] == "3F"
    assert found["floor_source"] == "given"
    assert found["floor_by_room_code"] == "2F"


def test_campus_map_is_always_offered(world):
    assert get_floor_plan("9999")["campus_map"]["file"] == "NCKU.png"


def test_missing_manifest_does_not_raise(monkeypatch, tmp_path):
    monkeypatch.setattr(fp, "MANIFEST_PATH", tmp_path / "nope.json")
    assert fp.load_manifest()["plans"] == []
