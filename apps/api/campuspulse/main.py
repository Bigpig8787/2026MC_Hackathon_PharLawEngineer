from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from campuspulse.api import routes_actions, routes_plan, routes_scenario, routes_state
from campuspulse.core.campus import Campus
from campuspulse.core.loop import AgentLoop
from campuspulse.providers.fixture_store import FixtureStore
from campuspulse.providers.registry import build_providers
from campuspulse.scenario.runner import SCENARIO_DIR, Scenario, ScenarioRunner
from campuspulse.settings import Settings, load_settings, missing_live_credentials

DEFAULT_SCENARIO = SCENARIO_DIR / "ncku-wed-0900.json"


def build_runner(settings: Settings, scenario_path: Path = DEFAULT_SCENARIO) -> ScenarioRunner:
    campus = Campus.load()
    store = FixtureStore()
    providers = build_providers(settings, store, campus)
    scenario = Scenario.load(scenario_path)
    loop = AgentLoop(campus, providers, scenario.commitment, scenario.origin, dry_run=settings.dry_run)
    runner = ScenarioRunner(scenario, loop, store)
    runner.reset()
    return runner


def create_app(settings: Settings | None = None, scenario_path: Path = DEFAULT_SCENARIO) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="CampusPulse API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = settings
    app.state.runner = build_runner(settings, scenario_path)

    @app.get("/api/health")
    def health() -> dict:
        return {
            "status": "ok",
            "provider_mode": settings.provider_mode,
            "dry_run": settings.dry_run,
            "missing_credentials": missing_live_credentials(settings),
            "providers": app.state.runner.loop.providers.modes(),
        }

    app.include_router(routes_state.router)
    app.include_router(routes_scenario.router)
    app.include_router(routes_actions.router)
    app.include_router(routes_plan.router)
    return app


app = create_app()
