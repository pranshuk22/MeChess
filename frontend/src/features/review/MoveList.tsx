import clsx from "clsx";
import { useEffect, useRef } from "react";
import { ClassIcon } from "@/components/ClassIcon";
import type { AnalysedMove, MoveClass } from "@/lib/types";

const QUIET: MoveClass[] = ["book", "good", "excellent"];            // not flagged in the list: only the moves worth a look carry an icon

export function MoveList({ moves, ply, onSelect }: { moves: AnalysedMove[]; ply: number; onSelect: (ply: number) => void }) {
  const cur = useRef<HTMLButtonElement>(null);
  useEffect(() => { cur.current?.scrollIntoView({ block: "nearest" }); }, [ply]);
  const rows = Math.ceil(moves.length / 2);
  const cell = (i: number) => {
    const m = moves[i];
    if (!m) return <span />;
    const active = ply === i + 1;
    return (
      <button ref={active ? cur : undefined} onClick={() => onSelect(i + 1)} aria-current={active ? "step" : undefined}
        className={clsx("flex items-center gap-1.5 rounded px-2 py-1 text-left font-medium cursor-pointer", active ? "bg-accent text-[var(--accent-text)]" : "hover:bg-surface-2")}>
        <span>{m.san}</span>
        {!QUIET.includes(m.cls) && <ClassIcon cls={m.cls} size={15} />}
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
