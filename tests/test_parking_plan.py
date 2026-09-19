"""parking_plan Skill 測試：排序與門檻邏輯是純函式，不打網路。"""
from commute_agent.skills.parking_plan import (
    MIN_AVAILABLE,
    lot_base_name,
    lot_name_candidates,
    rank_lots,
)

# 目的地：B501 資訊工程系館
DEST = (22.997228266312952, 120.22083681028772)


def lot(name, available, lat=None, lon=None, campus="成功校區"):
    return {"name": name, "campus": campus, "available": available, "lat": lat, "lon": lon}


def test_parking_suffix_is_stripped():
    assert lot_base_name("奇美樓地下機車停車場") == "奇美樓"
    assert lot_base_name("成杏校區平面汽車停車場") == "成杏校區"
    assert lot_base_name("管理學院機車停車場") == "管理學院"


def test_candidates_trim_directional_suffix():
    # 「雲平東側」查不到，退一步查「雲平」才對得到 A004 雲平大樓東棟
    assert lot_name_candidates("雲平東側機車停車場") == ["雲平東側", "雲平"]


def test_candidates_trim_building_suffix():
    assert lot_name_candidates("理學大樓地下機車停車場") == ["理學大樓", "理學"]


def test_candidates_do_not_trim_gates_or_roads():
    # 「光復前門」再退一步會查到「光復第三宿舍」，那是錯的，所以不退
    assert lot_name_candidates("光復前門地下機車停車場") == ["光復前門"]
    assert lot_name_candidates("林森路平面機車停車場") == ["林森路"]


def test_nearest_lot_with_space_comes_first():
    lots = [
        lot("遠的", 500, DEST[0] + 0.005, DEST[1]),
        lot("近的", 500, DEST[0] + 0.001, DEST[1]),
    ]
    assert rank_lots(lots, *DEST)[0]["name"] == "近的"


def test_lot_below_threshold_is_ranked_after_ones_with_space():
    # 使用者要求：車位少於 30 就別推薦，即使它最近
    lots = [
        lot("最近但快滿", MIN_AVAILABLE - 1, DEST[0] + 0.0005, DEST[1]),
        lot("稍遠但夠停", 200, DEST[0] + 0.003, DEST[1]),
    ]
    ranked = rank_lots(lots, *DEST)
    assert ranked[0]["name"] == "稍遠但夠停"
    assert ranked[0]["enough_space"] is True
    assert ranked[1]["enough_space"] is False


def test_exactly_at_threshold_counts_as_enough():
    ranked = rank_lots([lot("剛好三十", MIN_AVAILABLE, *DEST)], *DEST)
    assert ranked[0]["enough_space"] is True


def test_zero_spaces_is_not_enough():
    ranked = rank_lots([lot("停滿了", 0, *DEST)], *DEST)
    assert ranked[0]["enough_space"] is False


def test_lot_without_coordinates_sorts_last_and_has_no_distance():
    # 校門、路邊停車場在 GIS 查不到座標，不知道距離就不該假裝它近
    lots = [lot("沒座標", 500), lot("有座標但遠", 500, DEST[0] + 0.01, DEST[1])]
    ranked = rank_lots(lots, *DEST)
    assert ranked[0]["name"] == "有座標但遠"
    assert ranked[-1]["name"] == "沒座標"
    assert ranked[-1]["distance_m"] is None
    assert ranked[-1]["minutes"] is None


def test_distance_and_minutes_are_filled_in_for_located_lots():
    ranked = rank_lots([lot("近的", 500, DEST[0] + 0.001, DEST[1])], *DEST)
    assert 100 < ranked[0]["distance_m"] < 120
    assert ranked[0]["minutes"] >= 1


def test_travel_mode_changes_the_estimate():
    lots = [lot("遠的", 500, DEST[0] + 0.02, DEST[1])]
    walking = rank_lots(lots, *DEST, travel_mode="walking")[0]["minutes"]
    driving = rank_lots(lots, *DEST, travel_mode="driving")[0]["minutes"]
    assert walking > driving


def test_empty_input_returns_empty():
    assert rank_lots([], *DEST) == []
