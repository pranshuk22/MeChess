import { BarChart3, Download, Info } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useMe, useStats } from "@/api/hooks";
import { BarRow, Calendar, QualityBar } from "@/components/charts";
import { MiniBoard } from "@/components/MiniBoard";
import { Button } from "@/components/ui/Button";
import { Badge, EmptyState, Skeleton } from "@/components/ui/Misc";
import { PageHeader, Panel, PanelTitle } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { useDialogs } from "@/state/dialogs";
import type { Bucket, Deep, Habits, OpeningRow, Profile, TacticExample } from "./types";

const pct = (x: number | null | undefined, d = 0) => (x === null || x === undefined ? "–" : `${(100 * x).toFixed(d)}%`);
const PHASES: [string, string][] = [["opening", "Opening"], ["middlegame", "Middlegame"], ["endgame", "Endgame"]];
const SPEEDS = ["bullet", "blitz", "rapid", "classical"];
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);
/** Text colours made from the quality palette, darkened toward the text colour so they read on the page. */
const WARN = "color-mix(in srgb, var(--q-mistake) 40%, var(--text))", GOOD = "color-mix(in srgb, var(--q-best) 60%, var(--text))";

function useProfile(speed: string, colour: string, days: string) {
  return useQuery({ queryKey: ["profile", speed, colour, days], queryFn: () => api<Profile>(`/api/profile?${new URLSearchParams({ ...(speed ? { speed } : {}), ...(colour ? { colour } : {}), ...(days ? { days } : {}) })}`), staleTime: 30_000, placeholderData: (p) => p });
}

function Stacked({ w, d, l, className = "h-2" }: { w: number; d: number; l: number; className?: string }) {
  const n = w + d + l || 1;
  return (
    <span role="img" aria-label={`${w} wins, ${d} draws, ${l} losses`} className={`flex w-full overflow-hidden rounded-full bg-sunken ${className}`}>
      <span style={{ width: `${(100 * w) / n}%`, background: "var(--q-best)" }} /><span style={{ width: `${(100 * d) / n}%`, background: "var(--faint)" }} /><span style={{ width: `${(100 * l) / n}%`, background: "var(--q-blunder)" }} />
    </span>
  );
}

/** Ratings over time, one line per speed, with a y axis and a readout on hover. */
function RatingChart({ series }: { series: Record<string, { date: string; rating: number }[]> }) {
  const [hover, setHover] = useState<{ speed: string; i: number } | null>(null);
  const speeds = Object.keys(series).filter((k) => series[k].length >= 2);
  if (!speeds.length) return <p className="px-5 pb-5 text-[13px] text-muted">Ratings appear here once your games carry them (Lichess and Chess.com games do).</p>;
  const all = speeds.flatMap((k) => series[k].map((p) => p.rating));
  const lo = Math.floor(Math.min(...all) / 50) * 50, hi = Math.ceil(Math.max(...all) / 50) * 50 || lo + 50;
  const W = 600, H = 170, PX = 38, PY = 10;
  const x = (i: number, n: number) => PX + (n <= 1 ? 0 : (i / (n - 1)) * (W - PX - 8));
  const y = (r: number) => PY + (1 - (r - lo) / Math.max(1, hi - lo)) * (H - 2 * PY - 14);
  const colours = ["var(--accent)", "var(--q-great)", "var(--q-mistake)", "var(--q-brilliant)"];
  const ticks = [lo, Math.round((lo + hi) / 2 / 10) * 10, hi];
  const h = hover ? series[hover.speed][hover.i] : null;
  return (
    <div className="px-5 pb-4">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Rating over time" onPointerLeave={() => setHover(null)}>
        {ticks.map((t) => <g key={t}><line x1={PX} x2={W - 8} y1={y(t)} y2={y(t)} stroke="var(--border)" strokeDasharray="3 4" /><text x={PX - 6} y={y(t) + 4} textAnchor="end" fontSize="11" fill="var(--muted)">{t}</text></g>)}
        {speeds.map((k, si) => {
          const pts = series[k];
          const d = pts.map((p, i) => `${i ? "L" : "M"}${x(i, pts.length).toFixed(1)} ${y(p.rating).toFixed(1)}`).join(" ");
          return (
            <g key={k}>
              <path d={d} fill="none" stroke={colours[si % 4]} strokeWidth="1.8" strokeLinejoin="round" />
              {pts.map((p, i) => (i % Math.ceil(pts.length / 60) === 0 || i === pts.length - 1) && <circle key={i} cx={x(i, pts.length)} cy={y(p.rating)} r={hover?.speed === k && hover.i === i ? 4 : 2} fill={colours[si % 4]} onPointerEnter={() => setHover({ speed: k, i })} />)}
            </g>
          );
        })}
        <text x={PX} y={H - 2} fontSize="11" fill="var(--muted)">{series[speeds[0]][0].date}</text><text x={W - 8} y={H - 2} textAnchor="end" fontSize="11" fill="var(--muted)">{series[speeds[0]].at(-1)!.date}</text>
      </svg>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px]">
        {speeds.map((k, si) => <span key={k} className="flex items-center gap-1.5"><span className="h-2 w-2 rounded-full" style={{ background: colours[si % 4] }} /><span className="capitalize text-muted">{k}</span><b className="tnum">{series[k].at(-1)!.rating}</b></span>)}
        <span className="ml-auto tnum text-muted" aria-live="polite">{h ? `${hover!.speed} · ${h.date} · ${h.rating}` : ""}</span>
      </div>
    </div>
  );
}

function Header({ p, loading }: { p: Profile | undefined; loading: boolean }) {
  const me = useMe().data;
  if (!p) return <Skeleton className="h-[148px] rounded-[8px]" />;
  const s = p.summary;
  const perf = s.performance;
  return (
    <Panel className="p-5" aria-busy={loading}>
      <div className="flex flex-wrap items-start gap-x-8 gap-y-4">
        <div className="flex items-center gap-3">
          <span className="grid h-12 w-12 place-items-center rounded-full bg-accent-soft text-[16px] font-semibold text-accent" aria-hidden>{(me?.name ?? "ME").replace(/[^A-Za-z0-9]/g, "").slice(0, 2).toUpperCase() || "ME"}</span>
          <div><div className="text-[17px] font-semibold leading-6">{me?.name ?? "You"}</div><div className="text-[12.5px] text-muted">{s.games.toLocaleString()} games · {s.analysed.toLocaleString()} analysed{me?.since ? ` · since ${me.since}` : ""}</div></div>
        </div>
        <div className="grid flex-1 grid-cols-4 gap-x-6 gap-y-3 max-lg:grid-cols-2 min-w-[300px]">
          <Fact label="Score" value={pct(s.score)} sub={`${s.wins} won · ${s.draws} drawn · ${s.losses} lost`} />
          <Fact label="Accuracy" value={s.accuracy === null ? "–" : s.accuracy.toFixed(1)} sub={s.mistakesPerGame === null ? undefined : `${s.mistakesPerGame.toFixed(1)} mistakes a game`} />
          <Fact label="Performance" value={perf ? String(perf.rating) : "–"} sub={perf ? `by play, last ${perf.games} games (${perf.low}–${perf.high})` : "needs analysed games"} help="Estimated from how often your moves gave away points, compared with players of each rating (Lichess games analysed the same way). A wide range means few moves." />
          <Fact label="By results" value={s.performanceByResult === null ? "–" : String(s.performanceByResult)} sub="opponents' rating and your results" help="Your opponents' average rating plus 400 for every net win (the 400 rule), over the last 50 games with ratings." />
        </div>
      </div>
      <div className="mt-4"><Stacked w={s.wins} d={s.draws} l={s.losses} className="h-2.5" /></div>
    </Panel>
  );
}

const Fact = ({ label, value, sub, help }: { label: string; value: string; sub?: string; help?: string }) => (
  <div title={help}><div className="text-[12px] font-medium text-muted">{label}{help && <Info size={11} className="ml-1 inline text-faint" aria-hidden />}</div><div className="tnum text-[24px] font-semibold leading-8 tracking-[-0.03em]">{value}</div>{sub && <div className="text-[12px] text-muted">{sub}</div>}</div>
);

function Against({ s }: { s: Profile["summary"] }) {
  const rows: [string, Bucket][] = [["Stronger opponents", s.against.stronger], ["Similar opponents", s.against.similar], ["Weaker opponents", s.against.weaker]];
  return (
    <Panel>
      <PanelTitle sub="Opponents more than 100 points above or below your own rating">Results by opponent strength</PanelTitle>
      <div className="space-y-3.5 px-5 pb-5 pt-1">{rows.map(([l, b]) => <BarRow key={l} label={l} value={b.score === null ? null : b.score * 100} right={b.games ? `${pct(b.score)} · ${b.games}` : "no games"} tone={(b.score ?? 0) >= 0.5 ? "good" : "warn"} />)}</div>
    </Panel>
  );
}

function OpeningsTable({ rows }: { rows: OpeningRow[] }) {
  if (!rows.length) return null;
  return (
    <Panel>
      <PanelTitle sub="Click an opening to see those games. Early mistakes: games where you gave away 10 points or more in the first 12 moves. After 12: your average chance of winning at that point.">Your openings</PanelTitle>
      <div className="overflow-x-auto px-2 pb-3">
        <table className="w-full min-w-[720px] text-[13px]">
          <thead><tr className="text-left text-[11.5px] uppercase tracking-wide text-faint"><th className="px-3 py-2 font-semibold">Opening</th><th className="px-3 py-2 font-semibold">Games</th><th className="px-3 py-2 font-semibold">Results</th><th className="px-3 py-2 font-semibold">Score</th><th className="px-3 py-2 font-semibold">Accuracy</th><th className="px-3 py-2 font-semibold">Early mistakes</th><th className="px-3 py-2 font-semibold">After 12</th></tr></thead>
          <tbody>
            {rows.slice(0, 14).map((o) => (
              <tr key={o.name + o.colour} className="border-t border-border/60 hover:bg-surface-2/60">
                <td className="px-3 py-2"><Link to={`/library?${new URLSearchParams({ q: o.name, colour: o.colour })}`} className="font-medium hover:underline"><span className="mr-2 inline-block h-2.5 w-2.5 rounded-full border align-middle" style={{ background: o.colour === "white" ? "#fff" : "#2b3139", borderColor: "var(--border-strong)" }} aria-label={`as ${o.colour}`} />{o.name}</Link>{o.weak && <Badge tone="warn" className="ml-2">needs work</Badge>}{o.strong && <Badge tone="good" className="ml-2">strong</Badge>}</td>
                <td className="tnum px-3 py-2">{o.games}</td><td className="w-28 px-3 py-2"><Stacked w={o.wins} d={o.draws} l={o.losses} /></td>
                <td className="tnum px-3 py-2">{pct(o.score)}</td><td className="tnum px-3 py-2">{o.accuracy === null ? "–" : o.accuracy.toFixed(0)}</td>
                <td className="tnum px-3 py-2">{pct(o.earlyMistakes)}</td><td className="tnum px-3 py-2">{pct(o.after12)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function Phases({ d }: { d: Deep }) {
  const w = d.weakness, ex = d.endgames ?? [];
  return (
    <div className="grid grid-cols-2 gap-5 max-lg:grid-cols-1">
      <Panel>
        <PanelTitle sub={`From ${d.games} games analysed move by move`}>Accuracy by phase</PanelTitle>
        <div className="space-y-3.5 px-5 pb-4 pt-1">{PHASES.map(([k, l]) => { const v = d.accuracyByPhase?.[k] ?? null; return <BarRow key={k} label={l} value={v} right={v === null ? "–" : `${v.toFixed(0)}%`} />; })}</div>
        {w && w.sentences.length > 0 && <ul className="space-y-2 border-t border-border/60 px-5 py-4 text-[13.5px]">{w.sentences.slice(0, 3).map((t, i) => <li key={i}>{t.replace(/ Try: .*$/, "")}</li>)}<li><Link to="/coach" className="text-accent hover:underline">Practise these in the coach</Link></li></ul>}
      </Panel>
      <Panel>
        <PanelTitle sub="Which kinds of endgame cost you most (compared with your other endgames)">Endgames</PanelTitle>
        {ex.length === 0 ? <p className="px-5 pb-5 text-[13px] text-muted">No endgames analysed yet.</p> : <table className="w-full text-[13px]"><tbody>{ex.map((e) => <tr key={e.type} className="border-t border-border/60 first:border-t-0"><td className="px-5 py-2 capitalize">{e.type}{e.weak && <Badge tone="warn" className="ml-2">weak</Badge>}</td><td className="tnum px-2 py-2 text-muted">{e.moves} moves · {e.games} games</td><td className="tnum px-5 py-2 text-right">gives away points on {pct(e.mistakeRate)}</td></tr>)}</tbody></table>}
      </Panel>
    </div>
  );
}

function Tactics({ d }: { d: Deep }) {
  const t = d.tactics;
  if (!t || (!t.table.length && !t.examples.length)) return null;
  return (
    <Panel>
      <PanelTitle sub="Found: you played the tactic. Missed: the engine's better move was one and you played something else. Allowed: your mistake let the opponent play one.">Tactics</PanelTitle>
      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] gap-6 px-5 pb-5 max-lg:grid-cols-1">
        <table className="w-full text-[13px] self-start"><thead><tr className="text-left text-[11.5px] uppercase tracking-wide text-faint"><th className="py-1.5 font-semibold">Tactic</th><th className="py-1.5 text-right font-semibold">Found</th><th className="py-1.5 text-right font-semibold">Missed</th><th className="py-1.5 text-right font-semibold">Allowed</th></tr></thead>
          <tbody>{t.table.map((r) => <tr key={r.motif} className="border-t border-border/60"><td className="py-1.5 capitalize">{r.name.replace(/^an? /, "")}</td><td className="tnum py-1.5 text-right" style={{ color: GOOD }}>{r.found}</td><td className="tnum py-1.5 text-right" style={{ color: r.missed ? WARN : undefined }}>{r.missed}</td><td className="tnum py-1.5 text-right">{r.allowed}</td></tr>)}</tbody></table>
        <div className="grid grid-cols-3 gap-3 max-sm:grid-cols-2">{t.examples.slice(0, 3).map((e) => <Example key={e.game + e.ply} e={e} />)}</div>
      </div>
    </Panel>
  );
}

function Example({ e }: { e: TacticExample }) {
  const turn = e.fen.split(" ")[1] === "w" ? "white" : "black";
  return (
    <Link to={`/review/${encodeURIComponent(e.game)}?ply=${e.ply}`} className="block rounded-[8px] border border-border p-2 hover:border-[var(--border-strong)]" aria-label={`Missed ${e.motif}: ${e.bestSan} instead of ${e.played}`}>
      <MiniBoard fen={e.fen} orientation={turn} arrows={[{ from: e.best.slice(0, 2), to: e.best.slice(2, 4), kind: "best" }, { from: e.playedUci.slice(0, 2), to: e.playedUci.slice(2, 4), kind: "played" }]} size={180} />
      <p className="mt-1.5 text-[12px]"><b>{e.bestSan}</b> was there ({e.motif}); you played {e.played}.</p>
    </Link>
  );
}

function HabitsPanel({ h }: { h: Habits }) {
  const rows = (items: ({ name: string } & Bucket)[]) => items.map((r) => <BarRow key={r.name} label={cap(r.name)} value={r.score === null ? null : r.score * 100} right={`${pct(r.score)} · ${r.games}`} tone={(r.score ?? 0) >= 0.5 ? "good" : "warn"} />);
  if (!h.weekday.length && !h.timeOfDay.length) return null;
  return (
    <Panel>
      <PanelTitle sub="Your score by when you play, and how a session goes (games less than 30 minutes apart). Times are as the games were stamped (UTC).">Habits</PanelTitle>
      <div className="grid grid-cols-3 gap-6 px-5 pb-5 max-lg:grid-cols-1">
        <div className="space-y-3"><h3 className="text-[12px] font-semibold uppercase tracking-wide text-faint">Time of day</h3>{h.timeOfDay.length ? rows(h.timeOfDay) : <p className="text-[13px] text-muted">The games carry no time of day.</p>}</div>
        <div className="space-y-3"><h3 className="text-[12px] font-semibold uppercase tracking-wide text-faint">Weekday</h3>{rows(h.weekday)}</div>
        <div className="space-y-3"><h3 className="text-[12px] font-semibold uppercase tracking-wide text-faint">Within a session</h3>
          {h.sessionPlace.length ? h.sessionPlace.map((r) => <BarRow key={r.place} label={r.place === 5 ? "5th or later" : `Game ${r.place}`} value={r.score === null ? null : r.score * 100} right={`${pct(r.score)} · ${r.games}`} tone={(r.score ?? 0) >= 0.5 ? "good" : "warn"} />) : <p className="text-[13px] text-muted">No sessions found.</p>}
          {h.afterLoss.games > 0 && <p className="pt-1 text-[12.5px] text-muted">After a loss: <b className="text-text">{pct(h.afterLoss.score)}</b> ({h.afterLoss.games}); after a win: <b className="text-text">{pct(h.afterWin.score)}</b> ({h.afterWin.games}).</p>}</div>
      </div>
      {h.sentences.length > 0 && <ul className="space-y-1.5 border-t border-border/60 px-5 py-4 text-[13.5px]">{h.sentences.map((t, i) => <li key={i} className="flex gap-2"><Info size={15} className="mt-0.5 shrink-0 text-accent" />{t}</li>)}</ul>}
    </Panel>
  );
}

function Rest({ d }: { d: Deep }) {
  const c = d.conversion, o = d.opportunism, t = d.time, q = d.quality ?? [];
  return (
    <div className="grid grid-cols-3 gap-5 max-lg:grid-cols-1">
      <Panel>
        <PanelTitle sub="Turning a better position into a win, and saving a worse one">Converting and saving</PanelTitle>
        <div className="space-y-3 px-5 pb-5 pt-1 text-[13.5px]">
          {c && <><BarRow label="Won when clearly better" value={c.hadWinning ? (100 * c.converted) / c.hadWinning : null} right={c.hadWinning ? `${c.converted} of ${c.hadWinning}` : "no games"} /><BarRow label="Saved when clearly worse" value={c.wasLosing ? (100 * c.saved) / c.wasLosing : null} right={c.wasLosing ? `${c.saved} of ${c.wasLosing}` : "no games"} tone="warn" /></>}
          {o && <><BarRow label="Punishing the opponent's mistakes" value={o.opportunism === null ? null : 100 * o.opportunism} right={pct(o.opportunism)} /><BarRow label="Your mistakes left unpunished (luck)" value={o.luck === null ? null : 100 * o.luck} right={pct(o.luck)} tone="warn" /></>}
        </div>
      </Panel>
      <Panel>
        <PanelTitle sub="From the clock of games that carry one">The clock</PanelTitle>
        <div className="space-y-1.5 px-5 pb-5 pt-1 text-[13.5px]">
          {!t || !t.games ? <p className="text-muted">None of these games carry clock times. Games from Lichess and Chess.com imported as PGN do, and games played here do.</p> : <>
            <p>Short of time in <b>{pct(t.troubleShare)}</b> of your games; you score {pct(t.scoreInTrouble ?? null)} then, against {pct(t.scoreOtherwise ?? null)} otherwise.</p>
            {t.mistakeRateLow != null && <p>With little time you give away points on {pct(t.mistakeRateLow)} of your moves, against {pct(t.mistakeRateOk)} with time.</p>}
            <p>{t.flagLosses} of your {t.losses} losses were on time.</p></>}
        </div>
      </Panel>
      <Panel>
        <PanelTitle sub="Mistakes per 100 of your moves, by month">Over time</PanelTitle>
        <div className="space-y-2.5 px-5 pb-5 pt-1">{q.length < 2 ? <p className="text-[13px] text-muted">Needs two months with at least 100 analysed moves each.</p> : q.slice(-6).map((m) => <BarRow key={m.month} label={m.month} value={Math.min(100, m.mistakesPer100 * 5)} right={`${m.mistakesPer100.toFixed(1)}`} tone={m.mistakesPer100 > 9 ? "warn" : "good"} />)}</div>
      </Panel>
    </div>
  );
}

export function InsightsPage() {
  const [sp, setSp] = useSearchParams();
  const speed = sp.get("speed") ?? "", colour = sp.get("colour") ?? "", days = sp.get("days") ?? "";
  const set = (k: string, v: string) => setSp((p) => { const n = new URLSearchParams(p); if (v) n.set(k, v); else n.delete(k); return n; }, { replace: true });
  const { data: p, isLoading, isFetching } = useProfile(speed, colour, days);
  const stats = useStats().data;
  const setImportOpen = useDialogs((s) => s.setImportOpen);
  const empty = useMemo(() => p && p.summary.games === 0, [p]);
  const hasRatings = !!p && Object.values(p.summary.ratings).some((r) => r.length >= 2);
  const hasAgainst = !!p && Object.values(p.summary.against).some((b) => b.games > 0);
  return (
    <div className="mx-auto max-w-[1180px] space-y-5 px-8 py-8 max-md:px-4">
      <PageHeader title="Insights" sub="How you play, from your own games. Every figure can be filtered; the address keeps the filter."
        actions={<div className="flex flex-wrap items-center gap-2">
          <Segmented size="sm" label="Speed" value={speed} onChange={(v) => set("speed", v)} options={[["", "All speeds"], ...SPEEDS.map((s) => [s, cap(s)] as [string, string])]} />
          <Segmented size="sm" label="Colour" value={colour} onChange={(v) => set("colour", v)} options={[["", "Both"], ["white", "White"], ["black", "Black"]]} />
          <Segmented size="sm" label="Period" value={days} onChange={(v) => set("days", v)} options={[["", "All time"], ["365", "Year"], ["90", "90 days"], ["30", "30 days"]]} />
        </div>} />
      {isLoading ? <Skeleton className="h-[420px] rounded-[8px]" /> : empty && !speed && !colour && !days ? (
        <Panel><EmptyState icon={BarChart3} title="No games to learn from yet" text="Import your games and analyse them: this page shows how you play, by opening, phase, habit and tactic." action={<Button variant="primary" onClick={() => setImportOpen(true)}><Download size={15} /> Import games</Button>} /></Panel>
      ) : p && (<>
        <Header p={p} loading={isFetching} />
        {p.summary.games === 0 && <Panel className="p-5 text-[13.5px] text-muted">No games match these filters.</Panel>}
        {hasRatings || hasAgainst ? (
          <div className={`grid gap-5 max-lg:grid-cols-1 ${hasRatings && hasAgainst ? "grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)]" : "grid-cols-1"}`}>
            {hasRatings && <Panel><PanelTitle sub="Your rating in your games, by speed">Rating</PanelTitle><RatingChart series={p.summary.ratings} /></Panel>}
            {hasAgainst && <Against s={p.summary} />}
          </div>
        ) : <Panel className="flex items-center gap-3 px-5 py-3.5 text-[13px] text-muted"><Info size={16} className="shrink-0 text-accent" />These games carry no ratings, so the rating chart and the results by opponent strength are not shown. Games from Lichess and Chess.com have them; you can also give your own rating in <Link to="/settings" className="text-accent underline">Settings</Link>.</Panel>}
        <OpeningsTable rows={p.openings} />
        {p.deep.games > 0 && <Phases d={p.deep} />}
        <Tactics d={p.deep} />
        <HabitsPanel h={p.habits} />
        {p.deep.games > 0 && <Rest d={p.deep} />}
        {stats && <div className="grid grid-cols-2 gap-5 max-lg:grid-cols-1">
          <Panel className="col-span-2 max-lg:col-span-1"><PanelTitle sub="Games per day, last 26 weeks">Activity</PanelTitle><div className="px-5 pb-5"><Calendar days={stats.perDay} /></div></Panel>
          <Panel><PanelTitle sub="How your moves were judged (your last 100 analysed games)">Move quality</PanelTitle><div className="px-5 pb-5"><QualityBar counts={stats.classCounts} /></div></Panel>
        </div>}
      </>)}
    </div>
  );
}
