"""Perceive → plan → act → reflect. Deterministic code owns authorization and state; models only explain."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Callable

from campuspulse.core.actions import build_late_email
from campuspulse.core.campus import Campus
from campuspulse.core.models import (
    Commitment, IndoorGuidance, LatLng, Mode, Plan, PlanStatus, ProposedAction, RouteResult, Signal, SourceMode,
    TimelineEvent, Trigger,
)
from campuspulse.core.planner import MODE_LABEL, plan as make_plan
from campuspulse.core.triggers import apply_cooldown, detect_triggers
from campuspulse.providers.base import ProviderError
from campuspulse.providers.registry import Providers

RationaleFn = Callable[[Plan, Commitment, list[Trigger]], str]


class AgentLoop:
    def __init__(
        self, campus: Campus, providers: Providers, commitment: Commitment, origin: LatLng,
        rationale_fn: RationaleFn | None = None, dry_run: bool = True,
    ) -> None:
        self.campus = campus
        self.providers = providers
        self.commitment = commitment
        self.origin = origin
        self.rationale_fn = rationale_fn
        self.dry_run = dry_run
        self.reset()

    def reset(self) -> None:
        self.plan: Plan | None = None
        self.timeline: list[TimelineEvent] = []
        self.actions: list[ProposedAction] = []
        self.trigger_history: list[Trigger] = []
        self.last_triggers: list[Trigger] = []
        self.signals: dict[str, Signal] = {}
        self.routes: dict[Mode, RouteResult | None] = {}
        self.indoor: IndoorGuidance | None = None
        self.decisions_agent = 0
        self.decisions_user = 0
        self.clock: datetime | None = None
        self.user_state = "home"

    # ---- loop -----------------------------------------------------------------

    def run(self, now: datetime, user_state: str) -> None:
        self.clock = now
        self.user_state = user_state
        self._perceive(now)
        new_plan, triggers = self._plan(now, user_state)
        self._act(now, new_plan, triggers, user_state)
        self._reflect(now, user_state)

    def _perceive(self, now: datetime) -> None:
        signals: dict[str, Signal] = {}
        for kind, provider in self.providers.signals.items():
            try:
                signals[kind] = provider.fetch(now, {"commitment": self.commitment.model_dump(mode="json")})
            except ProviderError as e:
                signals[kind] = Signal(kind=kind, observed_at=now, value={}, source_mode=SourceMode.unavailable, confidence=0.0)  # type: ignore[arg-type]
        dest = self.campus.building(self.commitment.building_id).location
        routes: dict[Mode, RouteResult | None] = {}
        for mode in Mode:
            try:
                routes[mode] = self.providers.routing.route(self.origin, dest, mode, now)
            except ProviderError:
                routes[mode] = None
        self.signals, self.routes = signals, routes
        modes = sorted({s.source_mode.value for s in signals.values()} | {r.source_mode.value for r in routes.values() if r})
        unavailable = [k for k, s in signals.items() if s.source_mode == SourceMode.unavailable]
        detail = "四種路線與五種訊號已讀取" + (f"；不可用：{', '.join(unavailable)}" if unavailable else "")
        self._log(now, "perceive", "讀取即時訊號與路線", detail, modes)

    def _plan(self, now: datetime, user_state: str) -> tuple[Plan, list[Trigger]]:
        new_plan = make_plan(self.commitment, self.origin, now, self.routes, self.signals, self.campus, user_state)
        triggers = apply_cooldown(detect_triggers(self.plan, new_plan, now), self.trigger_history, now)
        if self.rationale_fn is not None:
            try:
                new_plan.rationale = self.rationale_fn(new_plan, self.commitment, [t for t in triggers if t.material]) or new_plan.rationale
            except Exception:
                pass  # model text is optional; the template rationale stays
        chosen = MODE_LABEL[new_plan.selected.mode] if new_plan.selected else "無可行方案"
        self._log(now, "plan", f"比較四種方式，選擇：{chosen}", new_plan.rationale)
        return new_plan, triggers

    def _act(self, now: datetime, new_plan: Plan, triggers: list[Trigger], user_state: str) -> None:
        material = [t for t in triggers if t.material]
        self.trigger_history.extend(triggers)
        self.last_triggers = triggers
        if material:
            self.decisions_agent += new_plan.decisions_made + len(material)
            self._log(now, "act", "更新建議卡", "；".join(t.description for t in material))
        self.plan = new_plan
        if new_plan.status in (PlanStatus.late_risk, PlanStatus.no_feasible) and user_state == "home" and not self._pending("email"):
            draft = build_late_email(self.commitment, new_plan, self.signals)
            preview = self.providers.email.preview(**draft) if self.providers.email else draft
            action = ProposedAction(id=f"act-{uuid.uuid4().hex[:8]}", type="email", preview=preview, created_at=now)
            self.actions.append(action)
            self._log(now, "act", "提議寄信給助教與組員（需你確認）", f"收件：{', '.join(preview.get('to', []))}")

    def _reflect(self, now: datetime, user_state: str) -> None:
        if user_state == "arrived_building":
            try:
                self.indoor = self.providers.indoor.locate(self.commitment.building_id, self.commitment.room) if self.providers.indoor else None
            except ProviderError:
                self.indoor = None
            self._log(now, "reflect", "已到大樓，切換教室導引", self.indoor.instructions if self.indoor else "此棟樓尚無平面圖")
            return
        nxt = self.plan.next_check_at.strftime("%H:%M") if self.plan and self.plan.next_check_at else "--:--"
        self._log(now, "reflect", f"下次檢查 {nxt}", f"你目前狀態：{user_state}")

    # ---- actions --------------------------------------------------------------

    def _pending(self, action_type: str) -> bool:
        return any(a.type == action_type and a.state == "proposed" for a in self.actions)

    def _find(self, action_id: str) -> ProposedAction:
        for a in self.actions:
            if a.id == action_id:
                return a
        raise KeyError(action_id)

    def confirm_action(self, action_id: str, now: datetime) -> ProposedAction:
        a = self._find(action_id)
        if a.state != "proposed":
            return a
        a.state = "confirmed"
        if a.type == "email" and self.providers.email:
            receipt = self.providers.email.send(a.preview)
            a.state = "executed_dry_run" if (self.dry_run or receipt.get("status") == "dry_run") else "confirmed"
        a.updated_at = now
        self.decisions_user += 1
        self._log(now, "act", "你確認寄信", "dry-run：未真的寄出" if a.state == "executed_dry_run" else "已寄出")
        return a

    def reject_action(self, action_id: str, now: datetime) -> ProposedAction:
        a = self._find(action_id)
        if a.state == "proposed":
            a.state = "rejected"
            a.updated_at = now
            self.decisions_user += 1
            self._log(now, "act", "你拒絕寄信", "")
        return a

    # ---- helpers --------------------------------------------------------------

    def _log(self, at: datetime, phase: str, title: str, detail: str = "", source_modes: list[str] | None = None) -> None:
        self.timeline.append(TimelineEvent(at=at, phase=phase, title=title, detail=detail, source_modes=source_modes or []))  # type: ignore[arg-type]

    def snapshot(self) -> dict[str, Any]:
        b = self.campus.building(self.commitment.building_id)
        return {
            "clock": self.clock.isoformat() if self.clock else None,
            "user_state": self.user_state,
            "commitment": self.commitment.model_dump(mode="json"),
            "origin": self.origin.model_dump(),
            "building": {"id": b.id, "name": b.name, "campus": b.campus, "location": b.location.model_dump()},
            "plan": self.plan.model_dump(mode="json") if self.plan else None,
            "signals": {k: s.model_dump(mode="json") for k, s in self.signals.items()},
            "routes_source": {m.value: (r.source_mode.value if r else "unavailable") for m, r in self.routes.items()},
            "timeline": [e.model_dump(mode="json") for e in self.timeline],
            "triggers": [t.model_dump(mode="json") for t in self.last_triggers],
            "actions": [a.model_dump(mode="json") for a in self.actions],
            "decisions": {"agent": self.decisions_agent, "user": self.decisions_user},
            "indoor": self.indoor.model_dump(mode="json") if self.indoor else None,
            "providers": self.providers.modes(),
        }
