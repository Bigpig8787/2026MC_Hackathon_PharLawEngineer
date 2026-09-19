"""tdx_bus 測試：解析與去重是純函式，不打網路也不需要金鑰。"""
from commute_agent.tools.tdx_bus import parse_arrivals, parse_stops, unique_by_name

HERE = (22.997228, 120.220837)   # B501 資訊工程系館


def raw_stop(name, uid, lat, lon):
    return {"StopName": {"Zh_tw": name}, "StopUID": uid,
            "StopPosition": {"PositionLat": lat, "PositionLon": lon}}


def raw_eta(uid, route, seconds, status=0, stop="成大自強校區"):
    return {"StopUID": uid, "RouteName": {"Zh_tw": route},
            "StopName": {"Zh_tw": stop}, "EstimateTime": seconds,
            "StopStatus": status, "Direction": 0}


def test_stops_are_sorted_by_distance():
    rows = [raw_stop("遠站", "A", 23.001, 120.2208),
            raw_stop("近站", "B", 22.9975, 120.2208)]
    assert [s["name"] for s in parse_stops(rows, *HERE)] == ["近站", "遠站"]


def test_stop_without_position_is_skipped():
    rows = [{"StopName": {"Zh_tw": "沒座標"}, "StopUID": "X"},
            raw_stop("有座標", "B", 22.9975, 120.2208)]
    assert [s["name"] for s in parse_stops(rows, *HERE)] == ["有座標"]


def test_walk_time_is_reported_for_each_stop():
    rows = [raw_stop("站", "A", 22.9975, 120.2208)]
    assert parse_stops(rows, *HERE)[0]["walk_minutes"] >= 1


def test_arrivals_are_sorted_soonest_first():
    rows = [raw_eta("A", "77", 1200), raw_eta("A", "0左", 300)]
    assert [a["route"] for a in parse_arrivals(rows, {"A"})] == ["0左", "77"]


def test_seconds_are_converted_to_minutes():
    assert parse_arrivals([raw_eta("A", "77", 780)], {"A"})[0]["minutes"] == 13


def test_arrivals_at_other_stops_are_excluded():
    rows = [raw_eta("A", "77", 300), raw_eta("Z", "88", 60)]
    assert [a["route"] for a in parse_arrivals(rows, {"A"})] == ["77"]


def test_missing_estimate_is_dropped_rather_than_shown_as_zero():
    # 沒有車在跑時 EstimateTime 是 None，顯示成「0 分鐘到站」會誤導
    assert parse_arrivals([raw_eta("A", "77", None)], {"A"}) == []


def test_abnormal_stop_status_is_dropped():
    # StopStatus 非 0 代表未發車或末班已過
    assert parse_arrivals([raw_eta("A", "77", 300, status=1)], {"A"}) == []


def test_imminent_bus_is_reported_as_zero_minutes():
    assert parse_arrivals([raw_eta("A", "77", 20)], {"A"})[0]["minutes"] == 0


def test_duplicate_stop_names_collapse_to_the_nearest():
    # 同一站名常有多個 UID（對向、對街），顯示時只留最近的
    stops = [{"name": "成大自強校區", "stop_uid": "A", "distance_m": 154, "walk_minutes": 2},
             {"name": "成大自強校區", "stop_uid": "B", "distance_m": 164, "walk_minutes": 2},
             {"name": "大學路口", "stop_uid": "C", "distance_m": 300, "walk_minutes": 4}]
    unique = unique_by_name(stops)
    assert [s["name"] for s in unique] == ["成大自強校區", "大學路口"]
    assert unique[0]["stop_uid"] == "A"


def test_empty_input_is_handled():
    assert parse_stops([], *HERE) == []
    assert parse_arrivals([], set()) == []
    assert unique_by_name([]) == []
