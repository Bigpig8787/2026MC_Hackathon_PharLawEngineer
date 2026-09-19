"""Fixture clock. Drives the loop through a JSON timeline; inject() overrides signals at the current time."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from campuspulse.core.loop import AgentLoop
from campuspulse.core.models import Commitment, LatLng
from campuspulse.providers.fixture_store import FixtureStore
from campuspulse.settings import API_ROOT

SCENARIO_DIR = API_ROOT / "fixtures" / "scenarios"


class ScenarioStep(BaseModel):
    at: datetime
    user_state: str = "home"
    signals: dict[str, dict[str, Any]] = Field(default_factory=dict)
    note: str = ""


class Scenario(BaseModel):
    id: str
    title: str
    commitment: Commitment
    origin: LatLng
    steps: list[ScenarioStep]

    @classmethod
    def load(cls, path: Path) -> "Scenario":
        with path.open(encoding="utf-8") as f:
            return cls.model_validate(json.load(f))


class ScenarioRunner:
    def __init__(self, scenario: Scenario, loop: AgentLoop, store: FixtureStore) -> None:
        self.scenario = scenario
        self.loop = loop
        self.store = store
        self.index = -1

    def reset(self) -> dict[str, Any]:
        self.loop.reset()
        self.index = 0
        self._apply(self.scenario.steps[0])
        return self.snapshot()

    def step(self) -> dict[str, Any]:
        if self.index < 0:
            return self.reset()
        if self.index < len(self.scenario.steps) - 1:
            self.index += 1
            self._apply(self.scenario.steps[self.index])
        return self.snapshot()

    def inject(self, overrides: dict[str, dict[str, Any]]) -> dict[str, Any]:
        if self.index < 0:
            self.reset()
        for kind, patch in overrides.items():
            self.store.update(kind, patch)
        current = self.scenario.steps[self.index]
        self.loop.run(self.loop.clock or current.at, self.loop.user_state or current.user_state)
        return self.snapshot()

    def _apply(self, step: ScenarioStep) -> None:
        self.store.set_all(step.signals, step.at)
        self.loop.run(step.at, step.user_state)

    def snapshot(self) -> dict[str, Any]:
        snap = self.loop.snapshot()
        step = self.scenario.steps[self.index] if self.index >= 0 else None
        snap.update({
            "scenario_id": self.scenario.id,
            "scenario_title": self.scenario.title,
            "step_index": self.index,
            "step_count": len(self.scenario.steps),
            "step_note": step.note if step else "",
        })
        return snap
