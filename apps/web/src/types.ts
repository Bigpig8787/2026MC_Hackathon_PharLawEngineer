export type Mode = "walk" | "scooter" | "bike" | "transit";
export type SourceMode = "live" | "fixture" | "stale" | "unavailable";
export type PlanStatus = "ok" | "late_risk" | "no_feasible" | "arrived";

export interface LatLng { lat: number; lng: number }

export interface RouteResult {
  mode: Mode; duration_min: number; distance_m: number; polyline: LatLng[];
  summary: string; corridor_ids: string[]; source_mode: SourceMode; mode_proxy?: string | null;
}

export interface LastDecision {
  kind: "parking_lot" | "bike_dock" | "bus_stop" | "gate";
  target_id: string; label: string; walk_min: number; reason: string; location?: LatLng | null;
}

export interface TravelOption {
  mode: Mode; route: RouteResult | null; last_decision: LastDecision | null;
  base_eta_min: number; conservative_eta_min: number;
  depart_at: string | null; arrive_at: string | null;
  feasible: boolean; on_time: boolean; slack_min: number;
  reasons: string[]; risk_flags: string[]; reliability: number; score: number; evidence: string[];
}

export interface Plan {
  commitment_id: string; generated_at: string; selected: TravelOption | null; options: TravelOption[];
  rationale: string; next_check_at: string | null; status: PlanStatus; policy_version: string; decisions_made: number;
}

export interface Commitment {
  id: string; title: string; start: string; building_id: string; room: string;
  importance: "normal" | "high" | "critical"; source: string; confirmed: boolean;
}

export interface Signal {
  kind: string; observed_at: string; valid_until: string | null;
  value: Record<string, unknown>; source_mode: SourceMode; confidence: number;
}

export interface TimelineEvent {
  at: string; phase: "perceive" | "plan" | "act" | "reflect"; title: string; detail: string; source_modes: string[];
}

export interface Trigger { kind: string; description: string; observed_at: string; material: boolean }

export interface ProposedAction {
  id: string; type: "email" | "calendar";
  preview: { to?: string[]; subject?: string; body?: string; [k: string]: unknown };
  state: "proposed" | "confirmed" | "rejected" | "executed_dry_run"; created_at: string;
}

export interface IndoorGuidance {
  building_id: string; room: string; floor: string; wing: string; entrance: string;
  instructions: string; source_mode: SourceMode; confidence: number;
}

export interface AppState {
  clock: string | null; user_state: string;
  step_index: number; step_count: number; step_note: string; scenario_title: string;
  commitment: Commitment; origin: LatLng;
  building: { id: string; name: string; campus: string; location: LatLng };
  plan: Plan | null; signals: Record<string, Signal>; routes_source: Record<string, string>;
  timeline: TimelineEvent[]; triggers: Trigger[]; actions: ProposedAction[];
  decisions: { agent: number; user: number }; indoor: IndoorGuidance | null;
  providers: Record<string, string>;
}

export interface Health {
  status: string; provider_mode: string; dry_run: boolean; missing_credentials: string[]; providers: Record<string, string>;
}
