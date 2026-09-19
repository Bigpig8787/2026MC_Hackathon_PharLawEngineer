"""ncku_floorplan 測試：索引用假資料，WFS 用假回應，不打網路。"""
from urllib.parse import parse_qs, urlparse

import pytest

from commute_agent.tools import ncku_floorplan as fp
from commute_agent.tools.ncku_floorplan import (floor_plan_url, get_rooms_on_floor,
                                                list_floors, locate_room_on_plan,
                                                normalize_floor)

INDEX = {"buildings": {
    "B029": {"1F": [0.0, 0.0, 100.0, 50.0], "2F": [0.0, 0.0, 100.0, 50.0]},
    "A029": {"B2": [0, 0, 10, 10], "B1": [0, 0, 10, 10], "1F": [0, 0, 10, 10],
             "2F": [0, 0, 10, 10], "10F": [0, 0, 10, 10]},
}}


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setattr(fp, "load_index", lambda: INDEX)


def test_floors_are_ordered_from_the_basement_up(world):
    assert list_floors("A029") == ["B2", "B1", "1F", "2F", "10F"]


def test_unknown_building_has_no_floors(world):
    assert list_floors("ZZZZ") == []


def test_normalize_floor_matches_the_layer_naming():
    assert normalize_floor("2f") == "2F"
    assert normalize_floor("夾層") == "MEZ"


def test_url_points_at_the_right_wms_layer(world):
    found = floor_plan_url("B029", "2F", 800, 400)
    assert found["status"] == "ok"
    query = parse_qs(urlparse(found["url"]).query)
    assert query["layers"] == ["gis_room:B029_2F"]
    assert query["request"] == ["GetMap"]
    assert query["srs"] == ["EPSG:3826"]
    assert (query["width"], query["height"]) == (["800"], ["400"])


def test_the_bbox_is_padded_so_walls_are_not_cut_off(world):
    box = floor_plan_url("B029", "2F")["bbox"]
    assert box["minx"] < 0 and box["maxx"] > 100


def test_a_missing_floor_says_which_floors_exist(world):
    found = floor_plan_url("B029", "9F")
    assert found["status"] == "not_found"
    assert "1F、2F" in found["error_message"]


def test_a_building_without_any_layer_is_reported(world):
    found = floor_plan_url("B204", "B1")
    assert found["status"] == "not_found"
    assert "沒有任何平面圖" in found["error_message"]


def test_image_size_is_capped(world):
    found = floor_plan_url("B029", "2F", 99999, 99999)
    assert found["width"] == fp.MAX_PIXELS


def test_room_position_is_a_percentage_with_the_y_axis_flipped():
    # 地理座標往北變大，圖片座標往下變大，所以 top 要用 maxy 去減
    box = {"minx": 0.0, "miny": 0.0, "maxx": 100.0, "maxy": 50.0}
    bounds = {"minx": 10.0, "miny": 10.0, "maxx": 20.0, "maxy": 20.0}
    found = locate_room_on_plan(bounds, box)
    assert (found["left"], found["width"]) == (10.0, 10.0)
    assert (found["top"], found["height"]) == (60.0, 20.0)


def test_room_position_needs_both_boxes():
    assert locate_room_on_plan(None, {"minx": 0}) is None
    assert locate_room_on_plan({"minx": 0}, None) is None


def test_rooms_carry_their_code_and_extent(world, monkeypatch):
    payload = {"features": [{
        "properties": {"ClassNum": "4264", "RoomName": "", "Type": "普通教室",
                       "Capacity": "60", "UsingUnitName": "資訊工程學系", "AREA": 66.6},
        "geometry": {"type": "MultiPolygon",
                     "coordinates": [[[[1.0, 2.0], [3.0, 4.0], [1.0, 2.0]]]]}}]}

    monkeypatch.setattr(fp.requests, "get",
                        lambda *a, **k: type("R", (), {"status_code": 200,
                                                       "json": lambda self: payload})())
    room = get_rooms_on_floor("B029", "2F")["rooms"][0]
    assert room["room_code"] == "4264"
    assert room["bounds"] == {"minx": 1.0, "miny": 2.0, "maxx": 3.0, "maxy": 4.0}


def test_a_non_json_reply_means_the_layer_is_missing(world, monkeypatch):
    def bad_json(self):
        raise ValueError("not json")

    monkeypatch.setattr(fp.requests, "get",
                        lambda *a, **k: type("R", (), {"status_code": 200,
                                                       "json": bad_json})())
    assert get_rooms_on_floor("B029", "9F")["status"] == "not_found"


def test_network_failure_is_reported_not_raised(world, monkeypatch):
    def boom(*a, **k):
        raise fp.requests.Timeout()

    monkeypatch.setattr(fp.requests, "get", boom)
    found = get_rooms_on_floor("B029", "2F")
    assert found["status"] == "error"
    assert "逾時" in found["error_message"]
