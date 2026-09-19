"""bike_plan Skill 測試：三段行程的組合邏輯，不打網路也不花錢。"""
import pytest

from commute_agent.skills import bike_plan
from commute_agent.skills.bike_plan import find_station, walk_leg

HOME = {"status": "ok", "lat": 22.9873692, "lon": 120.2204914, "name": "某路一段1號"}
CSIE = {"status": "ok", "lat": 22.997228, "lon": 120.220837, "name": "B501 資訊工程系館"}

STATIONS = [
    {"name": "勝利國小(長榮路)", "lat": 22.98884, "lon": 120.22095, "bikes": 2, "docks": 18},
    {"name": "大學長榮", "lat": 22.99602, "lon": 120.22216, "bikes": 9, "docks": 41},
]


@pytest.fixture
def world(monkeypatch):
    state = {"ride": {"status": "ok", "minutes": 5, "distance_m": 1216,
                      "provider": "google_routes", "is_estimate": False},
             "ride_calls": 0}

    places = {"家": HOME, "B501 資訊工程系館": CSIE}
    monkeypatch.setattr(bike_plan, "geocode_place",
                        lambda p: places.get(p, {"status": "not_found", "lat": None,
                                                 "lon": None, "name": ""}))
    monkeypatch.setattr(bike_plan, "fetch_stations", lambda: STATIONS)

    def fake_time(origin, destination, mode, provider=None):
        state["ride_calls"] += 1
        state["last"] = {"mode": mode, "provider": provider}
        return state["ride"]

    monkeypatch.setattr(bike_plan, "get_travel_time", fake_time)
    return state


def plan(**kw):
    return bike_plan.plan_bike_journey(
        kw.get("origin", "家"), kw.get("destination", "B501 資訊工程系館"),
        kw.get("from_station", "勝利國小(長榮路)"), kw.get("to_station", "大學長榮"))


def test_station_is_found_by_name():
    assert find_station(STATIONS, "大學長榮")["bikes"] == 9


def test_unknown_station_is_none():
    assert find_station(STATIONS, "不存在的站") is None


def test_walk_leg_reports_distance_and_minutes():
    leg = walk_leg(22.9873692, 120.2204914, 22.98884, 120.22095)
    assert leg["distance_m"] > 0
    assert leg["minutes"] >= 1
    assert leg["is_estimate"] is True


def test_three_legs_are_added_up(world):
    r = plan()
    assert r["status"] == "ok"
    expected = (r["walk_to_station"]["minutes"] + r["ride"]["minutes"]
                + r["walk_to_destination"]["minutes"])
    assert r["total_minutes"] == expected


def test_only_the_ride_leg_costs_an_api_call(world):
    # 兩段步行距離短，用座標估就夠，不值得各打一次付費 API
    plan()
    assert world["ride_calls"] == 1
    assert world["last"] == {"mode": "bicycling", "provider": "google"}


def test_walk_legs_are_always_estimates(world):
    r = plan()
    assert r["walk_to_station"]["is_estimate"] is True
    assert r["walk_to_destination"]["is_estimate"] is True


def test_total_is_none_when_ride_cannot_be_computed(world):
    world["ride"] = {"status": "unavailable", "minutes": None, "distance_m": None,
                     "provider": "estimate", "is_estimate": True, "reason": "額度用盡"}
    r = plan()
    assert r["total_minutes"] is None
    assert r["ride"]["unavailable_reason"] == "額度用盡"


def test_map_link_passes_through_both_stations(world):
    link = plan()["map_link"]
    assert "waypoints" in link
    assert "travelmode=bicycling" in link


def test_unknown_origin_is_an_error(world):
    assert plan(origin="火星")["status"] == "error"


def test_unknown_station_is_an_error(world):
    r = plan(from_station="不存在的站")
    assert r["status"] == "error"
    assert "不存在的站" in r["error_message"]
