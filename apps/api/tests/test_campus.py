from campuspulse.core.campus import Campus, walk_minutes
from campuspulse.core.models import LatLng


def test_campus_loads_and_resolves_room():
    campus = Campus.load()
    room = campus.room("4263")
    assert room is not None and room.building_id == "csie"
    entrance = campus.entrance("csie", room.entrance_id)
    assert entrance.name == "東側門"


def test_walk_to_building_uses_nearest_entrance():
    campus = Campus.load()
    lot_b = campus.lot("lot-b")
    entrance, minutes = campus.walk_to_building(lot_b.location, "csie")
    assert entrance.id == "csie-east"
    assert 0 < minutes < 10


def test_walk_minutes_is_distance_over_80m_per_min():
    a = LatLng(lat=23.0, lng=120.22)
    b = LatLng(lat=23.0, lng=120.2208)  # ~82 m east
    assert 0.9 < walk_minutes(a, b) < 1.2


def test_corridor_ids_in_text_matches_aliases():
    campus = Campus.load()
    assert campus.corridor_ids_in_text("Turn left onto 小東路 then Changrong Rd") == ["xiaodong-rd", "changrong-rd"]
