"""classroom_guide 測試：GIS 與平面圖對照表都用假資料。"""
import pytest

from commute_agent.skills import classroom_guide as cg
from commute_agent.skills.classroom_guide import locate_classroom

CANDIDATE = {"room_code": "4264", "room_name": "", "floor": "2F",
             "building_id": "B029", "building_name": "B501 資訊工程系館",
             "building_name_en": "", "space_id": "", "exact_match": True}

PLAN = {"status": "ok", "floor": "2F", "floor_source": "given",
        "floor_rule": "42 開頭的大樓代號只有一碼，樓層看第 2 碼",
        "floor_by_room_code": "2F",
        "plan": {"file": "42.png", "url": "/picture/42.png",
                 "caption": "資訊系館 2F", "available": True},
        "plan_floor": "2F", "plan_building": "B501 資訊工程系館",
        "campus_map": {"file": "NCKU.png", "url": "/picture/NCKU.png",
                       "caption": "校區全圖", "available": True}}


@pytest.fixture
def world(monkeypatch):
    state = {"room": {"status": "ok", "candidates": [dict(CANDIDATE)],
                      "exact_match_count": 1, "source": "http://gis"},
             "plan": dict(PLAN)}

    monkeypatch.setattr(cg, "lookup_room", lambda q: state["room"])
    monkeypatch.setattr(cg, "get_floor_plan",
                        lambda code, name="", floor="": state["plan"])
    monkeypatch.setattr(cg, "get_building_centroid",
                        lambda bid: {"status": "ok", "name": "B501 資訊工程系館",
                                     "lat": 22.9972, "lon": 120.2208})
    monkeypatch.setattr(cg, "build_route_link",
                        lambda target, origin=None, travel_mode="walking": "http://map")
    return state


def test_conclusion_says_which_floor(world):
    found = locate_classroom("4264")
    assert found["status"] == "ok"
    assert "2 樓" in found["conclusion"]
    assert found["floor_source"] == "gis"


def test_coordinates_come_from_the_building_id(world):
    # 用名稱搜尋會對到別棟，一定要走 build_id
    assert locate_classroom("4264")["location"]["lat"] == 22.9972


def test_floor_plan_is_returned(world):
    assert locate_classroom("4264")["floor_plan"]["plan"]["url"] == "/picture/42.png"


def test_gis_wins_but_the_disagreement_is_reported(world):
    # 代碼推算 3F、GIS 說 2F：以 GIS 為準，但不能把差異吞掉
    world["plan"] = {**PLAN, "floor_by_room_code": "3F"}
    found = locate_classroom("4264")
    assert found["floor"] == "2F"
    assert "以 GIS 為準" in found["floor_conflict"]


def test_no_conflict_when_the_two_agree(world):
    assert locate_classroom("4264")["floor_conflict"] is None


def test_floor_falls_back_to_the_room_code_rule(world):
    # GIS 沒有樓層時用代碼推算，而且要講明這是推算
    world["room"] = {**world["room"],
                     "candidates": [{**CANDIDATE, "floor": ""}]}
    found = locate_classroom("4264")
    assert found["floor"] == "2F"
    assert found["floor_source"] == "room_code"
    assert "推算" in found["conclusion"]


def test_the_floor_plan_answers_when_the_gis_cannot(world):
    # 「格致廳小講堂」在 GIS 查不到，但平面圖對照表認得它
    world["room"] = {"status": "not_found", "candidates": [],
                     "exact_match_count": 0, "source": "http://gis"}
    world["plan"] = {**PLAN, "floor_by_room_code": None, "plan_floor": "B1",
                     "plan_building": "資訊大樓"}
    found = locate_classroom("格致廳小講堂")
    assert found["building_name"] == "資訊大樓"
    assert found["floor_source"] == "floor_plan"
    assert "地下 1 樓" in found["conclusion"]


def test_lookup_error_is_propagated(world):
    world["room"] = {"status": "error", "candidates": [],
                     "error_message": "成大地理資訊系統查詢逾時"}
    found = locate_classroom("4264")
    assert found["status"] == "error"
    assert "逾時" in found["error_message"]


def test_empty_query_is_rejected(world):
    assert locate_classroom("  ")["status"] == "error"
