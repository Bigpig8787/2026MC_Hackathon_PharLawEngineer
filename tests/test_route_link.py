"""build_route_link Tool 測試：以地點名稱搜尋式導航連結，不需要 Google Maps API 金鑰。"""
import pytest

from commute_agent.tools.route_link import TRAVEL_MODE_LABELS, build_route_link


def test_link_uses_google_maps_dir_api_with_place_name():
    link = build_route_link("B502 資訊工程系大樓")
    assert link.startswith("https://www.google.com/maps/dir/?api=1")
    assert "travelmode=walking" in link
    assert "destination=" in link


def test_destination_is_prefixed_with_ncku_to_disambiguate():
    # "資訊系館" 這種名稱在其他學校也可能存在，加上校名避免導航到別的城市
    link = build_route_link("B502 資訊工程系大樓")
    assert "%E6%88%90%E5%8A%9F%E5%A4%A7%E5%AD%B8" in link or "成功大學" in link


def test_origin_included_when_provided():
    link = build_route_link("B502 資訊工程系大樓", origin="敬業一舍")
    assert "origin=" in link


def test_origin_omitted_uses_current_location():
    # 不給 origin 時，Google Maps 會用使用者當下定位，不應出現 origin 參數
    link = build_route_link("B502 資訊工程系大樓")
    assert "origin=" not in link


def test_building_name_is_url_encoded():
    link = build_route_link("B204 理化實驗大樓")
    assert " " not in link


def test_empty_destination_raises():
    with pytest.raises(ValueError):
        build_route_link("")


def test_walking_is_the_default_mode():
    assert "travelmode=walking" in build_route_link("B501 資訊工程系館")


@pytest.mark.parametrize("mode", ["walking", "bicycling", "driving", "transit"])
def test_every_supported_mode_reaches_the_url(mode):
    assert f"travelmode={mode}" in build_route_link("B501 資訊工程系館", travel_mode=mode)


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        build_route_link("B501 資訊工程系館", travel_mode="teleport")


def test_every_mode_has_a_chinese_label():
    # 介面的模式選單直接用這份標籤，缺一個就會顯示成英文代碼
    assert set(TRAVEL_MODE_LABELS) == {"walking", "bicycling", "driving", "transit"}


def test_parking_lot_can_be_a_destination():
    # 停車場不是大樓，但一樣要能當目的地
    link = build_route_link("奇美樓地下機車停車場", travel_mode="driving")
    assert "travelmode=driving" in link


def test_pure_function_no_network_or_settings_needed():
    # Tool 層原則：這支不打任何 API，是純函式
    import commute_agent.tools.route_link as m
    assert not hasattr(m, "requests")


def test_waypoints_are_joined_for_google_maps():
    # YouBike 行程要把借車站與還車站串成一條路線
    link = build_route_link("B501 資訊工程系館", origin="家", travel_mode="bicycling",
                            waypoints=["勝利國小(長榮路)", "大學長榮"])
    assert "waypoints=" in link
    assert "%7C" in link          # | 的編碼


def test_empty_waypoints_are_omitted():
    link = build_route_link("B501 資訊工程系館", waypoints=["", "  ", None])
    assert "waypoints" not in link


def test_coordinates_are_sent_verbatim_not_as_a_place_name():
    # 這是重點：座標不該被加上校名，否則 Google 會當成地名去猜
    link = build_route_link((22.997228, 120.220837))
    assert "destination=22.997228%2C120.220837" in link
    assert "%E6%88%90%E5%8A%9F%E5%A4%A7%E5%AD%B8" not in link


def test_origin_coordinates_are_sent_verbatim():
    link = build_route_link("B501 資訊工程系館", origin=(22.9873, 120.2204))
    assert "origin=22.9873%2C120.2204" in link


def test_waypoint_coordinates_are_sent_verbatim():
    link = build_route_link((22.996, 120.222), origin=(22.987, 120.220),
                            travel_mode="bicycling",
                            waypoints=[(22.9888, 120.2209), (22.9960, 120.2221)])
    assert "22.9888%2C120.2209" in link
    assert "22.996%2C120.2221" in link


def test_origin_name_is_not_prefixed_with_campus():
    # 起點常是校外住家地址，補校名反而害它找不到
    link = build_route_link("B501 資訊工程系館", origin="台南市東區某路一段1號")
    assert "origin=%E5%8F%B0%E5%8D%97" in link


def test_name_already_carrying_campus_is_not_doubled():
    link = build_route_link("國立成功大學 B501 資訊工程系館")
    assert link.count("%E5%9C%8B%E7%AB%8B%E6%88%90%E5%8A%9F%E5%A4%A7%E5%AD%B8") == 1
