from __future__ import annotations

from campuspulse.core.campus import Campus
from campuspulse.core.models import IndoorGuidance, SourceMode
from campuspulse.providers.base import ProviderError


class FixtureIndoorProvider:
    source_mode = SourceMode.fixture

    def __init__(self, campus: Campus) -> None:
        self.campus = campus

    def locate(self, building_id: str, room: str) -> IndoorGuidance:
        r = self.campus.room(room)
        if r is None or r.building_id != building_id:
            raise ProviderError("unavailable", f"no fixture guidance for {building_id}/{room}")
        entrance = self.campus.entrance(building_id, r.entrance_id)
        return IndoorGuidance(
            building_id=building_id, room=room, floor=r.floor, wing=r.wing,
            entrance=entrance.name, instructions=r.instructions, source_mode=SourceMode.fixture,
        )
