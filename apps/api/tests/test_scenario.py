from campuspulse.core.campus import Campus
from campuspulse.core.loop import AgentLoop
from campuspulse.providers.fixture_store import FixtureStore
from campuspulse.providers.registry import build_providers
from campuspulse.scenario.runner import SCENARIO_DIR, Scenario, ScenarioRunner
from campuspulse.settings import Settings


def _runner():
    campus = Campus.load()
    store = FixtureStore()
    providers = build_providers(Settings(provider_mode="fixture"), store, campus)
    scenario = Scenario.load(SCENARIO_DIR / "ncku-wed-0900.json")
    loop = AgentLoop(campus, providers, scenario.commitment, scenario.origin)
    return ScenarioRunner(scenario, loop, store)


def test_reset_produces_initial_scooter_plan_with_full_loop_timeline():
    r = _runner()
    s = r.reset()
    assert s["step_index"] == 0 and s["plan"]["selected"]["mode"] == "scooter"
    assert {e["phase"] for e in s["timeline"]} == {"perceive", "plan", "act", "reflect"}
    assert s["decisions"]["agent"] > 0 and s["decisions"]["user"] == 0
    assert s["providers"]["routing"] == "fixture"


def test_step_one_switches_to_transit_and_records_material_triggers():
    r = _runner()
    r.reset()
    before = r.snapshot()["decisions"]["agent"]
    s = r.step()
    assert s["plan"]["selected"]["mode"] == "transit"
    kinds = {t["kind"] for t in s["triggers"] if t["material"]}
    assert "selected_mode_changed" in kinds and "feasibility_flip" in kinds
    assert s["decisions"]["agent"] > before
    scooter = next(o for o in s["plan"]["options"] if o["mode"] == "scooter")
    assert scooter["last_decision"]["target_id"] == "lot-b" and "rerouted" in scooter["risk_flags"]


def test_step_two_is_late_risk_and_proposes_email_once():
    r = _runner()
    r.reset(); r.step()
    s = r.step()
    assert s["plan"]["status"] == "late_risk"
    assert len(s["actions"]) == 1 and s["actions"][0]["type"] == "email" and s["actions"][0]["state"] == "proposed"
    assert "4263" in s["actions"][0]["preview"]["body"]
    s = r.inject({"transit": {"next_eta_min": 3}})
    assert len(s["actions"]) == 1  # no duplicate proposal


def test_confirm_is_dry_run_and_counts_user_decision():
    r = _runner()
    r.reset(); r.step(); r.step()
    action_id = r.snapshot()["actions"][0]["id"]
    r.loop.confirm_action(action_id, r.loop.clock)
    s = r.snapshot()
    assert s["actions"][0]["state"] == "executed_dry_run" and s["decisions"]["user"] == 1


def test_step_three_arrived_shows_indoor_card():
    r = _runner()
    r.reset(); r.step(); r.step()
    s = r.step()
    assert s["plan"]["status"] == "arrived"
    assert s["indoor"]["floor"] == "4F" and s["indoor"]["entrance"] == "東側門"
    assert r.step()["step_index"] == 3  # stays on last step


def test_inject_bike_zero_flips_bike_feasibility():
    r = _runner()
    r.reset()
    s = r.inject({"bike": {"available": 0}})
    bike = next(o for o in s["plan"]["options"] if o["mode"] == "bike")
    assert bike["feasible"] is False
    assert any(t["kind"] == "feasibility_flip" for t in s["triggers"])
