"""Skill 層：產生給老師或助教的遲到通知信「草稿」。

只產生草稿，不寄出：內容由使用者確認、修改，再自己按 mailto 連結交給自己的郵件軟體，
或複製貼上。收件人、姓名都不預設，也不從任何地方讀個人資料——沒填就留成明顯的
【填寫】佔位，避免寄出一封署名空白或署錯名字的信。

全部是確定性的模板，沒有任何模型參與：這種信的價值在於準確與誠實
（幾點的課、預計晚多久），不需要也不該由模型自由發揮。
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote

SENDER_PLACEHOLDER = "【你的姓名／學號】"

# 原因由使用者自己填。請假、遲到的真正原因我們不知道，不能替他編一個（例如「生病」）
REASON_PLACEHOLDER = "【請填寫原因】"


def _mailto(recipient: str, subject: str, body: str) -> str:
    # 換行要用 CRLF，多數郵件軟體才會正確斷行；空白用 %20 而不是 +
    query = (f"subject={quote(subject, safe='')}"
             f"&body={quote(body.replace(chr(10), chr(13) + chr(10)), safe='')}")
    return f"mailto:{quote(recipient.strip(), safe='@,')}?{query}"


def build_late_notice(course_name: str, starts_at: str, late_minutes: int,
                      place: str = "", reason: str = "", recipient: str = "",
                      sender_name: str = "") -> dict:
    """產生遲到通知信草稿（不會寄出）。

    適用時機：判斷會遲到（課間轉場 late、或出發規劃 too_late）時，讓使用者一鍵
    產生給老師或助教的說明信，確認內容後由使用者自己寄出。

    Args:
        course_name: 課名。
        starts_at: 上課時間（ISO 格式）。
        late_minutes: 預計晚到幾分鐘；至少當作 1 分鐘。
        place: 上課地點，可留空。
        reason: 遲到原因，留空則寫「路程時間較預期長」。
        recipient: 收件人 email，預設留空由使用者填。
        sender_name: 署名，預設留成佔位文字，不代填。

    Returns:
        dict，包含 subject、body、mailto（可直接當連結）與提醒 note。
    """
    late = max(1, int(round(late_minutes)))
    start = datetime.fromisoformat(starts_at)
    clock = start.strftime("%H:%M")
    sender = (sender_name or "").strip() or SENDER_PLACEHOLDER
    why = (reason or "").strip() or "路程時間較預期長"
    where = f"（地點：{place.strip()}）" if (place or "").strip() else ""

    subject = f"【遲到通知】{course_name}（預計晚到約 {late} 分鐘）"
    body = (f"老師／助教您好，\n\n"
            f"我是修習「{course_name}」的學生。今天 {clock} 的課{where}，"
            f"因{why}，預計會晚到約 {late} 分鐘，先向您說明，造成不便敬請見諒。\n\n"
            f"我會盡快趕到教室。\n\n"
            f"敬上\n{sender}")

    return {
        "subject": subject,
        "body": body,
        "mailto": _mailto(recipient or "", subject, body),
        "late_minutes": late,
        "needs_sender": sender == SENDER_PLACEHOLDER,
        "needs_reason": REASON_PLACEHOLDER in why,
        "note": "這只是草稿，不會自動寄出。請確認內容、填入署名與收件人後，自己寄出。",
    }


def build_leave_notice(course_name: str, starts_at: str, place: str = "", reason: str = "",
                       recipient: str = "", sender_name: str = "") -> dict:
    """產生給老師或助教的請假通知信草稿（不會寄出）。

    適用時機：課已經開始、使用者不在教室，而且走過去也趕不上多少了，
    或使用者本來就沒打算去上課時。

    Args:
        course_name: 課名。
        starts_at: 上課時間（ISO 格式）。
        place: 上課地點，可留空。
        reason: 請假原因。留空則寫成【請填寫原因】佔位，不代替使用者編理由。
        recipient: 收件人 email，預設留空由使用者填。
        sender_name: 署名，預設留成佔位文字，不代填。

    Returns:
        dict，包含 subject、body、mailto、needs_sender、needs_reason 與提醒 note。
    """
    clock = datetime.fromisoformat(starts_at).strftime("%H:%M")
    sender = (sender_name or "").strip() or SENDER_PLACEHOLDER
    why = (reason or "").strip() or REASON_PLACEHOLDER
    where = f"（地點：{place.strip()}）" if (place or "").strip() else ""

    subject = f"【請假通知】{course_name}（{clock}）"
    body = (f"老師／助教您好，\n\n"
            f"我是修習「{course_name}」的學生。今天 {clock} 的課{where}，"
            f"因{why}，無法出席，特此向您請假，造成不便敬請見諒。\n\n"
            f"若有需要補交的作業或補充的資料，我會盡快處理，也請您告知。\n\n"
            f"敬上\n{sender}")

    return {
        "subject": subject,
        "body": body,
        "mailto": _mailto(recipient or "", subject, body),
        "needs_sender": sender == SENDER_PLACEHOLDER,
        "needs_reason": REASON_PLACEHOLDER in why,
        "note": "這只是草稿，不會自動寄出。請確認內容、填入原因與署名、收件人後，自己寄出。",
    }


def draft_late_notice(course_name: str, starts_at: str, late_minutes: int,
                      place: str = "", reason: str = "") -> dict:
    """給 Agent 用：產生遲到通知信草稿，回傳 subject 與 body 讓使用者確認。

    永遠只是草稿：不會寄信，轉述時要提醒使用者確認內容並自己寄出，
    不可以說「已經幫你寄出」。
    """
    return build_late_notice(course_name, starts_at, late_minutes, place, reason)


def draft_leave_notice(course_name: str, starts_at: str, place: str = "",
                       reason: str = "") -> dict:
    """給 Agent 用：產生請假通知信草稿，回傳 subject 與 body 讓使用者確認。

    永遠只是草稿：不會寄信，轉述時要提醒使用者填入原因與署名、確認後自己寄出，
    不可以說「已經幫你請假」。原因由使用者填，不可以替他編。
    """
    return build_leave_notice(course_name, starts_at, place, reason)
