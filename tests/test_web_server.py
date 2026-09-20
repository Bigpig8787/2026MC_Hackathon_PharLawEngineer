from web import server


def _room_result(building_name="A006 唯農大樓", floor="2F"):
    return {
        "status": "ok",
        "candidates": [{
            "building_name": building_name,
            "floor": floor,
            "exact_match": True,
        }],
    }


def test_room_only_location_is_not_marked_as_corrected(monkeypatch):
    monkeypatch.setattr(server, "lookup_room", lambda query: _room_result())

    result = server._resolve_building({
        "location": "共同教室-A1302",
        "room_query": "A1302",
    })

    assert result["building_name"] == "A006 唯農大樓"
    assert result["floor"] == "2F"
    assert result["corrected"] is False


def test_explicit_wrong_building_is_marked_as_corrected(monkeypatch):
    monkeypatch.setattr(server, "lookup_room", lambda query: _room_result())

    result = server._resolve_building({
        "location": "B501 資訊工程系館 A1302",
        "room_query": "A1302",
    })

    assert result["corrected"] is True
