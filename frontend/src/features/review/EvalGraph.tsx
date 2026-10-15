import { useMemo } from "react";
import { winPercent, type AnalysedMove } from "@/lib/types";

const W = 320, H = 64;
/** The game's evaluation as white's win chance; click to jump to a ply. Marks the user's mistakes. */
export function EvalGraph({ moves, ply, onSelect, userIsWhite }: { moves: AnalysedMove[]; ply: number; onSelect: (ply: number) => void; userIsWhite: boolean }) {
  const n = moves.length;
  const x = (i: number) => (n <= 1 ? 0 : (i / n) * W);                  // index 0 = start position
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
    <svg viewBox={`0 0 ${W} ${H}`} className="block h-16 w-full cursor-pointer" preserveAspectRatio="none" onClick={pick} role="img" aria-label="Evaluation graph: click to jump to a move">
      <rect width={W} height={H} fill="var(--surface-2)" rx="4" />
      <path d={area} fill="var(--surface)" opacity="0.9" />
      <line x1="0" x2={W} y1={H / 2} y2={H / 2} stroke="var(--border)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      <path d={line} fill="none" stroke="var(--accent)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
      {dots.map((d) => <circle key={d.i} cx={d.cx} cy={d.cy} r="2.6" fill={d.cls === "blunder" ? "var(--q-blunder)" : "var(--q-mistake)"} />)}
      <line x1={x(ply)} x2={x(ply)} y1="0" y2={H} stroke="var(--text)" strokeWidth="1.2" opacity="0.55" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
