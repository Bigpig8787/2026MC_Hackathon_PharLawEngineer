import { useCallback, useEffect, useState } from "react";
import { confirmAction, getState, rejectAction, resetScenario, stepScenario } from "./api/client";
import ActionModal from "./components/ActionModal";
import CommitmentCard from "./components/CommitmentCard";
import DecisionCounter from "./components/DecisionCounter";
import IndoorCard from "./components/IndoorCard";
import MapView from "./components/MapView";
import PlanCard from "./components/PlanCard";
import ScenarioBar from "./components/ScenarioBar";
import Timeline from "./components/Timeline";
import type { AppState, Mode } from "./types";

export default function App() {
  const [state, setState] = useState<AppState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [activeMode, setActiveMode] = useState<Mode | null>(null);

  useEffect(() => { getState().then(setState).catch((e) => setError(String(e))); }, []);

  const wrap = useCallback((fn: () => Promise<AppState>) => async () => {
    setBusy(true); setError(null);
    try { setState(await fn()); setActiveMode(null); }
    catch (e) { setError(String(e)); }
    finally { setBusy(false); }
  }, []);

  if (error) return <pre className="p-4 text-red-700">{error}</pre>;
  if (!state) return <p className="p-4">載入中…</p>;

  const pendingAction = state.actions.find((a) => a.state === "proposed");
  const modeToShow = activeMode ?? state.plan?.selected?.mode ?? "walk";

  return (
    <div className="mx-auto max-w-md space-y-4 p-4 pb-12">
      <ScenarioBar state={state} busy={busy} onReset={wrap(resetScenario)} onStep={wrap(stepScenario)} />
      <CommitmentCard state={state} />
      {state.indoor ? (
        <IndoorCard guidance={state.indoor} buildingName={state.building.name} />
      ) : state.plan ? (
        <PlanCard plan={state.plan} activeMode={modeToShow} onSelectMode={setActiveMode} />
      ) : null}
      <DecisionCounter agent={state.decisions.agent} user={state.decisions.user} />
      <MapView origin={state.origin} building={state.building} option={state.plan?.options.find((o) => o.mode === modeToShow)} />
      <Timeline events={state.timeline} />
      {pendingAction && (
        <ActionModal action={pendingAction} busy={busy}
          onConfirm={wrap(() => confirmAction(pendingAction.id))} onReject={wrap(() => rejectAction(pendingAction.id))} />
      )}
    </div>
  );
}
