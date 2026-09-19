"""calendar_export 測試：全是純函式，時間由測試指定。"""
from datetime import date, datetime
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

from commute_agent.skills.calendar_export import (
    DEFAULT_WEEKS,
    ICS_LINE_LIMIT,
    _fold,
    build_google_calendar_url,
    build_ics,
    first_occurrence,
)

COURSES = [
    {"name": "數位IC設計", "day": "Monday", "start_time": "09:00", "end_time": "12:00",
     "location": "資訊系館4264"},
    {"name": "日文（一）", "day": "Monday", "start_time": "13:10", "end_time": "15:00",
     "location": "唯農大樓7208"},
    {"name": "全民國防", "day": "Friday", "start_time": "15:20", "end_time": "17:10",
     "location": "軍訓館6021"},
]
WEDNESDAY = date(2026, 9, 16)
NOW = datetime(2026, 9, 20, 1, 0, tzinfo=ZoneInfo("Asia/Taipei"))


def unfold(text: str) -> str:
    return text.replace("\r\n ", "")


def ics(**kwargs):
    return build_ics(COURSES, WEDNESDAY, now=NOW, **kwargs)


# ---- Google 日曆連結 ----

def query(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_google_url_carries_title_dates_timezone_and_location():
    url = build_google_calendar_url("數位IC設計", "2026-09-21T09:00:00+08:00",
                                    "2026-09-21T12:00:00+08:00", location="B501 資訊工程系館")
    assert urlparse(url).netloc == "calendar.google.com"
    q = query(url)
    assert q["action"] == "TEMPLATE"
    assert q["text"] == "數位IC設計"
    assert q["dates"] == "20260921T090000/20260921T120000"
    assert q["ctz"] == "Asia/Taipei"
    assert q["location"] == "B501 資訊工程系館"


def test_google_url_repeats_weekly_by_default():
    q = query(build_google_calendar_url("課", "2026-09-21T09:00:00+08:00", "2026-09-21T10:00:00+08:00"))
    assert q["recur"] == f"RRULE:FREQ=WEEKLY;COUNT={DEFAULT_WEEKS}"


def test_google_url_can_add_a_single_event():
    q = query(build_google_calendar_url("課", "2026-09-21T09:00:00+08:00",
                                        "2026-09-21T10:00:00+08:00", weeks=1))
    assert "recur" not in q


def test_google_url_leaves_out_empty_optional_fields():
    q = query(build_google_calendar_url("課", "2026-09-21T09:00:00+08:00", "2026-09-21T10:00:00+08:00"))
    assert "location" not in q and "details" not in q


# ---- 第一次上課的日期 ----

def test_first_occurrence_is_the_next_matching_weekday():
    start, end = first_occurrence(COURSES[0], WEDNESDAY)      # 週三問週一的課 → 下週一
    assert start == datetime(2026, 9, 21, 9, 0) and end == datetime(2026, 9, 21, 12, 0)


def test_first_occurrence_includes_today():
    start, _ = first_occurrence(COURSES[0], date(2026, 9, 21))
    assert start.date() == date(2026, 9, 21)


def test_first_occurrence_is_never_in_the_past():
    # 週六問週五的課 → 下週五，不是昨天
    start, _ = first_occurrence(COURSES[2], date(2026, 9, 19))
    assert start.date() == date(2026, 9, 25)


# ---- .ics ----

def test_ics_is_a_wellformed_calendar_with_one_event_per_course():
    text = unfold(ics())
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "VERSION:2.0" in text
    assert text.count("BEGIN:VEVENT") == text.count("END:VEVENT") == len(COURSES)


def test_ics_uses_crlf_line_endings_only():
    text = ics()
    assert "\n" not in text.replace("\r\n", "")


def test_ics_events_carry_timezone_and_weekly_recurrence():
    text = unfold(ics())
    assert "DTSTART;TZID=Asia/Taipei:20260921T090000" in text
    assert "DTEND;TZID=Asia/Taipei:20260921T120000" in text
    assert f"RRULE:FREQ=WEEKLY;COUNT={DEFAULT_WEEKS}" in text
    assert "TZID:Asia/Taipei" in text and "TZOFFSETTO:+0800" in text


def test_ics_can_be_a_single_occurrence():
    assert "RRULE" not in ics(weeks=1)


def test_ics_timestamp_is_utc_from_the_given_moment():
    assert "DTSTAMP:20260919T170000Z" in ics()


def test_uid_is_stable_across_exports_and_unique_per_course():
    first = [l for l in unfold(ics()).split("\r\n") if l.startswith("UID:")]
    again = [l for l in unfold(ics()).split("\r\n") if l.startswith("UID:")]
    assert first == again
    assert len(set(first)) == len(COURSES)


def test_special_characters_in_text_are_escaped():
    odd = [{"name": "A,B;C\\D", "day": "Monday", "start_time": "09:00", "end_time": "10:00",
            "location": "甲棟\n乙"}]
    text = unfold(build_ics(odd, WEDNESDAY, now=NOW))
    assert "SUMMARY:A\\,B\\;C\\\\D" in text
    assert "LOCATION:甲棟\\n乙" in text


def test_no_physical_line_exceeds_75_bytes():
    long_location = [{"name": "課", "day": "Monday", "start_time": "09:00", "end_time": "10:00",
                      "location": "很長的地點名稱" * 12}]
    text = build_ics(long_location, WEDNESDAY, now=NOW)
    assert all(len(line.encode("utf-8")) <= ICS_LINE_LIMIT for line in text.split("\r\n"))


def test_folding_never_splits_a_character_and_unfolds_back():
    original = "SUMMARY:" + "中文課程名稱" * 20
    folded = _fold(original)
    assert len(folded) > 1
    assert all(len(part.encode("utf-8")) <= ICS_LINE_LIMIT for part in folded)
    assert all(part.startswith(" ") for part in folded[1:])
    assert "".join(folded[:1] + [p[1:] for p in folded[1:]]) == original
