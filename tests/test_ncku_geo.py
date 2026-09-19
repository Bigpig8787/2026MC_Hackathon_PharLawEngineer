"""ncku_geo 測試：距離與時間都是純數學，不打網路。"""
import pytest

from commute_agent.tools.ncku_geo import (
    DETOUR_FACTOR,
    SPEED_M_PER_MIN,
    best_match,
    estimate_minutes,
    haversine_meters,
    strip_build_code,
)

# 成大實測座標：B501 資訊工程系館與 A004 雲平大樓東棟
CSIE = (22.997228266312952, 120.22083681028772)


def test_distance_to_itself_is_zero():
    assert haversine_meters(*CSIE, *CSIE) == pytest.approx(0, abs=1e-6)


def test_known_short_campus_distance_is_plausible():
    # 往北移 0.001 度緯度約等於 111 公尺
    d = haversine_meters(CSIE[0], CSIE[1], CSIE[0] + 0.001, CSIE[1])
    assert 105 < d < 118


def test_distance_is_symmetric():
    a, b = CSIE, (22.9990, 120.2170)
    assert haversine_meters(*a, *b) == pytest.approx(haversine_meters(*b, *a))


def test_walking_estimate_applies_detour_factor():
    # 直線距離先乘繞路係數，再除以步行速率；速率是可調參數，不要寫死
    expected = round(800 * DETOUR_FACTOR / SPEED_M_PER_MIN["walking"])
    assert estimate_minutes(800, "walking") == expected


def test_faster_modes_take_less_time():
    walk = estimate_minutes(2000, "walking")
    bike = estimate_minutes(2000, "bicycling")
    drive = estimate_minutes(2000, "driving")
    assert walk > bike > drive


def test_very_short_distance_still_reports_at_least_one_minute():
    assert estimate_minutes(5, "walking") == 1


def test_transit_has_no_estimate():
    # 大眾運輸受班次影響，估了只會誤導，應明確回 None
    assert estimate_minutes(2000, "transit") is None


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        estimate_minutes(100, "teleport")


def test_build_code_is_stripped():
    assert strip_build_code("B208 理學教學大樓") == "理學教學大樓"
    assert strip_build_code("生醫卓群大樓") == "生醫卓群大樓"


def test_alias_in_keyword_beats_incidental_name_match():
    # 查「理學」時 GIS 會把「管理學院綜合大樓」排第一（名稱裡剛好有「理學」），
    # 但正確答案是 keyword 含「理學院」的 B208
    rows = [
        {"name": "A703 管理學院綜合大樓", "keyword": "管院 統計系館 交管系館"},
        {"name": "B208 理學教學大樓", "keyword": "物理系館 化學系館 理學院"},
    ]
    assert best_match(rows, "理學")["name"] == "B208 理學教學大樓"


def test_alias_match_when_official_name_differs():
    # 「奇美樓」的正式名稱是「奇美大樓」，只有 keyword 對得上
    rows = [{"name": "D501 奇美大樓｜電機工程系", "keyword": "奇美樓"}]
    assert best_match(rows, "奇美樓")["name"].startswith("D501")


def test_falls_back_to_gis_ordering_when_nothing_matches():
    rows = [{"name": "X001 某大樓", "keyword": ""}, {"name": "X002 另一棟", "keyword": ""}]
    assert best_match(rows, "完全無關")["name"] == "X001 某大樓"


def test_empty_rows_return_none():
    assert best_match([], "資訊系館") is None
