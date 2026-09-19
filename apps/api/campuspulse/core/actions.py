"""Build previews for external actions. Never sends anything."""
from __future__ import annotations

from campuspulse.core.models import Commitment, Plan, Signal
from campuspulse.core.planner import MODE_LABEL

# Fixture recipients. C/E replace with contacts derived from course email.
DEFAULT_TO = ["ta@example.edu", "group-db-2026@example.edu"]


def disruption_summary(signals: dict[str, Signal]) -> str:
    parts: list[str] = []
    rain = signals.get("rain")
    if rain and max(float(rain.value.get("mm_per_hour", 0)), float(rain.value.get("forecast_next_hour_mm", 0))) >= 20:
        parts.append("豪雨")
    flood = signals.get("flood")
    if flood and any(a.get("level") in ("warning", "danger") for a in flood.value.get("alerts", [])):
        parts.append("道路積淹水")
    bike = signals.get("bike")
    if bike and int(bike.value.get("available", 1)) <= 0:
        parts.append("YouBike 無車")
    return "、".join(parts) or "交通狀況"


def build_late_email(commitment: Commitment, plan: Plan, signals: dict[str, Signal]) -> dict:
    when = commitment.start.strftime("%m/%d %H:%M")
    subject = f"[{commitment.title}] 可能遲到通知"
    cause = disruption_summary(signals)
    if plan.selected and plan.selected.arrive_at:
        arrive = plan.selected.arrive_at.strftime("%H:%M")
        late = max(0.0, -plan.selected.slack_min)
        body = (
            f"老師、助教、各位組員好：\n\n"
            f"{when} 的「{commitment.title}」（{commitment.room} 教室）因{cause}，"
            f"我已改{MODE_LABEL[plan.selected.mode]}前往，預計 {arrive} 抵達"
            f"{'' if late == 0 else f'，可能晚約 {late:.0f} 分鐘'}。\n\n"
            f"造成不便很抱歉，會盡快到。"
        )
    else:
        body = (
            f"老師、助教、各位組員好：\n\n"
            f"{when} 的「{commitment.title}」（{commitment.room} 教室）因{cause}，"
            f"目前所有交通方式都無法準時抵達。我會盡快趕到，若有需要請先開始。\n\n造成不便很抱歉。"
        )
    return {"to": list(DEFAULT_TO), "subject": subject, "body": body}
