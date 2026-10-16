import { useMemo, useState } from "react";
import { CLASS_LABEL, CLASS_VAR, winPercent, type AnalysedMove } from "@/lib/types";

const W = 400, H = 112;
const BAD = ["mistake", "blunder", "miss"];
const GOOD = ["brilliant", "great"];

/** The game's evaluation as White's share of the position (white fill on a dark track, like the evaluation bar). Hover shows the move, its class and the evaluation; click jumps there. Both
 *  players' mistakes and blunders are dotted in the class colours (yours larger), brilliant and great moves are marked in their colours, and faint lines show where the phases change. */
export function EvalGraph({ moves, ply, onSelect, userIsWhite }: { moves: AnalysedMove[]; ply: number; onSelect: (ply: number) => void; userIsWhite: boolean }) {
  const n = moves.length;
  const [hover, setHover] = useState<number | null>(null);
  const x = (i: number) => (n <= 1 ? 0 : (i / n) * W);
  const y = (cp: number) => H - (winPercent(cp) / 100) * H;
  const { line, area, marks, phases } = useMemo(() => {
    const pts = [[0, H / 2], ...moves.map((m, i) => [x(i + 1), y(m.cp)])];
    const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    const marks = moves.flatMap((m, i) => (BAD.includes(m.cls) && m.loss >= 0.1) || GOOD.includes(m.cls) ? [{ i: i + 1, cx: x(i + 1), cy: y(m.cp), cls: m.cls, mine: (i % 2 === 0) === userIsWhite }] : []);
    const phases = moves.flatMap((m, i) => (i > 0 && m.phase && moves[i - 1].phase && m.phase !== moves[i - 1].phase ? [x(i)] : []));
    return { line, area: `${line} L ${W} ${H} L 0 ${H} Z`, marks, phases };
  }, [moves, userIsWhite]);                                             // eslint-disable-line react-hooks/exhaustive-deps
  const at = (e: React.PointerEvent<HTMLElement>) => { const r = e.currentTarget.getBoundingClientRect(); return Math.max(0, Math.min(n, Math.round(((e.clientX - r.left) / r.width) * n))); };
  const hm = hover !== null && hover > 0 ? moves[hover - 1] : null;
  return (
    <div className="relative" onPointerMove={(e) => setHover(at(e))} onPointerLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} className="block h-[112px] w-full cursor-pointer overflow-hidden rounded-[6px]" preserveAspectRatio="none" onClick={(e) => onSelect(at(e as unknown as React.PointerEvent<HTMLElement>))} role="img" aria-label="Evaluation graph: click to jump to a move">
        <rect width={W} height={H} fill="#2b3139" />
        <path d={area} fill="#f4f6f8" />
        {phases.map((px, i) => <line key={i} x1={px} x2={px} y1="0" y2={H} stroke="#8a95a1" strokeWidth="1" strokeDasharray="2 3" opacity="0.55" vectorEffect="non-scaling-stroke" />)}
        <line x1="0" x2={W} y1={H / 2} y2={H / 2} stroke="#8a95a1" strokeWidth="1" strokeDasharray="3 4" opacity="0.7" vectorEffect="non-scaling-stroke" />
        <path d={line} fill="none" stroke="var(--accent)" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
        {marks.map((d) => <ellipse key={d.i} cx={d.cx} cy={d.cy} rx={d.mine ? 2.6 : 1.9} ry={d.mine ? 5.2 : 3.8} fill={CLASS_VAR[d.cls as keyof typeof CLASS_VAR]} stroke="#fff" strokeWidth={d.mine ? 1 : 0.6} />)}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1="0" y2={H} stroke="#fff" strokeWidth="1" opacity="0.55" vectorEffect="non-scaling-stroke" />}
        <line x1={x(ply)} x2={x(ply)} y1="0" y2={H} stroke="var(--accent)" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
      </svg>
      {hm && hover !== null && (
        <div className="pointer-events-none absolute -top-9 z-10 -translate-x-1/2 whitespace-nowrap rounded-[6px] bg-[#1d262d] px-2 py-1 text-[11.5px] text-[#e8eef2] shadow-lg" style={{ left: `${Math.min(88, Math.max(12, (hover / n) * 100))}%` }}>
          <b>{Math.ceil(hover / 2)}{hover % 2 === 1 ? "." : "..."} {hm.san}</b> · {CLASS_LABEL[hm.cls]} · {hm.cp > 0 ? "+" : ""}{(hm.cp / 100).toFixed(1)}
        </div>
      )}
    </div>
  );
}
