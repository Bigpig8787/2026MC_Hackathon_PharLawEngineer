"""Timetable image -> commitments. Shell: owner C wires the Gemini Flash multimodal call."""
from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from campuspulse.ai.gemini import GeminiClient
from campuspulse.core.models import Commitment, Importance


class TimetableExtraction(BaseModel):
    commitments: list[Commitment] = Field(default_factory=list)
    confidence: float = 0.0
    notes: str = ""


PROMPT = (
    "這是一張台灣大學生的課表截圖。抽出每堂課的：課名、星期、開始時間、教室編號、建築名稱。"
    "教室編號通常是 3–4 位數字或字母加數字。若看不清楚，該欄位留空並降低 confidence。"
)


def extract_commitments(image_bytes: bytes, mime_type: str, client: GeminiClient, now: datetime) -> TimetableExtraction:
    if client.available and image_bytes:
        # TODO(live, owner C): build parts with types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
        # call client.generate_json(PROMPT, TimetableExtraction, parts=parts), then map building names to
        # campus building ids and next occurrence dates. Return that result instead of the fixture below.
        pass
    next_wed = now + timedelta(days=(2 - now.weekday()) % 7 or 7)
    start = next_wed.replace(hour=9, minute=0, second=0, microsecond=0)
    return TimetableExtraction(
        commitments=[Commitment(id="c-fixture-timetable", title="資料庫系統 小組報告", start=start, building_id="csie", room="4263", importance=Importance.high, source="timetable-fixture", confirmed=False)],
        confidence=0.0,
        notes="fixture: 課表辨識尚未接上（owner C）",
    )
