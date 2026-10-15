import clsx from "clsx";
import { useEffect, useRef } from "react";
import { CLASS_VAR, SYMBOL, type AnalysedMove } from "@/lib/types";

export function MoveList({ moves, ply, onSelect }: { moves: AnalysedMove[]; ply: number; onSelect: (ply: number) => void }) {
  const cur = useRef<HTMLButtonElement>(null);
  useEffect(() => { cur.current?.scrollIntoView({ block: "nearest" }); }, [ply]);
  const rows = Math.ceil(moves.length / 2);
  const cell = (i: number) => {
    const m = moves[i];
    if (!m) return <span />;
    const active = ply === i + 1, sym = SYMBOL[m.cls];
    return (
      <button ref={active ? cur : undefined} onClick={() => onSelect(i + 1)} aria-current={active ? "step" : undefined}
        className={clsx("flex items-baseline gap-1.5 rounded px-2 py-1 text-left font-medium cursor-pointer", active ? "bg-accent text-[var(--accent-text)]" : "hover:bg-surface-2")}>
        <span>{m.san}</span>
        {sym && <span className="text-[12px] font-bold" style={{ color: active ? "inherit" : CLASS_VAR[m.cls] }} title={m.cls}>{sym}</span>}
      </button>
    );
  };
  return (
    <div className="grid grid-cols-[32px_1fr_1fr] gap-y-px text-[13.5px]" role="list" aria-label="Moves">
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="contents" role="listitem">
          <span className="tnum px-1 py-1 text-right text-[12px] text-faint">{r + 1}.</span>
          {cell(2 * r)}
          {cell(2 * r + 1)}
        </div>
      ))}
    </div>
  );
}
