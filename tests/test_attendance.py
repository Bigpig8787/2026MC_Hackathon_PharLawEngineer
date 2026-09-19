"""attendance 測試：座標與時間全由測試指定，不打網路也不看系統時鐘。"""
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from commute_agent.skills import attendance as att
from commute_agent.skills.attendance import (
    AT_CLASS_RADIUS_METERS,
    MAX_RADIUS_METERS,
    WORTH_ATTENDING_MINUTES,
    check_attendance,
)

TZ = ZoneInfo("Asia/Taipei")


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=TZ)


def iso(text: str) -> str:
    return at(text).isoformat(timespec="seconds")


# 教室所在的大樓。往北每 0.0009 度約 100 公尺：
# 走路速度 65 公尺／分、繞路係數 1.3，所以 500 公尺約走 10 分鐘
CLASS_PLACE = {"status": "ok", "name": "B501 資訊工程系館", "build_id": "B501",
               "lat": 23.0000, "lon": 120.2000, "is_verified": True}
NEAR_33M = (23.0003, 120.2000)
NEAR_200M = (23.0018, 120.2000)
NEAR_355M = (23.0032, 120.2000)
FAR_500M = (23.0045, 120.2000)


def current(start="2026-09-24T13:10", end="2026-09-24T16:10"):
    return {"name": "人工智慧導論", "location": "資訊系館4264", "room_query": "4264",
            "starts_at": iso(start), "ends_at": iso(end)}


def locate_ok(text, room=""):
    return CLASS_PLACE


def geocoder(**places):
    def geocode(text):
        if text in places:
            lat, lon = places[text]
            return {"status": "ok", "lat": lat, "lon": lon, "name": text, "source": "ncku_gis"}
        return {"status": "not_found", "lat": None, "lon": None, "name": ""}
    return geocode


def check(now="2026-09-24T13:30", place_text="", lat=None, lon=None, accuracy_m=None,
          cur=None, locate=locate_ok, **places):
    return check_attendance(cur if cur is not None else current(), at(now), place_text=place_text,
                            lat=lat, lon=lon, accuracy_m=accuracy_m, locate=locate,
                            geocode=geocoder(**places))


# ---- 在教室 ----

def test_being_in_the_classroom_building_counts_as_present():
    r = check(place_text="資訊系館", 資訊系館=NEAR_33M)
    assert r["status"] == "ok" and r["at_class"] is True
    assert r["distance_m"] < AT_CLASS_RADIUS_METERS
    assert r["suggestion"] is None and r["late_by"] == 0 and r["walk_minutes"] == 0


def test_present_still_reports_how_far_into_the_class_it_is():
    r = check(now="2026-09-24T13:30", place_text="資訊系館", 資訊系館=NEAR_33M)
    assert r["elapsed_minutes"] == 20 and r["remaining_minutes"] == 160


# ---- 不在教室 ----

def test_being_elsewhere_during_class_is_late_with_a_late_letter_when_still_worth_going():
    # 13:30，課 13:10 開始已 20 分鐘；圖書館走過去約 10 分 → 晚到約 30 分，之後還剩 150 分
    r = check(place_text="成大圖書館", 成大圖書館=FAR_500M)
    assert r["at_class"] is False
    assert r["distance_m"] > 400
    assert r["walk_minutes"] == 10
    assert r["late_by"] == 30
    assert r["suggestion"] == "late"
    assert "建議先通知老師會遲到" in r["advice"]


def test_advice_names_the_building_and_the_numbers():
    advice = check(place_text="成大圖書館", 成大圖書館=FAR_500M)["advice"]
    assert "B501 資訊工程系館" in advice
    assert "已開始 20 分鐘" in advice and "還剩 160 分鐘" in advice


def test_near_the_end_of_class_suggests_a_leave_letter():
    # 16:02：課只剩 8 分鐘，走過去要 10 分，到了課已經結束
    r = check(now="2026-09-24T16:02", place_text="成大圖書館", 成大圖書館=FAR_500M)
    assert r["at_class"] is False and r["suggestion"] == "leave"
    assert "請假" in r["advice"]


def test_worth_attending_boundary():
    walk = 10
    # 課結束前恰好剩 走路 ＋ 15 分鐘 → 還值得去；少一分鐘就不值得
    ends = "2026-09-24T16:10"
    enough = check(now="2026-09-24T15:45", place_text="遠", 遠=FAR_500M,
                   cur=current(end=ends))                  # 剩 25 = 10 + 15
    short = check(now="2026-09-24T15:46", place_text="遠", 遠=FAR_500M,
                  cur=current(end=ends))                   # 剩 24 = 10 + 14
    assert enough["remaining_minutes"] - walk == WORTH_ATTENDING_MINUTES
    assert enough["suggestion"] == "late"
    assert short["suggestion"] == "leave"


# ---- 即時位置（GPS）----

def test_gps_far_from_the_class_is_absent():
    r = check(lat=FAR_500M[0], lon=FAR_500M[1])
    assert r["here"]["source"] == "gps" and r["at_class"] is False


def test_gps_accuracy_widens_the_radius():
    # 200 公尺外：精度不明時半徑 120 → 不在；精度 ±250 公尺時半徑放寬 → 算在
    assert check(lat=NEAR_200M[0], lon=NEAR_200M[1])["at_class"] is False
    assert check(lat=NEAR_200M[0], lon=NEAR_200M[1], accuracy_m=250)["at_class"] is True


def test_gps_radius_never_exceeds_the_cap():
    # 精度差到 1000 公尺也不能無限放大：355 公尺外仍然不算在教室
    r = check(lat=NEAR_355M[0], lon=NEAR_355M[1], accuracy_m=1000)
    assert r["radius_m"] == MAX_RADIUS_METERS
    assert r["at_class"] is False


def test_typed_places_use_the_fixed_radius_regardless_of_accuracy():
    assert check(place_text="附近", accuracy_m=1000, 附近=NEAR_200M)["radius_m"] == AT_CLASS_RADIUS_METERS


def test_gps_wins_over_typed_place():
    r = check(place_text="成大圖書館", lat=NEAR_33M[0], lon=NEAR_33M[1], 成大圖書館=FAR_500M)
    assert r["here"]["source"] == "gps" and r["at_class"] is True


# ---- 沒辦法判斷時，明說而不是猜 ----

def test_no_current_class():
    r = check_attendance(None, at("2026-09-24T13:30"), place_text="成大圖書館")
    assert r["status"] == "no_class"


def test_no_location_is_not_treated_as_absent():
    # 還沒輸入位置的人，不能因此被判缺席
    r = check()
    assert r["status"] == "no_location"
    assert "at_class" not in r
    assert r["class"]["name"] == "人工智慧導論"


def test_blank_place_counts_as_no_location():
    assert check(place_text="   ")["status"] == "no_location"


def test_unknown_typed_place_is_reported():
    r = check(place_text="不存在的地方")
    assert r["status"] == "unknown_location" and "不存在的地方" in r["note"]


def test_unlocatable_classroom_is_reported():
    r = check(place_text="成大圖書館", 成大圖書館=FAR_500M,
              locate=lambda text, room="": {"status": "not_found"})
    assert r["status"] == "unavailable" and "資訊系館4264" in r["note"]


def test_unverified_classroom_position_is_flagged():
    unverified = {**CLASS_PLACE, "is_verified": False}
    r = check(place_text="成大圖書館", 成大圖書館=FAR_500M, locate=lambda t, room="": unverified)
    assert "Google" in r["note"]


def test_result_admits_it_only_knows_the_building():
    assert "分不出樓層" in check(place_text="資訊系館", 資訊系館=NEAR_33M)["note"]


# ---- 給 Agent 用的入口 ----

def _settings(path):
    return lambda: type("S", (), {"timezone": "Asia/Taipei", "class_schedule_path": str(path)})()


@pytest.fixture
def agent_world(tmp_path, monkeypatch):
    schedule = tmp_path / "s.json"
    schedule.write_text(json.dumps({"courses": [
        {"name": "數位IC設計", "day": "Monday", "start_time": "09:00", "end_time": "12:00",
         "location": "資訊系館4264"}]}), encoding="utf-8")
    state = {"now": "2026-09-21T10:00:00+08:00", "calls": []}

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(state["now"])

    monkeypatch.setattr(att, "load_settings", _settings(schedule))
    monkeypatch.setattr(att, "datetime", Frozen)
    monkeypatch.setattr(att, "check_attendance",
                        lambda cur, now, place_text="": state["calls"].append(
                            ((cur or {}).get("name"), place_text)) or {"status": "ok"})
    return state


def test_agent_entry_checks_the_class_in_session(agent_world):
    assert att.check_attendance_now("成大圖書館")["status"] == "ok"
    assert agent_world["calls"] == [("數位IC設計", "成大圖書館")]


def test_agent_entry_passes_no_class_when_nothing_is_in_session(agent_world):
    agent_world["now"] = "2026-09-21T08:00:00+08:00"          # 還沒上課
    att.check_attendance_now("成大圖書館")
    assert agent_world["calls"] == [(None, "成大圖書館")]


def test_agent_entry_reports_a_missing_schedule(tmp_path, monkeypatch):
    monkeypatch.setattr(att, "load_settings", _settings(tmp_path / "nope.json"))
    assert att.check_attendance_now("成大圖書館")["status"] == "error"
