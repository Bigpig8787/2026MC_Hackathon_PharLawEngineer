"""Typed domain models shared by planner, loop, providers and API."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Mode(str, Enum):
    walk = "walk"
    scooter = "scooter"
    bike = "bike"
    transit = "transit"


class SourceMode(str, Enum):
    live = "live"
    fixture = "fixture"
    stale = "stale"
    unavailable = "unavailable"


class Importance(str, Enum):
    normal = "normal"
    high = "high"
    critical = "critical"


class PlanStatus(str, Enum):
    ok = "ok"
    late_risk = "late_risk"
    no_feasible = "no_feasible"
    arrived = "arrived"


class LatLng(BaseModel):
    lat: float
    lng: float


class Commitment(BaseModel):
    id: str
    title: str
    start: datetime
    building_id: str
    room: str
    importance: Importance = Importance.normal
    source: str = "fixture"
    confirmed: bool = True


SignalKind = Literal["rain", "flood", "bike", "transit", "parking"]


class Signal(BaseModel):
    kind: SignalKind
    observed_at: datetime
    valid_until: Optional[datetime] = None
    value: dict[str, Any] = Field(default_factory=dict)
    source_mode: SourceMode = SourceMode.fixture
    confidence: float = 1.0


class RouteResult(BaseModel):
    mode: Mode
    duration_min: float
    distance_m: float
    polyline: list[LatLng] = Field(default_factory=list)
    summary: str = ""
    corridor_ids: list[str] = Field(default_factory=list)
    source_mode: SourceMode = SourceMode.fixture
    mode_proxy: Optional[str] = None
    alternative: Optional["RouteResult"] = None


class LastDecision(BaseModel):
    kind: Literal["parking_lot", "bike_dock", "bus_stop", "gate"]
    target_id: str
    label: str
    walk_min: float
    reason: str
    location: Optional[LatLng] = None


class TravelOption(BaseModel):
    mode: Mode
    route: Optional[RouteResult] = None
    last_decision: Optional[LastDecision] = None
    base_eta_min: float = 0.0
    conservative_eta_min: float = 0.0
    depart_at: Optional[datetime] = None
    arrive_at: Optional[datetime] = None
    feasible: bool = False
    on_time: bool = False
    slack_min: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    reliability: float = 0.0
    score: float = 0.0
    evidence: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    commitment_id: str
    generated_at: datetime
    selected: Optional[TravelOption] = None
    options: list[TravelOption] = Field(default_factory=list)
    rationale: str = ""
    next_check_at: Optional[datetime] = None
    status: PlanStatus = PlanStatus.ok
    policy_version: str = "0.1"
    decisions_made: int = 0


class Trigger(BaseModel):
    kind: str
    description: str
    old: Any = None
    new: Any = None
    observed_at: datetime
    material: bool = True


class ProposedAction(BaseModel):
    id: str
    type: Literal["email", "calendar"]
    preview: dict[str, Any]
    state: Literal["proposed", "confirmed", "rejected", "executed_dry_run"] = "proposed"
    created_at: datetime
    updated_at: Optional[datetime] = None


class TimelineEvent(BaseModel):
    at: datetime
    phase: Literal["perceive", "plan", "act", "reflect"]
    title: str
    detail: str = ""
    source_modes: list[str] = Field(default_factory=list)


class IndoorGuidance(BaseModel):
    building_id: str
    room: str
    floor: str
    wing: str
    entrance: str
    instructions: str
    source_mode: SourceMode = SourceMode.fixture
    confidence: float = 1.0
