"""trip_plan Skill 測試：座標查詢以假資料取代，不打網路。"""
import pytest

from commute_agent.skills import trip_plan
from commute_agent.tools import travel_time
from commute_agent.tools.ncku_geo import place_candidates

# 兩組都是 GIS getCentroidByBuildId 回傳的實際座標，不是估的
LIBRARY = {"status": "ok", "name": "G001 圖書館(舊)",
           "lat": 22.995525782871347, "lon": 120.21955682352767}
CSIE = {"status": "ok", "name": "B501 資訊工程系館",
        "lat": 22.997228266312952, "lon": 120.22083681028772}
MISSING = {"status": "not_found", "name": "", "lat": None, "lon": None}


@pytest.fixture
def places(monkeypatch):
    """把座標查詢換成查表，測試才不依賴 GIS 是否在線。

    座標解析已經搬到 travel_time 接口裡，所以要 patch 那一層；
    這裡同時鎖定 estimate 來源，確保測試不會因為 .env 改成 google 而去打計費 API。
    """
    table = {}
    monkeypatch.setattr(travel_time, "resolve_place",
                        lambda query: table.get(query, MISSING))
    monkeypatch.setattr(travel_time, "load_settings",
                        lambda: type("S", (), {"travel_time_provider": "estimate"})())
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


LOT = {"name": "三系館地下機車停車場", "campus": "成功校區", "available": 500,
       "minutes": 2, "distance_m": 110}


@pytest.fixture
def journey(monkeypatch):
    """把停車查詢與時間查詢都換成假資料，確保測試不打網路也不花錢。"""
    from commute_agent.skills import parking_plan

    calls = []

    def fake_plan_parking(destination, vehicle_type, walk_mode="walking"):
        return {"status": "ok", "recommended": dict(LOT), "alternatives": [],
                "skipped_full": ["某個滿的停車場"], "min_available": 30}

    def fake_travel_time(origin, destination, mode, provider=None):
        calls.append({"destination": destination, "mode": mode, "provider": provider})
        return {"status": "ok", "minutes": 6, "distance_m": 1523,
                "provider": "google_routes", "is_estimate": False}

    monkeypatch.setattr(parking_plan, "plan_parking", fake_plan_parking)
    monkeypatch.setattr(parking_plan, "load_lot_locations",
                        lambda *a, **k: {LOT["name"]: {"lat": 22.9977, "lon": 120.2192}})
    monkeypatch.setattr(trip_plan, "get_travel_time", fake_travel_time)
    return calls


def test_ride_and_walk_are_added_up(journey):
    r = trip_plan.plan_ride_and_walk("成大圖書館", "B501 資訊工程系館", "機車")
    assert r["ride"]["minutes"] == 6      # Google 算的騎車段
    assert r["walk"]["minutes"] == 2      # GIS 估的停車場→教室
    assert r["total_minutes"] == 8


def test_only_one_google_call_per_journey(journey):
    # 使用者要求最低限度呼叫付費 API：整趟只有騎車段花錢
    trip_plan.plan_ride_and_walk("成大圖書館", "B501 資訊工程系館", "機車")
    assert len(journey) == 1
    assert journey[0]["provider"] == "google"
    assert journey[0]["mode"] == "driving"


def test_ride_leg_is_sent_as_lot_coordinates(journey):
    # Google 不認得停車場名稱，要送座標
    trip_plan.plan_ride_and_walk("成大圖書館", "B501 資訊工程系館", "機車")
    assert journey[0]["destination"] == (22.9977, 120.2192)


def test_walk_leg_is_always_a_gis_estimate(journey):
    r = trip_plan.plan_ride_and_walk("成大圖書館", "B501 資訊工程系館", "機車")
    assert r["walk"]["is_estimate"] is True
    assert r["walk"]["provider"] == "estimate"


def test_total_is_none_when_ride_cannot_be_computed(journey, monkeypatch):
    monkeypatch.setattr(trip_plan, "get_travel_time",
                        lambda *a, **k: {"status": "unavailable", "minutes": None,
                                         "distance_m": None, "provider": "estimate",
                                         "is_estimate": True, "reason": "額度用盡"})
    r = trip_plan.plan_ride_and_walk("成大圖書館", "B501 資訊工程系館", "機車")
    assert r["total_minutes"] is None
    assert r["ride"]["unavailable_reason"] == "額度用盡"


def test_no_usable_lot_is_an_error(monkeypatch):
    from commute_agent.skills import parking_plan
    monkeypatch.setattr(parking_plan, "plan_parking",
                        lambda *a, **k: {"status": "not_found", "recommended": None,
                                         "alternatives": [], "skipped_full": []})
    r = trip_plan.plan_ride_and_walk("成大圖書館", "B501 資訊工程系館", "機車")
    assert r["status"] == "error"
    assert r["total_minutes"] is None
