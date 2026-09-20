"""Skill 層：把課表匯出成行事曆——Google 日曆連結與 .ics 檔。

不走 Google Calendar API：那需要 OAuth 授權，等於把使用者的行事曆交給我們。
這裡只組出「使用者自己按下去」的東西：

- Google 日曆的新增事件網址（action=TEMPLATE）：點開後由使用者在 Google 端確認，
  才會真的加進他自己的日曆；
- 標準 .ics 檔：Google、Apple、Outlook 都能匯入。

兩者都不經過伺服器保存任何資料，全部是純函式。
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote, urlencode

TIMEZONE = "Asia/Taipei"

# 一學期約 18 週；學期起訖我們不知道，給個合理的重複次數，使用者匯入後可自行調整
DEFAULT_WEEKS = 18

WEEKDAY_INDEX = {"Monday": 0, "Tuesday": 1, "Wednesday": 2, "Thursday": 3,
                 "Friday": 4, "Saturday": 5, "Sunday": 6}

# iCalendar 建議每行不超過 75 個位元組（不含換行）
ICS_LINE_LIMIT = 75

# 台灣沒有夏令時間，時區定義只需要一段固定的 +08:00
VTIMEZONE = (
    "BEGIN:VTIMEZONE",
    f"TZID:{TIMEZONE}",
    "BEGIN:STANDARD",
    "DTSTART:19700101T000000",
    "TZOFFSETFROM:+0800",
    "TZOFFSETTO:+0800",
    "TZNAME:CST",
    "END:STANDARD",
    "END:VTIMEZONE",
)


def _stamp(moment: datetime) -> str:
    """20260921T090000：日曆用的本地時間格式，不帶時區，時區另外標。"""
    return moment.strftime("%Y%m%dT%H%M%S")


def build_google_calendar_url(name: str, starts_at: str, ends_at: str, location: str = "",
                              details: str = "", weeks: int = DEFAULT_WEEKS) -> str:
    """組出「加到 Google 日曆」的網址。

    Args:
        name: 事件標題（課名）。
        starts_at、ends_at: 第一次上課的起訖時間（ISO 格式，台北時間）。
        location、details: 地點與備註。
        weeks: 每週重複幾次；1 以下代表只加這一次。
    """
    start, end = datetime.fromisoformat(starts_at), datetime.fromisoformat(ends_at)
    params = {"action": "TEMPLATE", "text": name,
              "dates": f"{_stamp(start)}/{_stamp(end)}", "ctz": TIMEZONE}
    if location:
        params["location"] = location
    if details:
        params["details"] = details
    if weeks and weeks > 1:
        params["recur"] = f"RRULE:FREQ=WEEKLY;COUNT={weeks}"
    return "https://calendar.google.com/calendar/render?" + urlencode(params, quote_via=quote)


def first_occurrence(course: dict, today: date) -> tuple[datetime, datetime]:
    """這門課從 today 起（含當天）第一次上課的起訖時間，不含時區的本地時間。"""
    weekday = WEEKDAY_INDEX[course["day"]]
    day = today + timedelta(days=(weekday - today.weekday()) % 7)
    start_h, start_m = (int(p) for p in course["start_time"].split(":"))
    end_h, end_m = (int(p) for p in course["end_time"].split(":"))
    return (datetime.combine(day, time(start_h, start_m)),
            datetime.combine(day, time(end_h, end_m)))


def _escape(text: str) -> str:
    """iCalendar 文字值的跳脫：反斜線、分號、逗號與換行。"""
    return (text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\\n").replace("\n", "\\n"))


def _fold(line: str) -> list[str]:
    """把過長的行折成多行：每行最多 75 位元組，續行以一個空白開頭。

    以位元組計算而不是字元數——中文一字三位元組，照字元數折會超長；
    也不能從一個字中間切開，所以是逐字累加。
    """
    physical: list[str] = []
    current, size = "", 0
    for char in line:
        width = len(char.encode("utf-8"))
        if size + width > ICS_LINE_LIMIT:
            physical.append(current)
            current, size = " " + char, 1 + width
        else:
            current += char
            size += width
    physical.append(current)
    return physical


def _uid(course: dict) -> str:
    """同一門課永遠是同一個 UID，重複匯入時行事曆會更新而不是重複新增。"""
    key = "|".join(str(course.get(k, "")) for k in
                   ("name", "day", "start_time", "end_time", "location"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16] + "@ncku-smart-commute"


def build_ics(courses: list[dict], today: date, weeks: int = DEFAULT_WEEKS,
              now: datetime | None = None, calendar_name: str = "成大課表") -> str:
    """把整份課表組成一個 .ics 檔，每門課是每週重複的事件。

    Args:
        courses: 課表（class_schedule 的格式）。
        today: 用哪一天當基準找第一次上課；事件不會排在過去。
        weeks: 每週重複幾次。
        now: 建立時間（含時區），測試時指定；預設是現在。
    """
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stamp = moment.strftime("%Y%m%dT%H%M%SZ")

    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//NCKU Smart Commute//課表匯出//ZH",
             "CALSCALE:GREGORIAN", f"X-WR-CALNAME:{_escape(calendar_name)}",
             f"X-WR-TIMEZONE:{TIMEZONE}", *VTIMEZONE]

    for course in courses:
        start, end = first_occurrence(course, today)
        lines += ["BEGIN:VEVENT", f"UID:{_uid(course)}", f"DTSTAMP:{stamp}",
                  f"DTSTART;TZID={TIMEZONE}:{_stamp(start)}",
                  f"DTEND;TZID={TIMEZONE}:{_stamp(end)}"]
        if weeks and weeks > 1:
            lines.append(f"RRULE:FREQ=WEEKLY;COUNT={weeks}")
        lines.append(f"SUMMARY:{_escape(course['name'])}")
        if course.get("location"):
            lines.append(f"LOCATION:{_escape(course['location'])}")
        lines += ["DESCRIPTION:" + _escape("由成大智慧通勤匯出"), "END:VEVENT"]

    lines.append("END:VCALENDAR")
    return "\r\n".join(folded for line in lines for folded in _fold(line)) + "\r\n"
