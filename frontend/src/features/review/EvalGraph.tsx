import { useMemo } from "react";
import { winPercent, type AnalysedMove } from "@/lib/types";

const W = 320, H = 72;
/** The game's evaluation as white's share of the position: white fill below the line on a dark track (like the eval bar); click to jump; the player's mistakes are dotted. */
export function EvalGraph({ moves, ply, onSelect, userIsWhite }: { moves: AnalysedMove[]; ply: number; onSelect: (ply: number) => void; userIsWhite: boolean }) {
  const n = moves.length;
  const x = (i: number) => (n <= 1 ? 0 : (i / n) * W);
  const y = (cp: number) => H - (winPercent(cp) / 100) * H;
  const { line, area, dots } = useMemo(() => {
    const pts = [[0, H / 2], ...moves.map((m, i) => [x(i + 1), y(m.cp)])];
    const line = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    const dots = moves.flatMap((m, i) => (m.loss >= 0.1 && (i % 2 === 0) === userIsWhite && (m.cls === "mistake" || m.cls === "blunder" || m.cls === "miss") ? [{ i: i + 1, cx: x(i + 1), cy: y(m.cp), cls: m.cls }] : []));
    return { line, area: `${line} L ${W} ${H} L 0 ${H} Z`, dots };
  }, [moves, userIsWhite]);                                             // eslint-disable-line react-hooks/exhaustive-deps
  const pick = (e: React.MouseEvent<SVGSVGElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    onSelect(Math.max(0, Math.min(n, Math.round(((e.clientX - r.left) / r.width) * n))));
  };
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="block h-[72px] w-full cursor-pointer overflow-hidden rounded-[8px]" preserveAspectRatio="none" onClick={pick} role="img" aria-label="Evaluation graph: click to jump to a move">
      <rect width={W} height={H} fill="#2b3139" />
      <path d={area} fill="#f4f6f8" />
      <line x1="0" x2={W} y1={H / 2} y2={H / 2} stroke="#8a95a1" strokeWidth="1" strokeDasharray="3 4" opacity="0.7" vectorEffect="non-scaling-stroke" />
      <path d={line} fill="none" stroke="var(--accent)" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
      {dots.map((d) => <circle key={d.i} cx={d.cx} cy={d.cy} r="2.8" fill={d.cls === "blunder" ? "var(--q-blunder)" : "var(--q-mistake)"} stroke="#fff" strokeWidth="0.8" />)}
      <line x1={x(ply)} x2={x(ply)} y1="0" y2={H} stroke="var(--accent)" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
