import { winPercent, type AnalysedMove } from "@/lib/types";

/** A tiny evaluation sparkline (white's win chance over the game). */
export function MiniEval({ moves, width = 96, height = 24 }: { moves: AnalysedMove[]; width?: number; height?: number }) {
  if (moves.length < 2) return null;
  const pts = moves.map((m, i) => `${((i / (moves.length - 1)) * width).toFixed(1)},${(height - (winPercent(m.cp) / 100) * height).toFixed(1)}`);
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden className="block">
      <line x1="0" x2={width} y1={height / 2} y2={height / 2} stroke="var(--border)" strokeWidth="1" />
      <polyline points={pts.join(" ")} fill="none" stroke="var(--accent)" strokeWidth="1.4" strokeLinejoin="round" />
    </svg>
  );
}
