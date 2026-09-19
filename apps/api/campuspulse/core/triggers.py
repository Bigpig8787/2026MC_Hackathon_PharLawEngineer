"""Material-change detection between consecutive plans."""
from __future__ import annotations

from datetime import datetime, timedelta

from campuspulse.core.models import Plan, Trigger
from campuspulse.core.planner import MODE_LABEL

MATERIAL_ETA_INCREASE_MIN = 5.0
MATERIAL_DEPART_EARLIER_MIN = 3.0
COOLDOWN = timedelta(minutes=5)
ALWAYS_MATERIAL = {"initial_plan", "feasibility_flip"}


def detect_triggers(old: Plan | None, new: Plan, now: datetime) -> list[Trigger]:
    if old is None:
        return [Trigger(kind="initial_plan", description="產生初始計畫", observed_at=now, material=True)]
    out: list[Trigger] = []
    old_by = {o.mode: o for o in old.options}
    for n in new.options:
        o = old_by.get(n.mode)
        if o is not None and o.feasible != n.feasible:
            out.append(Trigger(
                kind="feasibility_flip", description=f"{MODE_LABEL[n.mode]}{'變為可行' if n.feasible else '不再可行'}",
                old=o.feasible, new=n.feasible, observed_at=now, material=True,
            ))
    old_mode = old.selected.mode if old.selected else None
    new_mode = new.selected.mode if new.selected else None
    if old_mode != new_mode:
        out.append(Trigger(
            kind="selected_mode_changed",
            description=f"建議從 {MODE_LABEL[old_mode] if old_mode else '無'} 改為 {MODE_LABEL[new_mode] if new_mode else '無'}",
            old=old_mode.value if old_mode else None, new=new_mode.value if new_mode else None, observed_at=now, material=True,
        ))
    elif old.selected and new.selected:
        o, n = old.selected, new.selected
        if o.depart_at and n.depart_at:
            earlier = (o.depart_at - n.depart_at).total_seconds() / 60
            if earlier > MATERIAL_DEPART_EARLIER_MIN:
                out.append(Trigger(kind="depart_earlier", description=f"出門時間提早 {earlier:.0f} 分", old=o.depart_at, new=n.depart_at, observed_at=now, material=True))
        delta = n.conservative_eta_min - o.conservative_eta_min
        if delta > MATERIAL_ETA_INCREASE_MIN:
            out.append(Trigger(kind="eta_increase", description=f"預估時間增加 {delta:.0f} 分", old=o.conservative_eta_min, new=n.conservative_eta_min, observed_at=now, material=True))
        elif delta != 0:
            out.append(Trigger(kind="eta_drift", description=f"預估時間變動 {delta:+.0f} 分", old=o.conservative_eta_min, new=n.conservative_eta_min, observed_at=now, material=False))
        if "rerouted" in n.risk_flags and "rerouted" not in o.risk_flags:
            out.append(Trigger(kind="rerouted", description="原路線積淹水，已改道", observed_at=now, material=True))
    if old.status != new.status:
        out.append(Trigger(kind="status_changed", description=f"狀態 {old.status.value} → {new.status.value}", old=old.status.value, new=new.status.value, observed_at=now, material=True))
    return out


def apply_cooldown(triggers: list[Trigger], history: list[Trigger], now: datetime) -> list[Trigger]:
    for t in triggers:
        if t.kind in ALWAYS_MATERIAL or not t.material:
            continue
        if any(h.kind == t.kind and (now - h.observed_at) < COOLDOWN for h in history):
            t.material = False
    return triggers
