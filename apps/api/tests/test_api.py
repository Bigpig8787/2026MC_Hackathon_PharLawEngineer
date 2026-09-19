from fastapi.testclient import TestClient

from campuspulse.main import create_app
from campuspulse.settings import Settings


def _client():
    return TestClient(create_app(Settings(provider_mode="fixture")))


def test_state_after_startup_is_step_zero():
    c = _client()
    s = c.get("/api/state").json()
    assert s["step_index"] == 0 and s["plan"]["selected"]["mode"] == "scooter"


def test_scenario_step_and_reset():
    c = _client()
    assert c.post("/api/scenario/step").json()["plan"]["selected"]["mode"] == "transit"
    assert c.post("/api/scenario/reset").json()["step_index"] == 0


def test_inject_overrides_signal():
    c = _client()
    s = c.post("/api/scenario/inject", json={"bike": {"available": 0}}).json()
    assert next(o for o in s["plan"]["options"] if o["mode"] == "bike")["feasible"] is False


def test_confirm_action_is_dry_run():
    c = _client()
    c.post("/api/scenario/step"); s = c.post("/api/scenario/step").json()
    action_id = s["actions"][0]["id"]
    out = c.post(f"/api/actions/{action_id}/confirm").json()
    assert out["action"]["state"] == "executed_dry_run"
    assert c.post("/api/actions/nope/confirm").status_code == 404


def test_plan_endpoint_runs_planner_directly():
    c = _client()
    body = {
        "commitment": {"id": "x", "title": "普通課", "start": "2026-09-23T09:00:00+08:00", "building_id": "csie", "room": "4263", "importance": "normal"},
        "origin": {"lat": 22.9905, "lng": 120.2280},
        "now": "2026-09-23T07:50:00+08:00",
        "signals": {"rain": {"mm_per_hour": 0, "forecast_next_hour_mm": 0}, "flood": {"alerts": []},
                    "bike": {"origin_station_id": "yb-dongning", "available": 3, "dest_station_id": "yb-ncku-north", "docks": 2, "next_station_id": "yb-ncku-east", "next_station_docks": 9},
                    "transit": {"route_name": "5", "next_eta_min": 6, "board_stop_id": "bs-dongning", "alight_stop_id": "bs-ncku-north"},
                    "parking": {"lots": {"lot-a": {"free": 1}, "lot-b": {"free": 1}, "lot-c": {"free": 1}}}},
    }
    r = c.post("/api/plan", json=body)
    assert r.status_code == 200 and r.json()["status"] == "ok" and len(r.json()["options"]) == 4
