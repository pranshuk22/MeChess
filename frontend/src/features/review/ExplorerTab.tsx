import { BookOpen } from "lucide-react";
import { useExplorer } from "@/api/hooks";
import { EmptyState, Skeleton } from "@/components/ui/Misc";

/** What players of your rating play here, with how those games went. A click plays the move. */
export function ExplorerTab({ fen, active, onPlay }: { fen: string; active: boolean; onPlay: (uci: string) => void }) {
  const q = useExplorer(fen, active);
  if (q.isLoading) return <div className="space-y-2 p-4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-9" />)}</div>;
  if (q.data === null) return <EmptyState icon={BookOpen} title="The opening explorer is not built yet" text="It needs the explorer database; the workspace checklist on the home page says how to get it." />;
  if (q.isError || !q.data) return <p className="p-4 text-[13px] text-[var(--q-blunder)]">The explorer could not be read.</p>;
  const { total, moves } = q.data;
  if (!moves.length) return <p className="p-4 text-[13px] text-muted">No games in the database reach this position.</p>;
  return (
    <div className="p-2">
      <div className="px-2.5 pb-2 text-[12px] text-muted">{total.toLocaleString()} games reached this position</div>
      {moves.slice(0, 12).map((m) => (
        <button key={m.uci} onClick={() => onPlay(m.uci)} className="grid w-full grid-cols-[54px_1fr_64px] items-center gap-3 rounded-[9px] px-2.5 py-2 text-left transition-colors hover:bg-surface-2 cursor-pointer">
          <b className="text-[13.5px] font-semibold">{m.san}</b>
          <span className="flex h-4 overflow-hidden rounded-[4px] text-[10px] font-semibold leading-4 text-white" title={`White ${Math.round(m.white * 100)}%  Draw ${Math.round(m.draw * 100)}%  Black ${Math.round(m.black * 100)}%`}>
            <span style={{ width: `${m.white * 100}%`, background: "#d9dde2", color: "#2b3139" }} className="text-center">{m.white > 0.18 ? Math.round(m.white * 100) : ""}</span>
            <span style={{ width: `${m.draw * 100}%`, background: "#8a95a1" }} className="text-center">{m.draw > 0.18 ? Math.round(m.draw * 100) : ""}</span>
            <span style={{ width: `${m.black * 100}%`, background: "#2b3139" }} className="text-center">{m.black > 0.18 ? Math.round(m.black * 100) : ""}</span>
          </span>
          <span className="tnum text-right text-[12.5px] text-muted">{m.games >= 1000 ? `${(m.games / 1000).toFixed(m.games >= 10000 ? 0 : 1)}k` : m.games}</span>
        </button>
      ))}
    </div>
  );
}
