import type { ProposedAction } from "../types";

interface Props { action: ProposedAction; busy: boolean; onConfirm: () => void; onReject: () => void }

export default function ActionModal({ action, busy, onConfirm, onReject }: Props) {
  return (
    <div className="fixed inset-0 z-[1000] flex items-end justify-center bg-black/40 p-4 sm:items-center">
      <div className="w-full max-w-[480px] rounded-xl bg-white p-4 shadow-lg">
        <div className="text-xs text-gray-500">需要你確認・寄信</div>
        <div className="mt-1 font-semibold">{action.preview.subject}</div>
        <div className="mt-1 text-xs text-gray-500">收件：{(action.preview.to ?? []).join("、")}</div>
        <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-gray-50 p-2 text-sm">{action.preview.body}</pre>
        <div className="mt-3 flex gap-2">
          <button onClick={onReject} disabled={busy} className="flex-1 rounded-lg border px-3 py-2 text-sm">先不要</button>
          <button onClick={onConfirm} disabled={busy} className="flex-1 rounded-lg bg-blue-600 px-3 py-2 text-sm text-white">確認寄出（dry-run）</button>
        </div>
      </div>
    </div>
  );
}
