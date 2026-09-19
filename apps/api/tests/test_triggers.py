from datetime import datetime, timedelta, timezone

from campuspulse.core.models import Mode, Plan, PlanStatus, TravelOption, Trigger
from campuspulse.core.triggers import apply_cooldown, detect_triggers

TPE = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 23, 8, 15, tzinfo=TPE)


def _opt(mode, feasible=True, depart=NOW, eta=20.0, risks=None):
    return TravelOption(mode=mode, feasible=feasible, on_time=feasible, depart_at=depart, arrive_at=depart + timedelta(minutes=eta),
                        conservative_eta_min=eta, risk_flags=risks or [])


def _plan(selected, options, status=PlanStatus.ok):
    return Plan(commitment_id="c1", generated_at=NOW, selected=selected, options=options, status=status)


def test_initial_plan_is_single_material_trigger():
    p = _plan(_opt(Mode.scooter), [_opt(Mode.scooter)])
    t = detect_triggers(None, p, NOW)
    assert [x.kind for x in t] == ["initial_plan"] and t[0].material


def test_feasibility_flip_and_mode_change_are_material():
    old = _plan(_opt(Mode.scooter), [_opt(Mode.scooter), _opt(Mode.bike)])
    new = _plan(_opt(Mode.transit), [_opt(Mode.transit), _opt(Mode.scooter), _opt(Mode.bike, feasible=False)])
    kinds = {t.kind for t in detect_triggers(old, new, NOW) if t.material}
    assert {"feasibility_flip", "selected_mode_changed"} <= kinds


def test_small_eta_drift_is_not_material():
    old = _plan(_opt(Mode.scooter, eta=20), [_opt(Mode.scooter, eta=20)])
    new = _plan(_opt(Mode.scooter, eta=22), [_opt(Mode.scooter, eta=22)])
    t = detect_triggers(old, new, NOW)
    assert all(not x.material for x in t)


def test_big_eta_increase_and_earlier_departure_are_material():
    old = _plan(_opt(Mode.scooter, eta=20, depart=NOW + timedelta(minutes=20)), [_opt(Mode.scooter, eta=20)])
    new = _plan(_opt(Mode.scooter, eta=27, depart=NOW + timedelta(minutes=13)), [_opt(Mode.scooter, eta=27)])
    kinds = {t.kind for t in detect_triggers(old, new, NOW) if t.material}
    assert {"eta_increase", "depart_earlier"} <= kinds


def test_cooldown_suppresses_repeat_but_not_flip():
    history = [Trigger(kind="eta_increase", description="", observed_at=NOW - timedelta(minutes=2))]
    fresh = [
        Trigger(kind="eta_increase", description="", observed_at=NOW),
        Trigger(kind="feasibility_flip", description="", observed_at=NOW),
    ]
    out = apply_cooldown(fresh, history, NOW)
    assert out[0].material is False and out[1].material is True
