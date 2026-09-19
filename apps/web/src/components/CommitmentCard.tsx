import { hhmm } from "../labels";
import type { AppState } from "../types";

const IMPORTANCE: Record<string, string> = { normal: "一般", high: "重要", critical: "絕不能遲到" };

export default function CommitmentCard({ state }: { state: AppState }) {
  const c = state.commitment;
  return (
    <div className="rounded-xl bg-white p-4 shadow-sm">
      <div className="text-xs text-gray-500">今天的承諾・來源 {c.source}</div>
      <div className="mt-1 text-lg font-semibold">{c.title}</div>
      <div className="mt-1 text-sm">{hhmm(c.start)}・{state.building.name} {c.room}</div>
      <span className={`mt-2 inline-block rounded px-2 py-0.5 text-xs ${c.importance === "normal" ? "bg-gray-100" : "bg-red-100 text-red-800"}`}>
        {IMPORTANCE[c.importance]}
      </span>
    </div>
  );
}
