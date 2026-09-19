"""Direct planner access so teammates can test their signals without the scenario."""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from campuspulse.core.models import Commitment, LatLng, Mode, Plan, Signal, SourceMode
from campuspulse.core.planner import plan as make_plan
from campuspulse.providers.base import ProviderError

router = APIRouter(prefix="/api", tags=["plan"])


class PlanRequest(BaseModel):
    commitment: Commitment
    origin: LatLng
    now: datetime
    signals: dict[str, dict[str, Any]] = Field(default_factory=dict)
    user_state: str = "home"


@router.post("/plan", response_model=Plan)
def post_plan(request: Request, body: PlanRequest) -> Plan:
    runner = request.app.state.runner
    campus, providers = runner.loop.campus, runner.loop.providers
    dest = campus.building(body.commitment.building_id).location
    routes = {}
    for mode in Mode:
        try:
            routes[mode] = providers.routing.route(body.origin, dest, mode, body.now)
        except ProviderError:
            routes[mode] = None
    signals = {k: Signal(kind=k, observed_at=body.now, value=v, source_mode=SourceMode.fixture) for k, v in body.signals.items()}  # type: ignore[arg-type]
    return make_plan(body.commitment, body.origin, body.now, routes, signals, campus, body.user_state)
