import { SOURCE_CLASS } from "../labels";
import type { IndoorGuidance } from "../types";

export default function IndoorCard({ guidance, buildingName }: { guidance: IndoorGuidance; buildingName: string }) {
  return (
    <div className="rounded-xl border-2 border-green-600 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="text-xs text-gray-500">最後 200 公尺・{buildingName}</div>
        <span className={`rounded px-1.5 py-0.5 text-[11px] ${SOURCE_CLASS[guidance.source_mode]}`}>{guidance.source_mode}</span>
      </div>
      <div className="mt-1 text-2xl font-semibold">{guidance.room}</div>
      <div className="text-sm">{guidance.floor}・{guidance.wing}・從{guidance.entrance}進</div>
      <p className="mt-2 text-sm">{guidance.instructions}</p>
    </div>
  );
}
