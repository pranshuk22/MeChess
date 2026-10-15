/** A small line chart for a handful of values (accuracy over the last games, evaluation over a game). */
export function Spark({ values, width = 88, height = 32, domain, area = true }: { values: number[]; width?: number; height?: number; domain?: [number, number]; area?: boolean }) {
  if (values.length < 2) return <div style={{ width, height }} />;
  const [lo, hi] = domain ?? [Math.min(...values), Math.max(...values)];
  const span = hi - lo || 1, pad = 3;
  const pts = values.map((v, i) => [(i / (values.length - 1)) * width, pad + (1 - (v - lo) / span) * (height - 2 * pad)]);
  const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} aria-hidden className="block shrink-0 overflow-visible">
      {area && <path d={`${line} L${width} ${height} L0 ${height} Z`} fill="var(--accent)" opacity="0.1" />}
      <path d={line} fill="none" stroke="var(--accent)" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={pts.at(-1)![0]} cy={pts.at(-1)![1]} r="2.4" fill="var(--accent)" />
    </svg>
  );
}
