"""ncku_campus_map 測試：座標換算是純函式，WFS 用假回應。"""
import math
from urllib.parse import parse_qs, urlparse

from commute_agent.tools import ncku_campus_map as cm
from commute_agent.tools.ncku_campus_map import (bbox_for, buildings_in_bbox,
                                                 campus_map_url, to_percent)

BBOX = {"minlon": 120.0, "minlat": 22.0, "maxlon": 121.0, "maxlat": 23.0}


def test_bbox_covers_every_point():
    box = bbox_for([(22.99, 120.21), (23.00, 120.22)])
    assert box["minlat"] < 22.99 and box["maxlat"] > 23.00
    assert box["minlon"] < 120.21 and box["maxlon"] > 120.22


def test_bbox_matches_the_image_aspect_so_the_campus_is_not_stretched():
    # 一度經度在這個緯度上比一度緯度短，要乘 cos(lat) 才是實際長寬比
    box = bbox_for([(22.99, 120.21), (23.00, 120.22)], 1200, 600)
    span_lon = box["maxlon"] - box["minlon"]
    span_lat = box["maxlat"] - box["minlat"]
    clat = (box["maxlat"] + box["minlat"]) / 2
    ratio = (span_lon * math.cos(math.radians(clat))) / span_lat
    assert abs(ratio - 2.0) < 0.01


def test_two_points_at_the_same_spot_still_get_a_usable_box():
    # 停車場就在大樓旁邊時 bbox 會塌成一個點，圖會放大到看不出東西在哪
    box = bbox_for([(22.99, 120.21), (22.99, 120.21)])
    assert box["maxlat"] - box["minlat"] >= cm.MIN_SPAN_DEGREES


def test_no_points_means_no_box():
    assert bbox_for([]) is None


def test_percentage_flips_the_y_axis():
    # 緯度往北變大，圖片座標往下變大
    assert to_percent(23.0, 120.0, BBOX) == {"left": 0.0, "top": 0.0}
    assert to_percent(22.0, 121.0, BBOX) == {"left": 100.0, "top": 100.0}


def test_percentage_needs_a_box():
    assert to_percent(23.0, 120.0, None) is None


def test_map_url_stacks_the_campus_layers():
    found = campus_map_url(BBOX, 800, 400)
    assert found["status"] == "ok"
    query = parse_qs(urlparse(found["url"]).query)
    assert query["layers"] == [",".join(cm.BASE_LAYERS)]
    assert query["srs"] == ["EPSG:4326"]
    assert query["bbox"] == ["120.0,22.0,121.0,23.0"]


def test_map_url_needs_a_box():
    assert campus_map_url(None)["status"] == "not_found"


def test_map_size_is_capped():
    assert campus_map_url(BBOX, 99999, 99999)["width"] == cm.MAX_PIXELS


def test_buildings_carry_name_and_centre(monkeypatch):
    payload = {"features": [{
        "properties": {"Name": "資訊系館"},
        "geometry": {"type": "Polygon",
                     "coordinates": [[[120.0, 22.0], [121.0, 23.0], [120.0, 22.0]]]}}]}
    monkeypatch.setattr(cm.requests, "get",
                        lambda *a, **k: type("R", (), {"status_code": 200,
                                                       "json": lambda self: payload})())
    found = buildings_in_bbox(BBOX)
    assert found["buildings"] == [{"name": "資訊系館", "lat": 22.5, "lon": 120.5}]


def test_nameless_buildings_are_skipped(monkeypatch):
    # 沒有名字的多邊形拿來指路也講不出口
    payload = {"features": [{"properties": {"Name": ""},
                             "geometry": {"type": "Point", "coordinates": [120.0, 22.0]}}]}
    monkeypatch.setattr(cm.requests, "get",
                        lambda *a, **k: type("R", (), {"status_code": 200,
                                                       "json": lambda self: payload})())
    assert buildings_in_bbox(BBOX)["buildings"] == []


def test_network_failure_is_reported_not_raised(monkeypatch):
    def boom(*a, **k):
        raise cm.requests.Timeout()

    monkeypatch.setattr(cm.requests, "get", boom)
    found = buildings_in_bbox(BBOX)
    assert found["status"] == "error"
    assert "逾時" in found["error_message"]
