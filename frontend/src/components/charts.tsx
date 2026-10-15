import clsx from "clsx";
import { CLASS_LABEL, CLASS_ORDER, CLASS_VAR, type MoveClass } from "@/lib/types";

/** A line chart for a series over time: soft area, the last point marked, min and max printed. */
export function LineChart({ values, labels, height = 120, format = (v: number) => String(Math.round(v)) }: { values: number[]; labels?: string[]; height?: number; format?: (v: number) => string }) {
  if (values.length < 2) return <p className="py-6 text-center text-[13px] text-muted">Not enough games yet.</p>;
  const W = 600, pad = 8;
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1;
  const pts = values.map((v, i) => [pad + (i / (values.length - 1)) * (W - 2 * pad), pad + (1 - (v - lo) / span) * (height - 2 * pad)]);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
  const last = pts.at(-1)!;
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${height}`} className="block w-full" preserveAspectRatio="none" role="img" aria-label={`Chart from ${format(values[0])} to ${format(values.at(-1)!)}`} style={{ height }}>
        <path d={`${line} L${W - pad} ${height} L${pad} ${height} Z`} fill="var(--accent)" opacity="0.1" />
        <path d={line} fill="none" stroke="var(--accent)" strokeWidth="2" vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
        <circle cx={last[0]} cy={last[1]} r="3.5" fill="var(--accent)" stroke="var(--surface)" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="tnum mt-1 flex justify-between text-[11.5px] text-faint"><span>{labels?.[0]}</span><span>low {format(lo)} · high {format(hi)}</span><span>{labels?.at(-1)}</span></div>
    </div>
  );
}

/** Games per day over the last half year, one cell per day, weeks in columns. */
export function Calendar({ days, weeks = 26 }: { days: { date: string; games: number }[]; weeks?: number }) {
  const map = new Map(days.map((d) => [d.date, d.games]));
  const today = new Date();
  const end = new Date(Date.UTC(today.getFullYear(), today.getMonth(), today.getDate()));
  const start = new Date(end); start.setUTCDate(end.getUTCDate() - ((end.getUTCDay() + 6) % 7) - (weeks - 1) * 7);       // a Monday
  const cols: { date: string; n: number }[][] = [];
  for (let w = 0; w < weeks; w++) {
    const col = [];
    for (let d = 0; d < 7; d++) {
      const dt = new Date(start); dt.setUTCDate(start.getUTCDate() + w * 7 + d);
      const key = dt.toISOString().slice(0, 10);
      col.push({ date: key, n: dt > end ? -1 : map.get(key) ?? 0 });
    }
    cols.push(col);
  }
  const level = (n: number) => (n <= 0 ? 0 : n < 3 ? 1 : n < 6 ? 2 : n < 10 ? 3 : 4);
  const total = days.reduce((a, d) => a + d.games, 0);
  return (
    <div>
      <div className="flex gap-[3px] overflow-x-auto pb-1" role="img" aria-label={`${total} games in the last ${weeks} weeks`}>
        {cols.map((col, i) => (
          <div key={i} className="flex flex-col gap-[3px]">
            {col.map((c) => <span key={c.date} title={c.n < 0 ? "" : `${c.date}: ${c.n} game${c.n === 1 ? "" : "s"}`} className={clsx("h-[11px] w-[11px] rounded-[3px]", c.n < 0 && "opacity-0")}
              style={{ background: level(c.n) === 0 ? "var(--sunken)" : `color-mix(in srgb, var(--accent) ${[0, 28, 50, 75, 100][level(c.n)]}%, var(--sunken))` }} />)}
          </div>
        ))}
      </div>
      <div className="mt-2 flex items-center justify-between text-[11.5px] text-faint"><span>{total.toLocaleString()} games in {weeks} weeks</span>
        <span className="flex items-center gap-1">less {[0, 1, 2, 3, 4].map((l) => <span key={l} className="h-[10px] w-[10px] rounded-[2px]" style={{ background: l === 0 ? "var(--sunken)" : `color-mix(in srgb, var(--accent) ${[0, 28, 50, 75, 100][l]}%, var(--sunken))` }} />)} more</span></div>
    </div>
  );
}

/** How the player's moves are spread over the move kinds, as one stacked bar with a legend. */
export function QualityBar({ counts }: { counts: Record<string, number> }) {
  const total = CLASS_ORDER.reduce((a, c) => a + (counts[c] ?? 0), 0);
  if (!total) return <p className="py-4 text-center text-[13px] text-muted">Analyse some games to see this.</p>;
  return (
    <div>
      <div className="flex h-3.5 overflow-hidden rounded-full" role="img" aria-label="Move kinds">
        {CLASS_ORDER.filter((c) => counts[c]).map((c) => <span key={c} style={{ width: `${(100 * counts[c]) / total}%`, background: CLASS_VAR[c] }} title={`${CLASS_LABEL[c as MoveClass]}: ${counts[c]}`} />)}
      </div>
      <ul className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-[12.5px]">
        {CLASS_ORDER.filter((c) => counts[c]).map((c) => (
          <li key={c} className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full" style={{ background: CLASS_VAR[c] }} /><span className="flex-1">{CLASS_LABEL[c as MoveClass]}</span><span className="tnum text-muted">{((100 * counts[c]) / total).toFixed(1)}%</span></li>
        ))}
      </ul>
    </div>
  );
}

export function BarRow({ label, value, max = 100, right, tone = "accent" }: { label: string; value: number | null; max?: number; right?: string; tone?: "accent" | "good" | "warn" }) {
  const colour = tone === "good" ? "var(--q-best)" : tone === "warn" ? "var(--q-mistake)" : "var(--accent)";
  return (
    <div className="grid grid-cols-[96px_1fr_64px] items-center gap-3 text-[13px]">
      <span className="capitalize text-muted">{label}</span>
      <span className="h-2 overflow-hidden rounded-full bg-sunken"><span className="block h-full rounded-full transition-[width] duration-500" style={{ width: `${value === null ? 0 : Math.min(100, (100 * value) / max)}%`, background: colour }} /></span>
      <span className="tnum text-right font-medium">{right ?? (value === null ? "–" : value.toFixed(0))}</span>
    </div>
  );
}
