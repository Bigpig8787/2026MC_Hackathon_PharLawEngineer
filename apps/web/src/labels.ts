import type { Mode, PlanStatus, SourceMode } from "./types";

export const MODE_LABEL: Record<Mode, string> = { walk: "步行", scooter: "機車", bike: "YouBike", transit: "公車" };
export const MODE_ICON: Record<Mode, string> = { walk: "🚶", scooter: "🛵", bike: "🚲", transit: "🚌" };
export const REASON_LABEL: Record<string, string> = {
  route_unavailable: "查無路線", unsafe_heavy_rain: "豪雨不安全", flood_on_route: "路線積淹水",
  no_bike: "起點站無車", no_dock: "終點站無位", no_parking: "停車場全滿", too_late: "已來不及準時",
};
export const RISK_LABEL: Record<string, string> = {
  rerouted: "已改道", rain_unavailable: "無雨量資料", flood_unavailable: "無積水資料",
  transit_eta_unavailable: "無公車到站資料", parking_unavailable: "無停車場資料", routing_unavailable: "無路線資料",
};
export const STATUS_LABEL: Record<PlanStatus, string> = { ok: "照計畫", late_risk: "快遲到", no_feasible: "來不及", arrived: "已到大樓" };
export const SOURCE_CLASS: Record<SourceMode | string, string> = {
  live: "bg-green-100 text-green-800", fixture: "bg-amber-100 text-amber-800",
  stale: "bg-orange-100 text-orange-800", unavailable: "bg-red-100 text-red-800",
};
export const hhmm = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleTimeString("zh-TW", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: "Asia/Taipei" }) : "--:--";
