export default function DecisionCounter({ agent, user }: { agent: number; user: number }) {
  return (
    <div className="rounded-xl bg-blue-600 p-4 text-white shadow-sm">
      <div className="text-xs opacity-80">省下的專注力</div>
      <div className="text-lg font-semibold">今天 CampusPulse 幫你做了 {agent} 個決定，你做了 {user} 個</div>
    </div>
  );
}
