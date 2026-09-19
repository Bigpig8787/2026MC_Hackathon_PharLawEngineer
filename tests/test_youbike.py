"""youbike 測試：篩選與排序是純函式，不打網路。"""
import pytest

from commute_agent.tools.youbike import (
    TAINAN_BOUNDS,
    YouBikeError,
    nearby_stations,
    parse_stations,
)

# 成大圖書館附近，與實際站點位置相符
HERE = (22.995525, 120.219556)


def raw(name, lat, lng, bikes, docks, status=1):
    return {"name_tw": name, "address_tw": "某路1號", "lat": str(lat), "lng": str(lng),
            "available_spaces": bikes, "empty_spaces": docks,
            "parking_spaces": bikes + docks, "status": status, "updated_at": "2026-09-19"}


def station(name, lat, lon, bikes, docks):
    return {"name": name, "address": "", "lat": lat, "lon": lon,
            "bikes": bikes, "docks": docks, "capacity": bikes + docks, "updated_at": ""}


def test_stations_outside_tainan_are_dropped():
    # 官方端點回的是全台 9500 多站，留著只是浪費記憶體
    payload = [raw("台北某站", 25.04, 121.56, 5, 5), raw("台南某站", 22.99, 120.22, 5, 5)]
    assert [s["name"] for s in parse_stations(payload)] == ["台南某站"]


def test_disabled_stations_are_dropped():
    # status 非 1 代表停用或維護中，列出來會害使用者白跑一趟
    payload = [raw("維護中", 22.99, 120.22, 5, 5, status=0)]
    assert parse_stations(payload) == []


def test_rows_without_usable_coordinates_are_skipped():
    payload = [{"name_tw": "壞資料", "status": 1}, raw("好資料", 22.99, 120.22, 1, 1)]
    assert [s["name"] for s in parse_stations(payload)] == ["好資料"]


def test_non_list_payload_is_an_error():
    with pytest.raises(YouBikeError):
        parse_stations({"data": []})


def test_bounds_are_inclusive_at_the_edge():
    edge = raw("邊界", TAINAN_BOUNDS["lat_min"], TAINAN_BOUNDS["lon_min"], 1, 1)
    assert len(parse_stations([edge])) == 1


def test_nearest_station_comes_first():
    stations = [station("遠", 23.000, 120.2196, 5, 5),
                station("近", 22.9957, 120.2196, 5, 5)]
    assert nearby_stations(stations, *HERE)[0]["name"] == "近"


def test_stations_without_bikes_are_hidden_when_borrowing():
    stations = [station("空的", 22.9956, 120.2196, 0, 30),
                station("有車", 22.9958, 120.2196, 4, 10)]
    assert [s["name"] for s in nearby_stations(stations, *HERE, need="bike")] == ["有車"]


def test_full_stations_are_hidden_when_returning():
    # 借車與還車要的是相反的東西：站點爆滿時還不了車
    stations = [station("爆滿", 22.9956, 120.2196, 30, 0),
                station("有空位", 22.9958, 120.2196, 2, 8)]
    assert [s["name"] for s in nearby_stations(stations, *HERE, need="dock")] == ["有空位"]


def test_stations_beyond_radius_are_excluded():
    far = [station("兩公里外", 23.015, 120.2196, 10, 10)]
    assert nearby_stations(far, *HERE, radius_m=600) == []


def test_walk_time_is_reported_for_each_station():
    stations = [station("附近", 22.9958, 120.2196, 5, 5)]
    found = nearby_stations(stations, *HERE)[0]
    assert found["walk_minutes"] >= 1
    assert found["distance_m"] >= 0


def test_limit_caps_the_number_of_results():
    stations = [station(f"站{i}", 22.9956 + i * 0.0002, 120.2196, 5, 5) for i in range(10)]
    assert len(nearby_stations(stations, *HERE, limit=3)) == 3


def test_no_usable_station_returns_empty_list():
    assert nearby_stations([], *HERE) == []
