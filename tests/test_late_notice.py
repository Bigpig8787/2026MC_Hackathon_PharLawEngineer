"""late_notice 測試：純模板，不寄信、不讀任何個人資料。"""
from urllib.parse import parse_qs, urlparse

from commute_agent.skills.late_notice import (
    REASON_PLACEHOLDER,
    SENDER_PLACEHOLDER,
    build_late_notice,
    build_leave_notice,
    draft_late_notice,
    draft_leave_notice,
)

STARTS = "2026-09-21T09:00:00+08:00"


def notice(**kwargs):
    args = {"course_name": "數位IC設計", "starts_at": STARTS, "late_minutes": 10}
    return build_late_notice(**{**args, **kwargs})


def test_subject_and_body_state_the_course_time_and_delay():
    n = notice(place="B501 資訊工程系館")
    assert "數位IC設計" in n["subject"] and "10 分鐘" in n["subject"]
    assert "09:00" in n["body"] and "晚到約 10 分鐘" in n["body"]
    assert "B501 資訊工程系館" in n["body"]


def test_default_reason_is_the_honest_generic_one():
    assert "路程時間較預期長" in notice()["body"]


def test_custom_reason_replaces_the_default():
    body = notice(reason="公車誤點")["body"]
    assert "公車誤點" in body and "路程時間較預期長" not in body


def test_sender_is_never_filled_in_for_the_student():
    n = notice()
    assert SENDER_PLACEHOLDER in n["body"]
    assert n["needs_sender"] is True


def test_sender_name_is_used_when_given():
    n = notice(sender_name="王大帥")
    assert n["body"].endswith("王大帥") and n["needs_sender"] is False


def test_delay_is_at_least_one_minute_and_rounded():
    assert notice(late_minutes=0)["late_minutes"] == 1
    assert notice(late_minutes=2.6)["late_minutes"] == 3


def test_place_is_left_out_when_unknown():
    assert "地點" not in notice()["body"]


def test_mailto_without_recipient_leaves_it_for_the_user():
    assert notice()["mailto"].startswith("mailto:?subject=")


def test_mailto_with_recipient():
    assert notice(recipient="prof@example.edu")["mailto"].startswith("mailto:prof@example.edu?")


def test_mailto_round_trips_subject_and_body():
    n = notice()
    q = parse_qs(urlparse(n["mailto"]).query)
    assert q["subject"][0] == n["subject"]
    # 郵件軟體要 CRLF 換行才會正確斷行
    assert q["body"][0] == n["body"].replace("\n", "\r\n")


def test_mailto_has_no_raw_spaces_or_newlines():
    link = notice()["mailto"]
    assert " " not in link and "\n" not in link and "\r" not in link


def test_it_is_only_a_draft():
    assert "不會自動寄出" in notice()["note"]


def test_agent_wrapper_gives_the_same_draft():
    n = draft_late_notice("數位IC設計", STARTS, 10, place="B501")
    assert n["subject"] == notice(place="B501")["subject"]


def test_generic_late_reason_does_not_ask_the_student_to_fill_one_in():
    assert notice()["needs_reason"] is False


def test_late_notice_can_leave_the_reason_for_the_student_to_fill_in():
    n = notice(reason=REASON_PLACEHOLDER)
    assert n["needs_reason"] is True and REASON_PLACEHOLDER in n["body"]


# ---- 請假信 ----

def leave(**kwargs):
    args = {"course_name": "人工智慧導論", "starts_at": STARTS}
    return build_leave_notice(**{**args, **kwargs})


def test_leave_notice_states_the_course_and_time():
    n = leave(place="B501 資訊工程系館")
    assert "請假" in n["subject"] and "人工智慧導論" in n["subject"]
    assert "09:00" in n["body"] and "無法出席" in n["body"]
    assert "B501 資訊工程系館" in n["body"]


def test_leave_reason_is_never_invented():
    # 請假的真正原因我們不知道，不能替學生編一個（例如「身體不適」）
    n = leave()
    assert REASON_PLACEHOLDER in n["body"]
    assert n["needs_reason"] is True
    assert "生病" not in n["body"] and "不適" not in n["body"]


def test_leave_notice_uses_the_reason_the_student_gives():
    n = leave(reason="臨時有急事")
    assert "臨時有急事" in n["body"] and REASON_PLACEHOLDER not in n["body"]
    assert n["needs_reason"] is False


def test_leave_notice_does_not_fill_in_the_sender():
    n = leave()
    assert SENDER_PLACEHOLDER in n["body"] and n["needs_sender"] is True
    assert leave(sender_name="王大帥")["body"].endswith("王大帥")


def test_leave_mailto_round_trips_subject_and_body():
    n = leave(recipient="prof@example.edu")
    assert n["mailto"].startswith("mailto:prof@example.edu?")
    q = parse_qs(urlparse(n["mailto"]).query)
    assert q["subject"][0] == n["subject"]
    assert q["body"][0] == n["body"].replace("\n", "\r\n")


def test_leave_notice_is_only_a_draft():
    assert "不會自動寄出" in leave()["note"]


def test_agent_wrapper_gives_a_leave_draft():
    assert draft_leave_notice("人工智慧導論", STARTS)["subject"] == leave()["subject"]
