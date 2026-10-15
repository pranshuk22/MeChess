import { winPercent } from "@/lib/types";

/** Evaluation sparkline of a game: white's win chance over the moves, centre line = equal. */
export function MiniEval({ cps, width = 92, height = 26 }: { cps: number[]; width?: number; height?: number }) {
  if (cps.length < 2) return <span className="text-[12px] text-faint">not analysed</span>;
  const pts = cps.map((c, i) => `${((i / (cps.length - 1)) * width).toFixed(1)},${(height - (winPercent(c) / 100) * height).toFixed(1)}`);
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden className="block">
      <line x1="0" x2={width} y1={height / 2} y2={height / 2} stroke="var(--border-strong)" strokeWidth="1" strokeDasharray="2 3" />
      <polyline points={pts.join(" ")} fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}
