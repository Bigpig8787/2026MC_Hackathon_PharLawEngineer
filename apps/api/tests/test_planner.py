from datetime import datetime, timedelta, timezone

import pytest

from campuspulse.core.campus import Campus
from campuspulse.core.models import Commitment, Importance, LatLng, Mode, PlanStatus, Signal
from campuspulse.core.planner import plan
from campuspulse.providers.routing.fixture import FixtureRoutingProvider

TPE = timezone(timedelta(hours=8))
START = datetime(2026, 9, 23, 9, 0, tzinfo=TPE)
ORIGIN = LatLng(lat=22.9905, lng=120.2280)
DEST = LatLng(lat=22.9997, lng=120.2220)


@pytest.fixture(scope="module")
def campus():
    return Campus.load()


def _routes(now):
    r = FixtureRoutingProvider()
    return {m: r.route(ORIGIN, DEST, m, now) for m in Mode}


def _signals(now, **over):
    base = {
        "rain": {"mm_per_hour": 0, "forecast_next_hour_mm": 0},
        "flood": {"alerts": []},
        "bike": {"origin_station_id": "yb-dongning", "available": 8, "dest_station_id": "yb-ncku-north", "docks": 5,
                 "next_station_id": "yb-ncku-east", "next_station_docks": 9},
        "transit": {"route_name": "5", "next_eta_min": 6, "board_stop_id": "bs-dongning", "alight_stop_id": "bs-ncku-north"},
        "parking": {"lots": {"lot-a": {"free": 12}, "lot-b": {"free": 30}, "lot-c": {"free": 5}}},
    }
    for k, v in over.items():
        base[k] = v
    return {k: Signal(kind=k, observed_at=now, value=v) for k, v in base.items()}


def _commitment(importance=Importance.high):
    return Commitment(id="c1", title="小組報告", start=START, building_id="csie", room="4263", importance=importance)


def test_baseline_selects_scooter_with_open_air_lot(campus):
    now = START - timedelta(minutes=70)
    p = plan(_commitment(), ORIGIN, now, _routes(now), _signals(now), campus)
    assert p.status == PlanStatus.ok
    assert p.selected.mode == Mode.scooter
    assert p.selected.last_decision.kind == "parking_lot" and p.selected.last_decision.target_id == "lot-a"
    assert all(o.feasible for o in p.options)
    assert p.selected.arrive_at <= START - timedelta(minutes=10)


def test_bike_zero_is_infeasible(campus):
    now = START - timedelta(minutes=70)
    sig = _signals(now)
    sig["bike"].value["available"] = 0
    p = plan(_commitment(), ORIGIN, now, _routes(now), sig, campus)
    bike = next(o for o in p.options if o.mode == Mode.bike)
    assert not bike.feasible and "no_bike" in bike.reasons


def test_heavy_rain_disqualifies_bike_and_prefers_covered_lot(campus):
    now = START - timedelta(minutes=45)
    sig = _signals(now, rain={"mm_per_hour": 25, "forecast_next_hour_mm": 30})
    p = plan(_commitment(), ORIGIN, now, _routes(now), sig, campus)
    bike = next(o for o in p.options if o.mode == Mode.bike)
    scooter = next(o for o in p.options if o.mode == Mode.scooter)
    assert "unsafe_heavy_rain" in bike.reasons
    assert scooter.last_decision.target_id == "lot-b"


def test_flood_reroutes_scooter_and_switches_to_transit_for_high_importance(campus):
    now = START - timedelta(minutes=45)  # 08:15
    sig = _signals(
        now,
        rain={"mm_per_hour": 25, "forecast_next_hour_mm": 30},
        flood={"alerts": [{"corridor_id": "xiaodong-rd", "level": "warning"}]},
        bike={"origin_station_id": "yb-dongning", "available": 0, "dest_station_id": "yb-ncku-north", "docks": 5,
              "next_station_id": "yb-ncku-east", "next_station_docks": 9},
        transit={"route_name": "5", "next_eta_min": 4, "board_stop_id": "bs-dongning", "alight_stop_id": "bs-ncku-north"},
        parking={"lots": {"lot-a": {"free": 0}, "lot-b": {"free": 30}, "lot-c": {"free": 5}}},
    )
    p = plan(_commitment(), ORIGIN, now, _routes(now), sig, campus)
    scooter = next(o for o in p.options if o.mode == Mode.scooter)
    walk = next(o for o in p.options if o.mode == Mode.walk)
    assert "rerouted" in scooter.risk_flags and scooter.route.corridor_ids == ["changrong-rd"]
    assert scooter.last_decision.target_id == "lot-b"
    assert not walk.feasible and "too_late" in walk.reasons
    assert p.selected.mode == Mode.transit
    assert p.selected.last_decision.kind == "bus_stop"


def test_bike_dock_full_moves_return_station(campus):
    now = START - timedelta(minutes=70)
    sig = _signals(now)
    sig["bike"].value["docks"] = 0
    p = plan(_commitment(), ORIGIN, now, _routes(now), sig, campus)
    bike = next(o for o in p.options if o.mode == Mode.bike)
    assert bike.last_decision.target_id == "yb-ncku-east"


def test_all_lots_full_makes_scooter_infeasible(campus):
    now = START - timedelta(minutes=70)
    sig = _signals(now, parking={"lots": {"lot-a": {"free": 0}, "lot-b": {"free": 0}, "lot-c": {"free": 0}}})
    p = plan(_commitment(), ORIGIN, now, _routes(now), sig, campus)
    scooter = next(o for o in p.options if o.mode == Mode.scooter)
    assert not scooter.feasible and "no_parking" in scooter.reasons


def test_late_risk_when_buffer_is_eaten(campus):
    now = START - timedelta(minutes=33)  # 08:27
    sig = _signals(
        now,
        rain={"mm_per_hour": 25, "forecast_next_hour_mm": 30},
        flood={"alerts": [{"corridor_id": "xiaodong-rd", "level": "warning"}]},
        bike={"origin_station_id": "yb-dongning", "available": 0, "dest_station_id": "yb-ncku-north", "docks": 5,
              "next_station_id": "yb-ncku-east", "next_station_docks": 9},
        transit={"route_name": "5", "next_eta_min": 3, "board_stop_id": "bs-dongning", "alight_stop_id": "bs-ncku-north"},
        parking={"lots": {"lot-a": {"free": 0}, "lot-b": {"free": 30}, "lot-c": {"free": 5}}},
    )
    p = plan(_commitment(), ORIGIN, now, _routes(now), sig, campus)
    assert p.status == PlanStatus.late_risk
    assert p.selected is not None and p.selected.on_time and not p.selected.feasible
    assert 0 < p.selected.slack_min < 10


def test_no_feasible_when_everything_is_too_late(campus):
    now = START - timedelta(minutes=5)
    p = plan(_commitment(), ORIGIN, now, _routes(now), _signals(now), campus)
    assert p.status == PlanStatus.no_feasible and p.selected is None


def test_normal_importance_prefers_time_over_reliability(campus):
    now = START - timedelta(minutes=70)
    p = plan(_commitment(Importance.normal), ORIGIN, now, _routes(now), _signals(now), campus)
    assert p.selected.mode == Mode.scooter
    assert p.selected.arrive_at <= START - timedelta(minutes=5)


def test_missing_rain_signal_flags_risk_not_crash(campus):
    now = START - timedelta(minutes=70)
    sig = _signals(now)
    del sig["rain"]
    p = plan(_commitment(), ORIGIN, now, _routes(now), sig, campus)
    assert "rain_unavailable" in p.selected.risk_flags


def test_arrived_state(campus):
    now = START - timedelta(minutes=10)
    p = plan(_commitment(), ORIGIN, now, _routes(now), _signals(now), campus, user_state="arrived_building")
    assert p.status == PlanStatus.arrived
