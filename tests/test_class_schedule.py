"""class_schedule Tool 測試：純函式部分不讀檔、不看系統時鐘，時間一律由測試指定。"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from commute_agent.tools.class_schedule import (
    SchemaError,
    extract_room_query,
    find_classes,
    load_courses,
)

TZ = ZoneInfo("Asia/Taipei")

COURSES = [
    {"name": "數位IC設計", "day": "Monday", "day_zh": "星期一",
     "start_time": "09:00", "end_time": "12:00", "location": "資訊系館4264"},
    {"name": "日文（一）", "day": "Monday", "day_zh": "星期一",
     "start_time": "13:10", "end_time": "15:00", "location": "唯農大樓7208"},
    {"name": "全民國防", "day": "Friday", "day_zh": "星期五",
     "start_time": "15:20", "end_time": "17:10", "location": "軍訓館6021"},
]


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=TZ)


def test_room_code_extracted_from_location():
    assert extract_room_query("資訊系館4264") == "4264"
    assert extract_room_query("修齊大樓26302") == "26302"


def test_room_code_extracted_when_location_has_trailing_note():
    # 代碼後面還有「（視聽教室）」這類註記時，仍要抓到代碼本身
    assert extract_room_query("雲平大樓27103（視聽教室）") == "27103"


def test_room_query_empty_when_location_has_no_code():
    # 沒有數字代碼的地點，回空字串讓上層改用原字串處理，而不是硬湊一個錯的代碼
    assert extract_room_query("社科院大樓階梯教室－心理") == ""
    assert extract_room_query("資訊大樓格致廳小講堂") == ""


def test_next_class_is_the_upcoming_one_today():
    # 星期一早上 08:00，下一堂是 09:00 的數位IC設計
    current, nxt = find_classes(COURSES, at("2026-09-14T08:00"))
    assert current is None
    assert nxt["name"] == "數位IC設計"
    assert nxt["minutes_until_start"] == 60


def test_current_class_reported_while_in_session():
    # 星期一 10:00 正在上數位IC設計，下一堂是同一天下午的日文
    current, nxt = find_classes(COURSES, at("2026-09-14T10:00"))
    assert current["name"] == "數位IC設計"
    assert current["minutes_until_end"] == 120
    assert nxt["name"] == "日文（一）"


def test_next_class_wraps_to_following_week():
    # 星期五晚上已無課，下一堂應跨週末回到下星期一早上
    current, nxt = find_classes(COURSES, at("2026-09-18T20:00"))
    assert current is None
    assert nxt["name"] == "數位IC設計"
    assert nxt["starts_at"].startswith("2026-09-21")


def test_next_class_carries_room_query_for_lookup():
    _, nxt = find_classes(COURSES, at("2026-09-18T20:00"))
    assert nxt["room_query"] == "4264"
    assert nxt["location"] == "資訊系館4264"


def test_class_starting_exactly_now_counts_as_current_not_next():
    current, nxt = find_classes(COURSES, at("2026-09-14T09:00"))
    assert current["name"] == "數位IC設計"
    assert nxt["name"] == "日文（一）"


def test_unknown_weekday_is_rejected():
    bad = [{"name": "x", "day": "Funday", "start_time": "09:00",
            "end_time": "10:00", "location": "a"}]
    with pytest.raises(SchemaError):
        find_classes(bad, at("2026-09-14T08:00"))


def test_missing_field_is_rejected(tmp_path):
    path = tmp_path / "s.json"
    path.write_text('{"courses": [{"name": "x", "day": "Monday"}]}', encoding="utf-8")
    with pytest.raises(SchemaError):
        load_courses(path)


def test_missing_courses_array_is_rejected(tmp_path):
    path = tmp_path / "s.json"
    path.write_text('{"timezone": "Asia/Taipei"}', encoding="utf-8")
    with pytest.raises(SchemaError):
        load_courses(path)


def test_real_schedule_file_parses():
    from pathlib import Path

    from commute_agent.tools.class_schedule import PROJECT_ROOT

    courses = load_courses(PROJECT_ROOT / "data" / "class_schedule.json")
    assert len(courses) == 9
    assert all(c["day"] in
               ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday") for c in courses)
