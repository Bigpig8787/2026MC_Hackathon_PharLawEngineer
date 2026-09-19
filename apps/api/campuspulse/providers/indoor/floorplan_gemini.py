"""TODO(live, owner D): 用 Gemini 讀樓層平面圖（data/ncku/floorplans/<building_id>/<floor>.png）。
輸入建築、教室編號、平面圖影像；輸出 IndoorGuidance（樓層、翼、入口、走法、confidence）。
confidence < 0.6 時改回 fixture 指引並標 source_mode=stale。
"""
from __future__ import annotations

from campuspulse.ai.gemini import GeminiClient
from campuspulse.core.campus import Campus
from campuspulse.core.models import IndoorGuidance, SourceMode
from campuspulse.providers.base import ProviderError


class FloorplanGeminiIndoorProvider:
    IMPLEMENTED = False
    source_mode = SourceMode.live

    def __init__(self, client: GeminiClient, campus: Campus) -> None:
        self.client = client
        self.campus = campus

    def locate(self, building_id: str, room: str) -> IndoorGuidance:
        raise ProviderError("not_implemented", "TODO(live, owner D): floor-plan guidance")
