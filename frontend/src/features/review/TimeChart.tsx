import { useMemo } from "react";

const W = 400, H = 70;

/** Time spent on each move: White's bars grow up, Black's down, from the middle line; a move played with under a tenth of the starting time on the clock is drawn in the warning colour.
 *  `clocks[i]` is the seconds left for the mover after half-move i + 1; the increment is added back when the time spent is worked out. */
export function TimeChart({ clocks, base, inc, ply, onSelect }: { clocks: (number | null)[]; base: number | null; inc: number | null; ply: number; onSelect: (ply: number) => void }) {
  const n = clocks.length;
  const bars = useMemo(() => {
    return clocks.map((c, i) => {
      const prev = i >= 2 ? clocks[i - 2] : base;
      const spent = c !== null && prev !== null && prev !== undefined ? Math.max(0, prev - c + (inc ?? 0)) : null;
      return { spent, low: c !== null && base ? c < 0.1 * base : false };
    });
  }, [clocks, base, inc]);
  const max = Math.max(1, ...bars.map((b) => Math.min(b.spent ?? 0, 60)));
  const bw = W / Math.max(1, n);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="block h-[70px] w-full cursor-pointer overflow-hidden rounded-[6px] bg-sunken" preserveAspectRatio="none" role="img" aria-label="Time spent per move: White above the line, Black below; click to jump to a move"
      onClick={(e) => { const r = e.currentTarget.getBoundingClientRect(); onSelect(Math.max(0, Math.min(n, Math.round(((e.clientX - r.left) / r.width) * n)))); }}>
      <line x1="0" x2={W} y1={H / 2} y2={H / 2} stroke="var(--border-strong)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      {bars.map((b, i) => {
        if (b.spent === null) return null;
        const h = Math.max(1, (Math.min(b.spent, 60) / max) * (H / 2 - 3));
        const white = i % 2 === 0;
        return <rect key={i} x={i * bw + bw * 0.12} width={bw * 0.76} y={white ? H / 2 - h : H / 2} height={h} fill={b.low ? "var(--q-mistake)" : white ? "var(--text)" : "var(--muted)"} opacity={b.low ? 1 : 0.75} />;
      })}
      <line x1={(ply / Math.max(1, n)) * W} x2={(ply / Math.max(1, n)) * W} y1="0" y2={H} stroke="var(--accent)" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}
