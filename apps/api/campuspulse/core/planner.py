"""Deterministic travel planner. Pure: no I/O, no wall clock, no model calls."""
from __future__ import annotations

from datetime import datetime, timedelta

from campuspulse.core.campus import Campus
from campuspulse.core.models import (
    Commitment, Importance, LastDecision, LatLng, Mode, Plan, PlanStatus, RouteResult, Signal, SourceMode, TravelOption,
)

POLICY_VERSION = "0.1"
BUFFER_MIN = {Importance.normal: 5, Importance.high: 10, Importance.critical: 15}
FIXED_COST_MIN = {Mode.walk: 0.0, Mode.bike: 2.0, Mode.scooter: 3.0, Mode.transit: 2.0}
BASE_RELIABILITY = {Mode.walk: 0.9, Mode.bike: 0.6, Mode.scooter: 0.7, Mode.transit: 0.8}
MODE_ORDER = [Mode.scooter, Mode.transit, Mode.bike, Mode.walk]
MODE_LABEL = {Mode.walk: "步行", Mode.scooter: "機車", Mode.bike: "YouBike", Mode.transit: "公車"}
RECHECK_MIN = 5
RECHECK_URGENT_MIN = 2
TRANSIT_UNKNOWN_WAIT_MIN = 10.0
REASON_LABEL = {
    "route_unavailable": "查無路線",
    "unsafe_heavy_rain": "豪雨不安全",
    "flood_on_route": "路線積淹水",
    "no_bike": "起點站無車",
    "no_dock": "終點站無位",
    "no_parking": "停車場全滿",
    "too_late": "已來不及準時",
}


def rain_factor(mode: Mode, rain_mm_h: float) -> float | None:
    if rain_mm_h >= 20:
        return {Mode.walk: 1.6, Mode.bike: None, Mode.scooter: 1.3, Mode.transit: 1.1}[mode]
    if rain_mm_h >= 5:
        return {Mode.walk: 1.3, Mode.bike: 1.4, Mode.scooter: 1.2, Mode.transit: 1.05}[mode]
    return 1.0


def _known(signals: dict[str, Signal], kind: str) -> Signal | None:
    s = signals.get(kind)
    if s is None or s.source_mode == SourceMode.unavailable:
        return None
    return s


def _rain_mm(signals: dict[str, Signal]) -> tuple[float, bool]:
    s = _known(signals, "rain")
    if s is None:
        return 0.0, False
    v = s.value
    return max(float(v.get("mm_per_hour", 0)), float(v.get("forecast_next_hour_mm", 0))), True


def _flooded(signals: dict[str, Signal]) -> tuple[set[str], bool]:
    s = _known(signals, "flood")
    if s is None:
        return set(), False
    return {a["corridor_id"] for a in s.value.get("alerts", []) if a.get("level") in ("warning", "danger")}, True


def _resolve_route(route: RouteResult, mode: Mode, flooded: set[str]) -> tuple[RouteResult | None, list[str], list[str]]:
    if mode == Mode.transit or not (set(route.corridor_ids) & flooded):
        return route, [], []
    alt = route.alternative
    if alt and not (set(alt.corridor_ids) & flooded):
        return alt, [], ["rerouted"]
    return None, ["flood_on_route"], ["flood_on_route"]


def _fmt(sig: Signal, text: str) -> str:
    return f"{text}（{sig.source_mode.value}，{sig.observed_at.strftime('%H:%M')}）"


def _last_decision(
    mode: Mode, commitment: Commitment, origin: LatLng, campus: Campus, signals: dict[str, Signal], rain_mm: float
) -> tuple[LastDecision | None, list[str], list[str], list[str]]:
    """Returns (decision, reasons, risk_flags, evidence)."""
    b = commitment.building_id
    if mode == Mode.scooter:
        s = _known(signals, "parking")
        risks: list[str] = []
        if s is None:
            candidates = list(campus.lots)
            free_of = {lot.id: None for lot in candidates}
            risks.append("parking_unavailable")
            evidence = ["停車場狀態不可用，假設有位"]
        else:
            lots_state = s.value.get("lots", {})
            free_of = {lot.id: int(lots_state.get(lot.id, {}).get("free", 0)) for lot in campus.lots}
            candidates = [lot for lot in campus.lots if free_of[lot.id] > 0]
            evidence = [_fmt(s, "停車場剩位 " + ", ".join(f"{lot.id}:{free_of[lot.id]}" for lot in campus.lots))]
        if not candidates:
            return None, ["no_parking"], risks, evidence
        ranked = sorted(
            candidates,
            key=lambda lot: (0 if (rain_mm >= 5 and lot.covered) else 1, campus.walk_to_building(lot.location, b)[1]),
        )
        lot = ranked[0]
        entrance, walk = campus.walk_to_building(lot.location, b)
        free_txt = f"剩 {free_of[lot.id]} 位" if free_of[lot.id] is not None else "剩位未知"
        reason = f"{'有遮雨、' if lot.covered else ''}離{entrance.name}步行 {walk} 分，{free_txt}"
        return LastDecision(kind="parking_lot", target_id=lot.id, label=lot.name, walk_min=walk, reason=reason, location=lot.location), [], risks, evidence

    if mode == Mode.bike:
        s = _known(signals, "bike")
        if s is None:
            return None, ["route_unavailable"], ["bike_unavailable"], ["YouBike 狀態不可用"]
        v = s.value
        evidence = [_fmt(s, f"起點站可借 {v.get('available')}，終點站可還 {v.get('docks')}")]
        if int(v.get("available", 0)) <= 0:
            return None, ["no_bike"], [], evidence
        station = campus.bike_station(v["dest_station_id"])
        reason = "終點站有空位"
        if int(v.get("docks", 0)) <= 0:
            if int(v.get("next_station_docks", 0)) <= 0:
                return None, ["no_dock"], [], evidence
            station = campus.bike_station(v["next_station_id"])
            reason = "原站無空位，改還下一站"
        entrance, walk = campus.walk_to_building(station.location, b)
        return LastDecision(kind="bike_dock", target_id=station.id, label=station.name, walk_min=walk, reason=f"{reason}，離{entrance.name}步行 {walk} 分", location=station.location), [], [], evidence

    if mode == Mode.transit:
        s = _known(signals, "transit")
        if s is None:
            return None, ["route_unavailable"], ["transit_unavailable"], ["公車狀態不可用"]
        v = s.value
        stop = campus.bus_stop(v["alight_stop_id"])
        entrance, walk = campus.walk_to_building(stop.location, b)
        eta = v.get("next_eta_min")
        evidence = [_fmt(s, f"{v.get('route_name', '')} 號公車下一班 {eta if eta is not None else '未知'} 分")]
        return LastDecision(kind="bus_stop", target_id=stop.id, label=stop.name, walk_min=walk, reason=f"離{entrance.name}最近的站，步行 {walk} 分", location=stop.location), [], [], evidence

    entrance = campus.nearest_entrance(b, origin)
    return LastDecision(kind="gate", target_id=entrance.id, label=entrance.name, walk_min=0.0, reason="離你方向最近的入口", location=entrance.location), [], [], []


def evaluate_option(
    mode: Mode, commitment: Commitment, origin: LatLng, now: datetime, route: RouteResult | None,
    signals: dict[str, Signal], campus: Campus,
) -> TravelOption:
    reasons: list[str] = []
    risks: list[str] = []
    evidence: list[str] = []
    if route is None:
        return TravelOption(mode=mode, reasons=["route_unavailable"], risk_flags=["routing_unavailable"])

    rain_mm, rain_known = _rain_mm(signals)
    if not rain_known:
        risks.append("rain_unavailable")
    else:
        evidence.append(_fmt(signals["rain"], f"雨量 {rain_mm:g} mm/h"))
    flooded, flood_known = _flooded(signals)
    if not flood_known:
        risks.append("flood_unavailable")
    elif flooded:
        evidence.append(_fmt(signals["flood"], "積淹水警戒：" + ", ".join(sorted(flooded))))

    route_used, r_reasons, r_risks = _resolve_route(route, mode, flooded)
    reasons += r_reasons
    risks += r_risks
    factor = rain_factor(mode, rain_mm)
    if factor is None:
        reasons.append("unsafe_heavy_rain")
        factor = 1.0

    decision, d_reasons, d_risks, d_evidence = _last_decision(mode, commitment, origin, campus, signals, rain_mm)
    reasons += d_reasons
    risks += d_risks
    evidence += d_evidence

    base = (route_used or route).duration_min
    conservative = base * factor + FIXED_COST_MIN[mode] + (decision.walk_min if decision else 0.0)

    buffer = timedelta(minutes=BUFFER_MIN[commitment.importance])
    deadline = commitment.start - buffer

    if mode == Mode.transit:
        transit = _known(signals, "transit")
        eta = transit.value.get("next_eta_min") if transit else None
        if eta is None:
            conservative += TRANSIT_UNKNOWN_WAIT_MIN
            risks.append("transit_eta_unavailable")
            depart_at = now
        else:
            depart_at = now + timedelta(minutes=float(eta))
    else:
        latest = deadline - timedelta(minutes=conservative)
        depart_at = max(now, latest)
    arrive_at = depart_at + timedelta(minutes=conservative)

    feasible = not reasons and arrive_at <= deadline
    on_time = not reasons and arrive_at <= commitment.start
    if not reasons and not on_time:
        reasons.append("too_late")
    slack = round((commitment.start - arrive_at).total_seconds() / 60, 1)

    reliability = BASE_RELIABILITY[mode]
    if rain_mm >= 5:
        reliability -= {Mode.bike: 0.2, Mode.walk: 0.1}.get(mode, 0.0)
    if rain_mm >= 20 and mode == Mode.scooter:
        reliability -= 0.1
    if any(r.endswith("_unavailable") for r in risks):
        reliability -= 0.3
    reliability = max(0.0, min(1.0, reliability))

    return TravelOption(
        mode=mode, route=route_used or route, last_decision=decision, base_eta_min=base,
        conservative_eta_min=round(conservative, 1), depart_at=depart_at, arrive_at=arrive_at,
        feasible=feasible, on_time=on_time, slack_min=slack, reasons=reasons, risk_flags=risks,
        reliability=round(reliability, 2), evidence=evidence,
    )


def _score(option: TravelOption, importance: Importance, max_cons: float) -> float:
    time_part = 1.0 - (option.conservative_eta_min / max_cons if max_cons else 0.0)
    if importance in (Importance.high, Importance.critical):
        return round(0.7 * option.reliability + 0.3 * time_part, 3)
    return round(0.3 * option.reliability + 0.7 * time_part, 3)


def plan(
    commitment: Commitment, origin: LatLng, now: datetime, routes: dict[Mode, RouteResult | None],
    signals: dict[str, Signal], campus: Campus, user_state: str = "home",
) -> Plan:
    options = [evaluate_option(m, commitment, origin, now, routes.get(m), signals, campus) for m in MODE_ORDER]
    max_cons = max((o.conservative_eta_min for o in options if o.route), default=1.0) or 1.0
    for o in options:
        o.score = _score(o, commitment.importance, max_cons)
    ranked = sorted(options, key=lambda o: (0 if o.feasible else 1 if o.on_time else 2, -o.score, o.conservative_eta_min))
    top = ranked[0]
    selected = top if (top.feasible or top.on_time) else None

    if user_state == "arrived_building":
        status = PlanStatus.arrived
    elif selected is None:
        status = PlanStatus.no_feasible
    elif not selected.feasible:
        status = PlanStatus.late_risk
    else:
        status = PlanStatus.ok

    decisions = len(options) + 1 + sum(1 for o in options if o.last_decision)
    urgent = status in (PlanStatus.late_risk, PlanStatus.no_feasible)
    p = Plan(
        commitment_id=commitment.id, generated_at=now, selected=selected, options=ranked,
        next_check_at=now + timedelta(minutes=RECHECK_URGENT_MIN if urgent else RECHECK_MIN),
        status=status, policy_version=POLICY_VERSION, decisions_made=decisions,
    )
    p.rationale = build_rationale(p, commitment)
    return p


def _hhmm(dt: datetime | None) -> str:
    return dt.strftime("%H:%M") if dt else "--:--"


def build_rationale(p: Plan, commitment: Commitment) -> str:
    rejected = [o for o in p.options if p.selected is None or o.mode != p.selected.mode]
    rejected_txt = "；".join(
        f"{MODE_LABEL[o.mode]}：" + ("、".join(REASON_LABEL.get(r, r) for r in o.reasons) if o.reasons else f"可行但分數較低（可靠度 {o.reliability}）")
        for o in rejected
    )
    if p.status == PlanStatus.arrived:
        return "你已到大樓，切換為教室導引。"
    if p.selected is None:
        return f"四種方式都無法在 {_hhmm(commitment.start)} 前抵達。建議先通知助教與組員。{rejected_txt}"
    s = p.selected
    ld = f"，{s.last_decision.label}（{s.last_decision.reason}）" if s.last_decision else ""
    head = f"建議 {_hhmm(s.depart_at)} 出門{MODE_LABEL[s.mode]}，預計 {_hhmm(s.arrive_at)} 到{ld}。"
    if p.status == PlanStatus.late_risk:
        head += f" 緩衝只剩 {s.slack_min:g} 分鐘，再晚就會遲到。"
    return head + " 其他：" + rejected_txt
