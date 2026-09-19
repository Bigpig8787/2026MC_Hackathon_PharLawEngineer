"""trip_plan Skill 測試：座標查詢以假資料取代，不打網路。"""
import pytest

from commute_agent.skills import trip_plan
from commute_agent.tools.ncku_geo import place_candidates

# 兩組都是 GIS getCentroidByBuildId 回傳的實際座標，不是估的
LIBRARY = {"status": "ok", "name": "G001 圖書館(舊)",
           "lat": 22.995525782871347, "lon": 120.21955682352767}
CSIE = {"status": "ok", "name": "B501 資訊工程系館",
        "lat": 22.997228266312952, "lon": 120.22083681028772}
MISSING = {"status": "not_found", "name": "", "lat": None, "lon": None}


@pytest.fixture
def places(monkeypatch):
    """把 resolve_place 換成查表，測試才不依賴 GIS 是否在線。"""
    table = {}

    def fake_resolve(query):
        return table.get(query, MISSING)

    monkeypatch.setattr(trip_plan, "resolve_place", fake_resolve)
    return table


def test_school_prefix_is_stripped_for_lookup():
    # GIS 索引裡沒有「成大圖書館」，只有「圖書館」
    assert place_candidates("成大圖書館") == ["成大圖書館", "圖書館"]
    assert place_candidates("國立成功大學雲平大樓") == ["國立成功大學雲平大樓", "雲平大樓"]


def test_plain_name_has_no_extra_candidate():
    assert place_candidates("圖書館") == ["圖書館"]


def test_trip_between_two_campus_places_is_estimated(places):
    places.update({"圖書館": LIBRARY, "B501 資訊工程系館": CSIE})
    trip = trip_plan.estimate_trip("圖書館", "B501 資訊工程系館")
    assert trip["can_estimate"] is True
    assert 200 < trip["distance_m"] < 260
    assert trip["minutes"] >= 1
    assert trip["origin_name"] == "G001 圖書館(舊)"


def test_faster_mode_gives_shorter_estimate(places):
    places.update({"圖書館": LIBRARY, "B501 資訊工程系館": CSIE})
    walk = trip_plan.estimate_trip("圖書館", "B501 資訊工程系館", "walking")["minutes"]
    bike = trip_plan.estimate_trip("圖書館", "B501 資訊工程系館", "bicycling")["minutes"]
    assert walk >= bike


def test_off_campus_origin_cannot_be_estimated_but_still_links(places):
    # 校外地址不在 GIS 裡，寧可說不知道也不要拿附近大樓充數。
    # 這裡刻意用車站當例子，真實住址屬個資，只能放在 .gitignore 擋掉的 .env
    places.update({"B501 資訊工程系館": CSIE})
    trip = trip_plan.estimate_trip("台南火車站", "B501 資訊工程系館")
    assert trip["can_estimate"] is False
    assert trip["unresolved"] == "origin"
    assert trip["minutes"] is None
    assert trip["route_link"].startswith("https://www.google.com/maps/dir/")


def test_unknown_destination_is_reported(places):
    places.update({"圖書館": LIBRARY})
    trip = trip_plan.estimate_trip("圖書館", "不存在的大樓")
    assert trip["can_estimate"] is False
    assert trip["unresolved"] == "destination"


def test_transit_has_distance_but_no_time(places):
    # 兩端都查得到，但班次無法預估，所以不給時間
    places.update({"圖書館": LIBRARY, "B501 資訊工程系館": CSIE})
    trip = trip_plan.estimate_trip("圖書館", "B501 資訊工程系館", "transit")
    assert trip["distance_m"] > 0
    assert trip["minutes"] is None
    assert trip["can_estimate"] is False


def test_unsupported_mode_is_rejected(places):
    trip = trip_plan.estimate_trip("圖書館", "B501 資訊工程系館", "teleport")
    assert trip["status"] == "error"


def test_route_link_carries_origin_and_mode(places):
    places.update({"圖書館": LIBRARY, "B501 資訊工程系館": CSIE})
    link = trip_plan.estimate_trip("圖書館", "B501 資訊工程系館", "driving")["route_link"]
    assert "travelmode=driving" in link
    assert "origin=" in link
