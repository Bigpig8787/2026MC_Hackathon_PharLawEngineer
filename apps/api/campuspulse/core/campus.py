"""NCKU campus reference data: buildings, entrances, parking, stations, corridors."""
from __future__ import annotations

import json
import math
from pathlib import Path

from pydantic import BaseModel, Field

from campuspulse.core.models import LatLng
from campuspulse.settings import API_ROOT

DATA_DIR = API_ROOT / "data" / "ncku"
WALK_M_PER_MIN = 80.0


class Entrance(BaseModel):
    id: str
    name: str
    location: LatLng


class Building(BaseModel):
    id: str
    name: str
    campus: str
    location: LatLng
    entrances: list[Entrance] = Field(default_factory=list)
    verified: bool = False


class ParkingLot(BaseModel):
    id: str
    name: str
    location: LatLng
    covered: bool
    capacity: int
    verified: bool = False


class Room(BaseModel):
    room: str
    building_id: str
    floor: str
    wing: str
    entrance_id: str
    instructions: str
    verified: bool = False


class Station(BaseModel):
    id: str
    name: str
    location: LatLng
    verified: bool = False


class Corridor(BaseModel):
    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)


def haversine_m(a: LatLng, b: LatLng) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dp = p2 - p1
    dl = math.radians(b.lng - a.lng)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def walk_minutes(a: LatLng, b: LatLng) -> float:
    return round(haversine_m(a, b) / WALK_M_PER_MIN, 1)


def _read(path: Path, key: str) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)[key]


class Campus:
    def __init__(
        self,
        buildings: list[Building],
        lots: list[ParkingLot],
        rooms: list[Room],
        bike_stations: list[Station],
        bus_stops: list[Station],
        corridors: list[Corridor],
    ) -> None:
        self._buildings = {b.id: b for b in buildings}
        self.lots = lots
        self._lots = {lot.id: lot for lot in lots}
        self._rooms = {r.room: r for r in rooms}
        self._bike = {s.id: s for s in bike_stations}
        self._bus = {s.id: s for s in bus_stops}
        self.corridors = corridors

    @classmethod
    def load(cls, data_dir: Path = DATA_DIR) -> "Campus":
        return cls(
            buildings=[Building(**b) for b in _read(data_dir / "buildings.json", "buildings")],
            lots=[ParkingLot(**p) for p in _read(data_dir / "parking_lots.json", "lots")],
            rooms=[Room(**r) for r in _read(data_dir / "rooms.json", "rooms")],
            bike_stations=[Station(**s) for s in _read(data_dir / "bike_stations.json", "stations")],
            bus_stops=[Station(**s) for s in _read(data_dir / "bus_stops.json", "stops")],
            corridors=[Corridor(**c) for c in _read(data_dir / "corridors.json", "corridors")],
        )

    @property
    def buildings(self) -> list[Building]:
        return list(self._buildings.values())

    def building(self, building_id: str) -> Building:
        return self._buildings[building_id]

    def room(self, room: str) -> Room | None:
        return self._rooms.get(room)

    def entrance(self, building_id: str, entrance_id: str) -> Entrance:
        for e in self.building(building_id).entrances:
            if e.id == entrance_id:
                return e
        raise KeyError(entrance_id)

    def nearest_entrance(self, building_id: str, point: LatLng) -> Entrance:
        b = self.building(building_id)
        if not b.entrances:
            return Entrance(id=f"{b.id}-main", name="正門", location=b.location)
        return min(b.entrances, key=lambda e: haversine_m(point, e.location))

    def walk_to_building(self, point: LatLng, building_id: str) -> tuple[Entrance, float]:
        e = self.nearest_entrance(building_id, point)
        return e, walk_minutes(point, e.location)

    def lot(self, lot_id: str) -> ParkingLot:
        return self._lots[lot_id]

    def bike_station(self, station_id: str) -> Station:
        return self._bike[station_id]

    def bus_stop(self, stop_id: str) -> Station:
        return self._bus[stop_id]

    def corridor_ids_in_text(self, text: str) -> list[str]:
        found: list[tuple[int, str]] = []
        for c in self.corridors:
            positions = [text.find(a) for a in c.aliases if a in text]
            if positions:
                found.append((min(positions), c.id))
        return [cid for _, cid in sorted(found)]
