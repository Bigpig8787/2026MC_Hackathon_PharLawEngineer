"""Two-sentence Chinese explanation of a plan. Model text is optional; the template is the contract."""
from __future__ import annotations

import json

from campuspulse.ai.gemini import GeminiClient
from campuspulse.core.models import Commitment, Plan, Trigger
from campuspulse.core.planner import MODE_LABEL, build_rationale

PROMPT = (
    "你是大學生的通勤助理。用繁體中文、最多兩句、不用技術名詞，向學生說明下面這個決策：先說該怎麼做，再說為什麼。"
    "只能根據給定資料，不可自己假設交通時間或天氣。\n\n決策資料：\n{payload}"
)


def _payload(plan: Plan, commitment: Commitment, triggers: list[Trigger]) -> str:
    s = plan.selected
    data = {
        "課程": commitment.title,
        "上課時間": commitment.start.strftime("%H:%M"),
        "重要度": commitment.importance.value,
        "狀態": plan.status.value,
        "建議": None if s is None else {
            "方式": MODE_LABEL[s.mode],
            "出門": s.depart_at.strftime("%H:%M") if s.depart_at else None,
            "到達": s.arrive_at.strftime("%H:%M") if s.arrive_at else None,
            "最後一個決定": s.last_decision.label if s.last_decision else None,
            "原因": s.last_decision.reason if s.last_decision else None,
            "緩衝分鐘": s.slack_min,
        },
        "其他方式": [{"方式": MODE_LABEL[o.mode], "可行": o.feasible, "原因": o.reasons} for o in plan.options if s is None or o.mode != s.mode],
        "剛發生的變化": [t.description for t in triggers],
    }
    return json.dumps(data, ensure_ascii=False)


def make_rationale_fn(client: GeminiClient):
    def fn(plan: Plan, commitment: Commitment, triggers: list[Trigger]) -> str:
        template = plan.rationale or build_rationale(plan, commitment)
        if not client.available:
            return template
        text = client.generate_text(PROMPT.format(payload=_payload(plan, commitment, triggers)))
        return text or template

    return fn
