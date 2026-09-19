import { SOURCE_CLASS, hhmm } from "../labels";
import type { AppState } from "../types";

interface Props { state: AppState; busy: boolean; onReset: () => void; onStep: () => void }

export default function ScenarioBar({ state, busy, onReset, onStep }: Props) {
  const last = state.step_index >= state.step_count - 1;
  return (
    <div className="rounded-xl bg-white p-3 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-2xl font-semibold tabular-nums">{hhmm(state.clock)}</div>
          <div className="text-xs text-gray-500">劇本 {state.step_index + 1}/{state.step_count}・{state.step_note}</div>
        </div>
        <div className="flex gap-2">
          <button onClick={onReset} disabled={busy} className="rounded-lg border px-3 py-2 text-sm">重設</button>
          <button onClick={onStep} disabled={busy || last} className="rounded-lg bg-blue-600 px-3 py-2 text-sm text-white disabled:opacity-40">推進 ▶</button>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {Object.entries(state.providers).map(([name, mode]) => (
          <span key={name} className={`rounded px-1.5 py-0.5 text-[11px] ${SOURCE_CLASS[mode] ?? SOURCE_CLASS.unavailable}`}>{name}: {mode}</span>
        ))}
      </div>
    </div>
  );
}
