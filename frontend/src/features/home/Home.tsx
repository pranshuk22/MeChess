import { ArrowDownRight, ArrowRight, ArrowUpRight, Check, CircleAlert, Download, Minus, Sparkles, Swords } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { useAnalyse, useDrillStats, useMe, useGame, useGamesPage, useImportLegacy, useStats, useWorkspace } from "@/api/hooks";
import { Board } from "@/board/Board";
import { MiniEval } from "@/components/MiniEval";
import { Calendar, QualityBar } from "@/components/charts";
import { Spark } from "@/components/Spark";
import { Button } from "@/components/ui/Button";
import { Badge, EmptyState, Skeleton, Stat } from "@/components/ui/Misc";
import { PageHeader, Panel, PanelTitle } from "@/components/ui/Panel";
import { formatDate, myAccuracy, opponent, outcome } from "@/lib/format";
import { fensFromUci, START_FEN } from "@/lib/game";
import { useDialogs } from "@/state/dialogs";
import type { GameSummary, S } from "@/lib/types";
import { useMemo } from "react";

const RESULT = { win: ["Win", "good"], loss: ["Loss", "bad"], draw: ["Draw", "neutral"], unknown: ["–", "neutral"] } as const;

function Delta({ now, before, invert = false, unit = "" }: { now: number | null; before: number | null; invert?: boolean; unit?: string }) {
  if (now === null || before === null) return <span className="text-[12px] text-faint">needs more games</span>;
  const d = now - before, good = invert ? d < 0 : d > 0;
  if (Math.abs(d) < 0.05) return <span className="inline-flex items-center gap-1 text-[12px] text-muted"><Minus size={13} /> no change</span>;
  const Icon = d > 0 ? ArrowUpRight : ArrowDownRight;
  return <span className="inline-flex items-center gap-1 text-[12px] font-medium" style={{ color: good ? "var(--q-best)" : "var(--q-mistake)" }}><Icon size={14} /> {Math.abs(d).toFixed(1)}{unit} vs the 20 before</span>;
}

export function HomePage() {
  const stats = useStats(), ws = useWorkspace(), recent = useGamesPage({}, 7), me = useMe().data;
  const setImportOpen = useDialogs((s) => s.setImportOpen);
  const empty = stats.data && stats.data.games === 0 && !ws.isLoading && !ws.data?.checks.some((c) => c.id === "legacy");
  return (
    <div className="mx-auto max-w-[1180px] px-8 py-8 max-md:px-4">
      <PageHeader title="Overview" sub={me?.name ? `Welcome back, ${me.name}.${me.rating ? ` You are rated ${me.rating}${me.mainSpeed ? ` in ${me.mainSpeed}` : ""}.` : ""} How you are playing, from your own analysed games.` : "How you are playing, from your own analysed games."} actions={<Button variant="primary" onClick={() => setImportOpen(true)}><Download size={15} /> Import games</Button>} />
      {empty ? (
        <Panel><EmptyState icon={Swords} title="Bring in your games" text="Import your games from Lichess, Chess.com or a PGN file. They are analysed on this computer and never leave it." action={<Button variant="primary" size="lg" onClick={() => setImportOpen(true)}><Download size={16} /> Import games</Button>} /></Panel>
      ) : (<>
        <StatRow stats={stats.data} loading={stats.isLoading} />
        <div className="mt-5 grid grid-cols-[minmax(0,1fr)_360px] gap-5 max-lg:grid-cols-1">
          <div className="space-y-5">
            <NextStep ws={ws.data} games={recent.data?.items ?? []} />
            <RecentGames games={recent.data?.items} loading={recent.isLoading} total={recent.data?.total ?? 0} />
            {!!stats.data?.openings.length && <Openings openings={stats.data.openings} />}
            {stats.data && <Panel><PanelTitle sub="Games per day, last 26 weeks" right={<Link to="/insights" className="text-[12.5px] font-medium text-accent hover:underline">More insights</Link>}>Activity</PanelTitle><div className="px-5 pb-5"><Calendar days={stats.data.perDay} /></div></Panel>}
          </div>
          <div className="space-y-5">
            {me && me.games > 0 && <YouCard me={me} />}
            <Workspace ws={ws.data} loading={ws.isLoading} />
            {stats.data && Object.keys(stats.data.classCounts).length > 0 && <Panel><PanelTitle sub="Your last 100 analysed games">Move quality</PanelTitle><div className="px-5 pb-5"><QualityBar counts={stats.data.classCounts} /></div></Panel>}
            <PracticeCard />
            <PrepareCard />
          </div>
        </div>
      </>)}
    </div>
  );
}

function StatRow({ stats, loading }: { stats?: S.Stats; loading: boolean }) {
  if (loading || !stats) return <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[108px] rounded-[12px]" />)}</div>;
  const r = stats.results, played = r.win + r.draw + r.loss;
  return (
    <div className="grid grid-cols-4 gap-4 max-lg:grid-cols-2">
      <Stat label="Games" value={stats.games.toLocaleString()} sub={`${stats.analysed.toLocaleString()} analysed`} />
      <Stat label="Accuracy" value={stats.accuracy.recent === null ? "–" : stats.accuracy.recent.toFixed(1)} sub={<Delta now={stats.accuracy.recent} before={stats.accuracy.previous} unit="" />}><Spark values={stats.accuracy.series} domain={[Math.max(0, Math.min(...(stats.accuracy.series.length ? stats.accuracy.series : [50])) - 5), 100]} /></Stat>
      <Stat label="Mistakes per game" value={stats.mistakesPerGame.recent === null ? "–" : stats.mistakesPerGame.recent.toFixed(1)} sub={<Delta now={stats.mistakesPerGame.recent} before={stats.mistakesPerGame.previous} invert />} />
      <Stat label="Results" value={played ? `${Math.round((100 * (r.win + r.draw / 2)) / played)}%` : "–"} sub={played ? `${r.win} wins · ${r.draw} draws · ${r.loss} losses` : "no results yet"}>
        {played > 0 && <div className="mb-1 flex h-9 w-2.5 flex-col-reverse overflow-hidden rounded-full" aria-hidden><span style={{ height: `${(100 * r.win) / played}%`, background: "var(--q-best)" }} /><span style={{ height: `${(100 * r.draw) / played}%`, background: "var(--faint)" }} /><span style={{ height: `${(100 * r.loss) / played}%`, background: "var(--q-blunder)" }} /></div>}
      </Stat>
    </div>
  );
}

function NextStep({ ws, games }: { ws?: S.Workspace; games: GameSummary[] }) {
  const setImportOpen = useDialogs((s) => s.setImportOpen);
  const legacy = useImportLegacy(), analyse = useAnalyse(), nav = useNavigate();
  const step = ws?.next_step;
  const featured = games.find((g) => g.analysed && (g.mistakes ?? 0) > 0) ?? games[0];
  const detail = useGame(featured?.analysed ? featured.id : undefined).data;
  const fen = useMemo(() => {                                                          // the position just before the player's biggest mistake, or the start
    if (!detail || !detail.moves.length) return START_FEN;
    const mine = detail.moves.map((m, i) => ({ m, i })).filter(({ m, i }) => (i % 2 === 0) === (detail.user !== "black") && m.loss >= 0.1).sort((a, b) => b.m.loss - a.m.loss)[0];
    return fensFromUci(detail.moves.map((m) => m.uci))[mine ? mine.i : Math.min(20, detail.moves.length)];
  }, [detail]);
  let title = "Learn from your last game", text: React.ReactNode = featured ? <>You gave away points in <b className="text-text">{featured.mistakes ?? 0} moves</b> against {opponent(featured).name}. Replay them one by one, find the better move, and see why it is better.</> : "Review a game to see where points were lost.";
  let cta: React.ReactNode = featured ? <Link to={`/review/${encodeURIComponent(featured.id)}`}><Button variant="primary" size="lg">Review the game <ArrowRight size={16} /></Button></Link> : null;
  if (step === "set-engine") { title = "Set up the engine"; text = "Analysis needs Stockfish. Install it, then tell MeChess where it is in Settings."; cta = <Link to="/settings"><Button variant="primary" size="lg">Open Settings</Button></Link>; }
  else if (step === "import-legacy") { title = "Bring in your earlier work"; text = "Analysed games from the coach and the command-line tools were found on this computer. Import them into your library."; cta = <Button variant="primary" size="lg" disabled={legacy.isPending} onClick={() => legacy.mutate(undefined, { onSuccess: () => nav("/activity") })}>Import earlier work</Button>; }
  else if (step === "import") { title = "Import your games"; text = "Add your games from Lichess, Chess.com or a PGN file."; cta = <Button variant="primary" size="lg" onClick={() => setImportOpen(true)}>Import games</Button>; }
  else if (step === "analyse") { title = "Analyse your games"; text = "Some games have no analysis yet. Analysis runs in the background; you can keep using the app."; cta = <Button variant="primary" size="lg" disabled={analyse.isPending} onClick={() => analyse.mutate({}, { onSuccess: () => nav("/activity"), onError: () => undefined })}>Analyse new games</Button>; }
  return (
    <Panel className="relative overflow-hidden">
      <div className="grid grid-cols-[212px_1fr] items-center gap-6 p-5 max-sm:grid-cols-1">
        <div className="w-[212px] max-sm:w-44"><Board fen={fen} orientation={featured?.user === "black" ? "black" : "white"} showCoords={false} /></div>
        <div>
          <Badge tone="accent"><Sparkles size={12} className="mr-1" /> Next step</Badge>
          <h2 className="mt-3 text-[21px] font-semibold leading-7 tracking-[-0.025em]">{title}</h2>
          <p className="mt-2 max-w-[46ch] text-[14px] text-muted">{text}</p>
          {cta && <div className="mt-5">{cta}</div>}
        </div>
      </div>
    </Panel>
  );
}

function RecentGames({ games, loading, total }: { games?: GameSummary[]; loading: boolean; total: number }) {
  return (
    <Panel>
      <PanelTitle right={<Link to="/library" className="text-[12.5px] font-medium text-accent hover:underline">All {total.toLocaleString()} games</Link>}>Recent games</PanelTitle>
      <div className="pb-2">
        {loading && [0, 1, 2, 3].map((i) => <div key={i} className="px-5 py-3"><Skeleton className="h-8" /></div>)}
        {games?.map((g) => {
          const [label, tone] = RESULT[outcome(g)], opp = opponent(g), acc = myAccuracy(g);
          return (
            <Link key={g.id} to={`/review/${encodeURIComponent(g.id)}`} className="grid grid-cols-[56px_minmax(0,1fr)_56px_96px] items-center gap-4 px-5 py-2.5 transition-colors hover:bg-surface-2 max-sm:grid-cols-[56px_1fr_56px]">
              <Badge tone={tone} className="justify-center">{label}</Badge>
              <span className="min-w-0"><span className="block truncate text-[13.5px] font-medium">{opp.name}{opp.elo ? <span className="font-normal text-muted"> · {opp.elo}</span> : null}</span><span className="block truncate text-[12px] text-muted">{g.title ?? g.opening ?? "Opening unknown"} · {formatDate(g.date)}</span></span>
              <span className="tnum text-right text-[13px] font-medium">{acc === null ? <span className="text-faint">–</span> : `${acc.toFixed(0)}%`}</span>
              <span className="justify-self-end max-sm:hidden"><MiniEval cps={g.spark} /></span>
            </Link>
          );
        })}
        {games && games.length === 0 && <p className="px-5 py-6 text-[13.5px] text-muted">No games yet.</p>}
      </div>
    </Panel>
  );
}

function Openings({ openings }: { openings: S.OpeningStat[] }) {
  return (
    <Panel>
      <PanelTitle sub="Your most played openings and how you score with them">Openings</PanelTitle>
      <div className="px-5 pb-4">
        {openings.map((o) => (
          <div key={o.name + o.colour} className="grid grid-cols-[minmax(0,1fr)_72px_120px] items-center gap-4 border-t border-border/70 py-2.5 first:border-t-0 text-[13.5px]">
            <span className="truncate font-medium">{o.name} <span className="font-normal text-muted capitalize">· {o.colour}</span></span>
            <span className="tnum text-right text-muted">{o.games} games</span>
            <span className="flex items-center gap-2"><span className="h-1.5 flex-1 overflow-hidden rounded-full bg-sunken"><span className="block h-full rounded-full" style={{ width: `${o.score * 100}%`, background: o.score >= 0.5 ? "var(--q-best)" : "var(--q-mistake)" }} /></span><span className="tnum w-9 text-right text-[12.5px]">{Math.round(o.score * 100)}%</span></span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

function Workspace({ ws, loading }: { ws?: S.Workspace; loading: boolean }) {
  const setImportOpen = useDialogs((s) => s.setImportOpen);
  const legacy = useImportLegacy(), analyse = useAnalyse(), nav = useNavigate();
  const act = (a?: string | null) => {
    if (a === "import") return <Button size="sm" onClick={() => setImportOpen(true)}>Import</Button>;
    if (a === "analyse") return <Button size="sm" disabled={analyse.isPending} onClick={() => analyse.mutate({}, { onSuccess: () => nav("/activity") })}>Analyse</Button>;
    if (a === "import-legacy") return <Button size="sm" disabled={legacy.isPending} onClick={() => legacy.mutate(undefined, { onSuccess: () => nav("/activity") })}>Import</Button>;
    if (a === "set-engine") return <Link to="/settings"><Button size="sm">Settings</Button></Link>;
    return null;
  };
  return (
    <Panel>
      <PanelTitle sub="What MeChess found on this computer">Your workspace</PanelTitle>
      <ul className="px-5 pb-3">
        {loading && [0, 1, 2, 3].map((i) => <li key={i} className="py-2.5"><Skeleton className="h-5" /></li>)}
        {ws?.checks.map((c) => (
          <li key={c.id} className="flex items-center gap-3 border-t border-border/70 py-2.5 first:border-t-0">
            {c.state === "ok" ? <Check size={16} className="shrink-0 text-[var(--q-best)]" /> : c.state === "todo" ? <CircleAlert size={16} className="shrink-0 text-[var(--q-inaccuracy)]" /> : <Minus size={16} className="shrink-0 text-faint" />}
            <div className="min-w-0 flex-1"><div className="text-[13.5px] font-medium">{c.title}</div><div className="truncate text-[12px] text-muted" title={c.detail}>{c.detail}</div></div>
            {act(c.action)}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function YouCard({ me }: { me: S.Me }) {
  const rows = me.ratings.slice(0, 3);
  const best = ["white", "black"].map((c) => ({ colour: c, o: me.openings[c]?.best })).filter((x) => x.o) as { colour: string; o: S.MeOpening }[];
  const weak = ["white", "black"].map((c) => ({ colour: c, o: me.openings[c]?.weakest })).filter((x) => x.o && x.o.score < 0.5) as { colour: string; o: S.MeOpening }[];
  return (
    <Panel>
      <PanelTitle sub={me.since ? `${me.games.toLocaleString()} games since ${formatDate(me.since)}` : undefined}>You</PanelTitle>
      <div className="space-y-4 px-5 pb-5 pt-1">
        {rows.length > 0 && <ul className="space-y-1.5" aria-label="Your ratings">
          {rows.map((r) => (
            <li key={r.speed} className="flex items-baseline gap-2 text-[13.5px]">
              <span className="w-16 capitalize text-muted">{r.speed}</span><b className="tnum font-display text-[18px]">{r.rating}</b>
              {r.change !== null && r.change !== 0 && <span className="tnum text-[12px] font-medium" style={{ color: r.change > 0 ? "var(--q-best)" : "var(--q-mistake)" }}>{r.change > 0 ? "+" : ""}{r.change} in 30 days</span>}
              <span className="ml-auto text-[12px] text-faint">{r.games} games</span>
            </li>
          ))}
        </ul>}
        {(best.length > 0 || weak.length > 0) && <div className="space-y-1.5 text-[13px]">
          {best.map(({ colour, o }) => <p key={"b" + colour}><Badge tone="good">your best</Badge> <span className="ml-1">As {colour}: <b>{o.name}</b>, {Math.round(o.score * 100)}% in {o.games} games</span></p>)}
          {weak.map(({ colour, o }) => <p key={"w" + colour}><Badge tone="warn">needs work</Badge> <span className="ml-1">As {colour}: <b>{o.name}</b>, {Math.round(o.score * 100)}% in {o.games} games</span></p>)}
        </div>}
        {me.rating ? <p className="text-[12.5px] text-muted">The explorer, the opening practice and the play page start from your level.</p>
          : <p className="text-[12.5px] text-muted">Your games carry no rating. <Link to="/settings" className="text-accent underline">Add your user name and rating in Settings</Link> and the explorer, the opening practice and the play page start from your level.</p>}
      </div>
    </Panel>
  );
}

function PrepareCard() {
  return (
    <Panel>
      <PanelTitle sub="Playing someone you know?">Prepare against an opponent</PanelTitle>
      <div className="px-5 pb-5">
        <p className="text-[13.5px] text-muted">Give their user name. You get their weak openings, the traps in their games and a plan of what to play against them.</p>
        <Link to="/prepare"><Button className="mt-3 w-full">Prepare</Button></Link>
      </div>
    </Panel>
  );
}

function PracticeCard() {
  const d = useDrillStats().data;
  return (
    <Panel>
      <PanelTitle sub="Positions from your own mistakes">Practice</PanelTitle>
      <div className="px-5 pb-5">
        {d && d.total > 0 ? <p className="text-[13.5px] text-muted"><b className="tnum font-display text-[22px] text-text">{d.due}</b> {d.due === 1 ? "position is" : "positions are"} due, of {d.total}.</p>
          : <p className="text-[13.5px] text-muted">They come from your analysed games and return after a day, then after longer gaps once you get them right.</p>}
        <Link to="/coach"><Button className="mt-3 w-full" variant={d?.due ? "primary" : "secondary"}>{d?.due ? "Practise now" : "Open the coach"}</Button></Link>
      </div>
    </Panel>
  );
}
