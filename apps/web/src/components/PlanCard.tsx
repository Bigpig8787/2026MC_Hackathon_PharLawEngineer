import { MODE_ICON, MODE_LABEL, REASON_LABEL, RISK_LABEL, STATUS_LABEL, hhmm } from "../labels";
import type { Mode, Plan } from "../types";

interface Props { plan: Plan; activeMode: Mode; onSelectMode: (m: Mode) => void }

export default function PlanCard({ plan, activeMode, onSelectMode }: Props) {
  const active = plan.options.find((o) => o.mode === activeMode) ?? plan.options[0];
  const isSelected = plan.selected?.mode === active.mode;
  const statusClass = plan.status === "ok" ? "bg-green-100 text-green-800" : plan.status === "arrived" ? "bg-blue-100 text-blue-800" : "bg-red-100 text-red-800";
  return (
    <div className="rounded-xl bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="text-xs text-gray-500">建議方案</div>
        <span className={`rounded px-2 py-0.5 text-xs ${statusClass}`}>{STATUS_LABEL[plan.status]}</span>
      </div>
      <div className="mt-2 flex gap-1">
        {plan.options.map((o) => (
          <button key={o.mode} onClick={() => onSelectMode(o.mode)}
            className={`flex-1 rounded-lg border px-1 py-1.5 text-xs ${o.mode === active.mode ? "border-blue-600 bg-blue-50" : "border-gray-200"} ${o.feasible ? "" : o.on_time ? "opacity-80" : "opacity-50"}`}>
            <div>{MODE_ICON[o.mode]} {MODE_LABEL[o.mode]}</div>
            <div className="text-[10px] text-gray-500">{o.feasible ? "可行" : o.on_time ? "勉強" : "不可行"}{plan.selected?.mode === o.mode ? "・推薦" : ""}</div>
          </button>
        ))}
      </div>
      <div className="mt-3">
        {active.reasons.length === 0 ? (
          <div className="text-xl font-semibold">
            {hhmm(active.depart_at)} 出門 → {hhmm(active.arrive_at)} 到
            <span className="ml-2 text-sm font-normal text-gray-500">緩衝 {active.slack_min} 分</span>
          </div>
        ) : (
          <div className="text-base font-semibold text-red-700">{active.reasons.map((r) => REASON_LABEL[r] ?? r).join("、")}</div>
        )}
        {active.last_decision && (
          <div className="mt-2 rounded-lg bg-gray-50 p-2 text-sm">
            <div className="text-xs text-gray-500">最後一個決定</div>
            <div className="font-medium">{active.last_decision.label}</div>
            <div className="text-xs text-gray-600">{active.last_decision.reason}</div>
          </div>
        )}
        {active.risk_flags.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1">
            {active.risk_flags.map((f) => <span key={f} className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] text-amber-800">{RISK_LABEL[f] ?? f}</span>)}
          </div>
        )}
        <div className="mt-2 text-xs text-gray-500">
          路線 {active.route?.summary}・預估 {active.conservative_eta_min} 分（含緩衝係數）・可靠度 {active.reliability}
          {active.route?.mode_proxy ? `・以 ${active.route.mode_proxy} 代算` : ""}
        </div>
        {active.evidence.length > 0 && (
          <ul className="mt-1 list-disc pl-4 text-xs text-gray-500">{active.evidence.map((e, i) => <li key={i}>{e}</li>)}</ul>
        )}
        {isSelected && <p className="mt-3 border-t pt-2 text-sm">{plan.rationale}</p>}
      </div>
    </div>
  );
}
