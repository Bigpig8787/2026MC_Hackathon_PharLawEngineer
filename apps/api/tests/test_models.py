from datetime import datetime, timezone, timedelta

from campuspulse.core.models import (
    Commitment, Importance, LatLng, Mode, Plan, PlanStatus, RouteResult, SourceMode, TravelOption,
)

TPE = timezone(timedelta(hours=8))


def test_plan_round_trips_through_json():
    route = RouteResult(mode=Mode.scooter, duration_min=12, distance_m=3200, polyline=[LatLng(lat=22.99, lng=120.22)])
    opt = TravelOption(mode=Mode.scooter, route=route, feasible=True, on_time=True)
    plan = Plan(
        commitment_id="c1",
        generated_at=datetime(2026, 9, 23, 7, 50, tzinfo=TPE),
        selected=opt,
        options=[opt],
    )
    dumped = plan.model_dump_json()
    loaded = Plan.model_validate_json(dumped)
    assert loaded.selected.route.source_mode == SourceMode.fixture
    assert loaded.status == PlanStatus.ok
    assert loaded.policy_version == "0.1"


def test_commitment_defaults():
    c = Commitment(id="c1", title="小組報告", start=datetime(2026, 9, 23, 9, 0, tzinfo=TPE), building_id="csie", room="4263")
    assert c.importance == Importance.normal
    assert c.confirmed is True
