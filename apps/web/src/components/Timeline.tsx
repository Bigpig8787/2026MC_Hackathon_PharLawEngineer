import { hhmm } from "../labels";
import type { TimelineEvent } from "../types";

const PHASE: Record<TimelineEvent["phase"], { label: string; cls: string }> = {
  perceive: { label: "感知", cls: "bg-gray-200 text-gray-800" },
  plan: { label: "規劃", cls: "bg-blue-100 text-blue-800" },
  act: { label: "行動", cls: "bg-green-100 text-green-800" },
  reflect: { label: "反思", cls: "bg-purple-100 text-purple-800" },
};

export default function Timeline({ events }: { events: TimelineEvent[] }) {
  return (
    <div className="rounded-xl bg-white p-4 shadow-sm">
      <div className="text-xs text-gray-500">Agent 時間軸（最新在上）</div>
      <ul className="mt-2 space-y-2">
        {[...events].reverse().map((e, i) => (
          <li key={i} className="flex gap-2 text-sm">
            <span className="w-11 shrink-0 tabular-nums text-gray-500">{hhmm(e.at)}</span>
            <span className={`h-fit shrink-0 rounded px-1.5 py-0.5 text-[11px] ${PHASE[e.phase].cls}`}>{PHASE[e.phase].label}</span>
            <div>
              <div>{e.title}</div>
              {e.detail && <div className="text-xs text-gray-500">{e.detail}</div>}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
