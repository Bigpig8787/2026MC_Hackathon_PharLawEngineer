"""class_transition Skill 測試：座標、課表與時間全由測試指定，不打網路也不看系統時鐘。"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from commute_agent.skills import class_transition
from commute_agent.skills.class_transition import (
    assess_transition,
    find_transition,
    plan_class_transition,
)
from commute_agent.tools.class_schedule import find_classes

TZ = ZoneInfo("Asia/Taipei")


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=TZ)


def iso(text: str) -> str:
    return at(text).isoformat(timespec="seconds")


def place(name, build_id, lat, lon, verified=True):
    return {"status": "ok", "name": name, "build_id": build_id, "lat": lat, "lon": lon,
            "is_verified": verified, "source": "gis_room_code"}


# 兩棟相距約 500 公尺：走路 round(500 × 1.3 ÷ 65) = 10 分、騎車 round(500 × 1.3 ÷ 250) = 3 分
PLACES = {
    "4264": place("B501 資訊工程系館", "B501", 23.0000, 120.2000),
    "4261": place("B501 資訊工程系館", "B501", 23.0000, 120.2000),   # 同一棟
    "7208": place("A006 唯農大樓", "A006", 23.0045, 120.2000),
    "5555": place("某棟大樓", "", 23.0045, 120.2000, verified=False),  # 只有 Google 的位置
}


def locate(location_text, room_query=""):
    return PLACES.get(room_query, {"status": "not_found", "name": "", "lat": None, "lon": None})


def entry(name, room, start, end):
    return {"name": name, "location": f"某館{room}", "room_query": room,
            "starts_at": iso(start), "ends_at": iso(end)}


def plan(next_start, now="2026-09-14T11:50", next_room="7208", next_name="日文（一）"):
    previous = entry("數位IC設計", "4264", "2026-09-14T09:00", "2026-09-14T12:00")
    upcoming = entry(next_name, next_room, next_start, "2026-09-14T15:00")
    return plan_class_transition(previous, upcoming, at(now), locate)


# ---- 判斷邊界 ----

def test_margin_of_exactly_five_minutes_is_comfortable():
    assert assess_transition(18, 10, 3)["verdict"] == "comfortable"   # 18 − 10 − 3 = 5


def test_zero_margin_is_tight_not_late():
    r = assess_transition(13, 10, 3)
    assert r["verdict"] == "tight"
    assert r["late_by"] == 0


def test_negative_margin_is_late_by_that_many_minutes():
    r = assess_transition(10, 10, 3)   # 10 − 10 − 3 = −3
    assert r["verdict"] == "late"
    assert r["late_by"] == 3


# ---- 課間轉場 ----

def test_plenty_of_time_between_classes():
    r = plan("2026-09-14T13:10")       # 下課後有 70 分鐘
    assert r["status"] == "ok"
    assert r["gap_minutes"] == 70
    assert r["walk_minutes"] == 10
    assert r["verdict"] == "comfortable"


def test_tight_when_gap_barely_covers_walk_and_buffer():
    r = plan("2026-09-14T12:15")       # 15 − 10 − 3 = 2
    assert r["verdict"] == "tight"
    assert "馬上出發" in r["advice"]


def test_late_suggests_bike_when_bike_makes_it():
    r = plan("2026-09-14T12:10")       # 走路 10 − 10 − 3 = −3；騎車 10 − 3 − 3 = 4
    assert r["verdict"] == "late"
    assert r["late_by"] == 3
    assert "自行車" in r["advice"]


def test_late_says_so_when_even_biking_is_too_slow():
    r = plan("2026-09-14T12:05")       # 走路 −8；騎車 5 − 3 − 3 = −1
    assert r["verdict"] == "late"
    assert "即使騎車也趕不上" in r["advice"]


def test_departure_is_now_when_previous_class_already_ended():
    # 12:05 已下課 5 分鐘，空檔要從「現在」算起，不是從 12:00 下課那一刻
    r = plan("2026-09-14T13:10", now="2026-09-14T12:05")
    assert r["gap_minutes"] == 65
    assert r["leaves_after"] == iso("2026-09-14T12:05")


def test_departure_waits_for_class_to_end_while_still_in_session():
    r = plan("2026-09-14T13:10", now="2026-09-14T11:00")
    assert r["leaves_after"] == iso("2026-09-14T12:00")
    assert r["gap_minutes"] == 70


def test_same_building_needs_no_walk():
    r = plan("2026-09-14T12:10", next_room="4261")
    assert r["same_building"] is True
    assert r["walk_minutes"] == 0
    assert r["verdict"] == "comfortable"      # 10 − 0 − 3 = 7
    assert "不必換棟" in r["advice"]


def test_exam_class_gets_a_longer_buffer():
    ordinary = plan("2026-09-14T13:10")
    exam = plan("2026-09-14T13:10", next_name="期中考")
    assert ordinary["buffer_minutes"] == 3
    assert exam["buffer_minutes"] == 13


def test_unknown_room_is_reported_not_guessed():
    r = plan("2026-09-14T13:10", next_room="9999")
    assert r["status"] == "unavailable"
    assert r["verdict"] is None
    assert "某館9999" in r["note"]
    assert "walk_minutes" not in r     # 沒有位置就不該有任何算出來的時間


def test_unverified_location_is_flagged():
    r = plan("2026-09-14T13:10", next_room="5555")
    assert r["status"] == "ok"
    assert "Google" in r["note"]


def test_result_is_always_marked_as_estimate():
    assert plan("2026-09-14T13:10")["is_estimate"] is True


# ---- 在課表裡找出轉場 ----

COURSES = [
    {"name": "數位IC設計", "day": "Monday", "day_zh": "星期一",
     "start_time": "09:00", "end_time": "12:00", "location": "資訊系館4264"},
    {"name": "日文（一）", "day": "Monday", "day_zh": "星期一",
     "start_time": "13:10", "end_time": "15:00", "location": "唯農大樓7208"},
    {"name": "統計學", "day": "Monday", "day_zh": "星期一",
     "start_time": "15:10", "end_time": "16:00", "location": "資訊系館4261"},
]


def test_transition_while_in_class_uses_current_class_as_the_origin():
    r = find_transition(COURSES, at("2026-09-14T14:00"), locate=locate)
    assert r["from"]["course"] == "日文（一）"
    assert r["to"]["course"] == "統計學"
    assert r["verdict"] == "late"             # 空檔 10 分，走路 10 ＋ 緩衝 3


def test_transition_right_after_class_uses_the_class_just_finished():
    r = find_transition(COURSES, at("2026-09-14T12:05"), locate=locate)
    assert r["from"]["course"] == "數位IC設計"
    assert r["to"]["course"] == "日文（一）"
    assert r["leaves_after"] == iso("2026-09-14T12:05")


def test_no_transition_once_the_break_is_long_over():
    # 下課 30 分鐘了，人不知道在哪，不能再假設他還在上一堂教室
    assert find_transition(COURSES, at("2026-09-14T12:30"), locate=locate) is None


def test_no_transition_before_the_first_class_of_the_day():
    assert find_transition(COURSES, at("2026-09-14T08:00"), locate=locate) is None


def test_no_transition_when_next_class_is_on_another_day():
    # 15:30 正在上當天最後一堂，下一堂已經是下週一
    assert find_transition(COURSES, at("2026-09-14T15:30"), locate=locate) is None


def test_no_transition_for_overlapping_classes():
    overlapping = [
        {"name": "A", "day": "Monday", "day_zh": "星期一",
         "start_time": "09:00", "end_time": "10:00", "location": "資訊系館4264"},
        {"name": "B", "day": "Monday", "day_zh": "星期一",
         "start_time": "09:30", "end_time": "11:00", "location": "唯農大樓7208"},
    ]
    assert find_transition(overlapping, at("2026-09-14T09:15"), locate=locate) is None


def test_no_transition_when_the_gap_is_a_long_free_period():
    spaced = [
        {"name": "A", "day": "Monday", "day_zh": "星期一",
         "start_time": "09:00", "end_time": "10:00", "location": "資訊系館4264"},
        {"name": "B", "day": "Monday", "day_zh": "星期一",
         "start_time": "14:00", "end_time": "15:00", "location": "唯農大樓7208"},
    ]
    assert find_transition(spaced, at("2026-09-14T09:30"), locate=locate) is None


def test_precomputed_classes_give_the_same_answer():
    now = at("2026-09-14T14:00")
    current, upcoming = find_classes(COURSES, now)
    reused = find_transition(COURSES, now, current, upcoming, locate)
    fresh = find_transition(COURSES, now, locate=locate)
    assert reused == fresh


# ---- 給 Agent 用的入口 ----

def _stub_settings(path):
    return lambda: type("S", (), {"timezone": "Asia/Taipei",
                                  "class_schedule_path": str(path)})()


def test_missing_schedule_file_is_an_error(monkeypatch, tmp_path):
    monkeypatch.setattr(class_transition, "load_settings", _stub_settings(tmp_path / "nope.json"))
    r = class_transition.plan_next_transition()
    assert r["status"] == "error"


def test_not_applicable_when_there_is_no_transition(monkeypatch, tmp_path):
    path = tmp_path / "s.json"
    path.write_text('{"courses": []}', encoding="utf-8")
    monkeypatch.setattr(class_transition, "load_settings", _stub_settings(path))
    monkeypatch.setattr(class_transition, "find_transition", lambda courses, now: None)
    assert class_transition.plan_next_transition()["status"] == "not_applicable"


def test_transition_result_is_passed_through(monkeypatch, tmp_path):
    path = tmp_path / "s.json"
    path.write_text('{"courses": []}', encoding="utf-8")
    monkeypatch.setattr(class_transition, "load_settings", _stub_settings(path))
    canned = {"status": "ok", "verdict": "tight"}
    monkeypatch.setattr(class_transition, "find_transition", lambda courses, now: canned)
    assert class_transition.plan_next_transition() is canned
