import * as Tabs from "@radix-ui/react-tabs";
import clsx from "clsx";
import { AlertTriangle, BookMarked, ChevronDown, ChevronRight, ExternalLink, Info, Swords, Target } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Arrow } from "@/board/Arrows";
import { Board } from "@/board/Board";
import { Button } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Segmented";
import { Badge, EmptyState } from "@/components/ui/Misc";
import { Panel, PanelTitle } from "@/components/ui/Panel";
import { formatDate } from "@/lib/format";
import type { Colour, Family, MatchupRow, Moment, Openings, Plan, PlanNode, Report, Trap } from "./types";

const pct = (x: number | null | undefined, digits = 0) => (x === null || x === undefined ? "–" : `${(100 * x).toFixed(digits)}%`);
const other = (c: Colour): Colour => (c === "white" ? "black" : "white");
/** Text colours from the move-quality palette, darkened towards the text colour so that they read well on the page (the palette colours are made for fills). */
const BAD = "color-mix(in srgb, var(--q-blunder) 55%, var(--text))", WARN = "color-mix(in srgb, var(--q-mistake) 40%, var(--text))";
const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** "3.Nf3" or "3...Nf6" for the move that led to `fen` (the position AFTER the move). */
function numbered(san: string, fen: string) {
  const [, turn, , , , full] = fen.split(" ");
  return turn === "b" ? `${full}.${san}` : `${Number(full) - 1}...${san}`;
}

function MiniBoard({ fen, orientation, arrows = [], size = 280 }: { fen: string; orientation: Colour; arrows?: Arrow[]; size?: number }) {
  return <div className="w-full overflow-hidden rounded-[6px] shadow-[0_1px_2px_rgba(16,24,32,0.12),0_8px_24px_-12px_rgba(16,24,32,0.3)]" style={{ maxWidth: size }}><Board fen={fen} orientation={orientation} movable={null} arrows={arrows} /></div>;
}

function ScoreBar({ w, d, l }: { w: number; d: number; l: number }) {
  const n = w + d + l || 1;
  return (
    <span role="img" className="flex h-2 w-24 overflow-hidden rounded-full bg-sunken" title={`${w} wins, ${d} draws, ${l} losses`} aria-label={`${w} wins, ${d} draws, ${l} losses`}>
      <span style={{ width: `${(100 * w) / n}%`, background: "var(--q-best)" }} /><span style={{ width: `${(100 * d) / n}%`, background: "var(--faint)" }} /><span style={{ width: `${(100 * l) / n}%`, background: "var(--q-blunder)" }} />
    </span>
  );
}

export function ReportView({ prepId, report }: { prepId: string; report: Report }) {
  const o = report.opponent;
  return (
    <div className="space-y-5">
      {report.notes.length > 0 && (
        <Panel className="space-y-1.5 p-4" role="note">{report.notes.map((n, i) => <p key={i} className="flex gap-2 text-[13px] text-muted"><Info size={15} className="mt-0.5 shrink-0" />{n}</p>)}</Panel>
      )}
      <div className="grid grid-cols-[minmax(0,1fr)_320px] gap-5 max-lg:grid-cols-1">
        <Panel>
          <PanelTitle sub="What this preparation says, in a few lines">The short version</PanelTitle>
          <ul className="space-y-2.5 px-5 pb-5 pt-2 text-[14px]">
            {report.headline.length ? report.headline.map((h, i) => <li key={i} className="flex gap-2.5"><Target size={16} className="mt-[3px] shrink-0 text-accent" /><span>{h}</span></li>) : <li className="text-muted">Not enough games to say much yet.</li>}
          </ul>
        </Panel>
        <Panel>
          <PanelTitle>The opponent</PanelTitle>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2 px-5 pb-5 pt-2 text-[13px]">
            <dt className="text-muted">Rating</dt><dd className="tnum text-right">{o.rating ?? "–"}</dd>
            <dt className="text-muted">Games read</dt><dd className="tnum text-right">{o.games.toLocaleString()}</dd>
            <dt className="text-muted">As White / Black</dt><dd className="tnum text-right">{o.white} / {o.black}</dd>
            <dt className="text-muted">Their score</dt><dd className="tnum text-right">{pct(o.score)}</dd>
            <dt className="text-muted">Period</dt><dd className="tnum text-right">{o.from ? `${formatDate(o.from)} – ${formatDate(o.to)}` : "–"}</dd>
            <dt className="text-muted">Speeds</dt><dd className="text-right">{Object.entries(o.speeds).map(([k, v]) => `${k} ${v}`).join(", ")}</dd>
            <dt className="text-muted">Analysed in full</dt><dd className="tnum text-right">{report.weakness.games}</dd>
          </dl>
        </Panel>
      </div>

      <Tabs.Root defaultValue="plan">
        <Tabs.List className="mb-4 flex max-w-full gap-1 overflow-x-auto rounded-[9px] bg-sunken p-0.5 [scrollbar-width:none] md:inline-flex" aria-label="Report sections">
          {[["plan", "Your plan"], ["openings", "Their openings"], ["traps", "Traps"], ["later", "Middlegame and endgame"], ["games", "Their games"]].map(([v, l]) => (
            <Tabs.Trigger key={v} value={v} className="h-8 shrink-0 whitespace-nowrap rounded-[7px] px-4 text-[13px] font-medium text-muted data-[state=active]:bg-surface data-[state=active]:text-text data-[state=active]:shadow-[var(--shadow-sm)] cursor-pointer">{l}</Tabs.Trigger>
          ))}
        </Tabs.List>
        <Tabs.Content value="plan" className="outline-none"><PlanTab prepId={prepId} report={report} /></Tabs.Content>
        <Tabs.Content value="openings" className="outline-none"><OpeningsTab report={report} /></Tabs.Content>
        <Tabs.Content value="traps" className="outline-none"><TrapsTab report={report} /></Tabs.Content>
        <Tabs.Content value="later" className="outline-none"><LaterTab report={report} /></Tabs.Content>
        <Tabs.Content value="games" className="outline-none"><GamesTab report={report} /></Tabs.Content>
      </Tabs.Root>
    </div>
  );
}

// ---- the plan --------------------------------------------------------------------------------------------------------------------------------------

function Outline({ nodes, depth, selected, onSelect }: { nodes: PlanNode[]; depth: number; selected: string; onSelect: (n: PlanNode) => void }) {
  return (
    <ul className={clsx(depth > 0 && "ml-3 border-l border-border pl-2")} role={depth === 0 ? "tree" : "group"}>
      {nodes.map((n) => <OutlineRow key={n.fen + n.uci} node={n} depth={depth} selected={selected} onSelect={onSelect} />)}
    </ul>
  );
}
function OutlineRow({ node: n, depth, selected, onSelect }: { node: PlanNode; depth: number; selected: string; onSelect: (n: PlanNode) => void }) {
  const [open, setOpen] = useState(depth < 5);
  const you = n.by === "you", bad = !you && (n.loss ?? 0) >= 0.08;
  return (
    <li role="treeitem" aria-expanded={n.children.length ? open : undefined} aria-selected={selected === n.fen}>
      <div className={clsx("flex items-center gap-1.5 rounded-[7px] px-1.5 py-1 text-[13.5px]", selected === n.fen && "bg-accent-soft")}>
        {n.children.length ? <button aria-label={open ? "Collapse" : "Expand"} onClick={() => setOpen(!open)} className="cursor-pointer text-muted">{open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}</button> : <span className="w-[14px]" />}
        <button className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-left" onClick={() => onSelect(n)}>
          {you ? <Badge tone="accent">You</Badge> : <Badge>They</Badge>}
          <span className={clsx("font-mono", you && "font-semibold")}>{numbered(n.san, n.fen)}</span>
          {you ? <span className="text-[12px] text-muted">expect {pct(n.value)}</span> : <span className="text-[12px] text-muted">{pct(n.p)} of their games{n.games ? ` (${n.games})` : ""}</span>}
          {bad && <Badge tone="warn">gives away {pct(n.loss)}</Badge>}
          {you && (n.cost ?? 0) >= 0.03 && <Badge tone="warn" title="Slightly weaker than the engine's move, chosen because this opponent has often gone wrong after it">gamble: {pct(n.cost)} below best</Badge>}
        </button>
      </div>
      {open && n.children.length > 0 && <Outline nodes={n.children} depth={depth + 1} selected={selected} onSelect={onSelect} />}
    </li>
  );
}

function PlanTab({ prepId, report }: { prepId: string; report: Report }) {
  const [colour, setColour] = useState<Colour>("white");
  const plan: Plan = report.plan[colour];
  const [sel, setSel] = useState<PlanNode | null>(null);
  const qc = useQueryClient();
  const save = useMutation({ mutationFn: () => api<{ id: string; name: string }>(`/api/prep/${prepId}/repertoire`, { method: "POST", json: { colour } }), onSuccess: () => qc.invalidateQueries({ queryKey: ["repertoires"] }) });
  const tree = plan.tree;
  const shown = sel && tree ? sel : null;
  const lastYou = shown?.by === "you";
  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center gap-3">
        <Segmented label="Your colour" value={colour} onChange={(c) => { setColour(c); setSel(null); }} options={[["white", "You play White"], ["black", "You play Black"]]} />
        {tree && <span className="text-[13px] text-muted">Expected score <b className="text-text">{pct(tree.value)}</b> against what they really play, {tree.gain >= 0 ? "+" : ""}{(100 * tree.gain).toFixed(1)} points compared with best play from both sides.</span>}
      </div>
      {!tree ? <Panel><EmptyState icon={Swords} title="No plan for this colour" text={plan.reason} /></Panel> : (
        <div className="grid grid-cols-[minmax(0,1fr)_340px] gap-5 max-lg:grid-cols-1">
          <Panel className="p-3">
            <div className="px-2 pb-2 pt-1 text-[12.5px] text-muted">Your moves are in bold. After each of them the replies this opponent has actually played are listed with how often. Click a move to see the position.</div>
            <Outline nodes={tree.children} depth={0} selected={shown?.fen ?? ""} onSelect={setSel} />
          </Panel>
          <div className="space-y-4 lg:sticky lg:top-4 lg:self-start">
            <Panel className="p-4">
              <MiniBoard fen={shown?.fen ?? tree.fen} orientation={colour} size={320} arrows={shown ? [{ from: shown.uci.slice(0, 2), to: shown.uci.slice(2, 4), kind: lastYou ? "best" : "played" }] : []} />
              <div className="mt-3 text-[13px]" aria-live="polite">
                {!shown && <p className="text-muted">Pick a move in the list.</p>}
                {shown && lastYou && <>
                  <p><b>{numbered(shown.san, shown.fen)}</b>: expected score <b>{pct(shown.value)}</b>; the engine alone says {pct(shown.engine)} here.</p>
                  {(shown.cost ?? 0) >= 0.03 && <p className="mt-1.5" style={{ color: WARN }}>A gamble: the engine's best move is about {pct(shown.cost)} stronger. It is chosen because this opponent has often gone wrong after it; if they find the right replies you are slightly worse off.</p>}
                  {shown.usual && shown.usual.san !== shown.san && <p className="mt-1.5 text-muted">You usually play {shown.usual.san} here ({shown.usual.games} games, score {pct(shown.usual.score)}).</p>}
                  {!!shown.yourGames && <p className="mt-1.5 text-muted">You have played this move {shown.yourGames} time{shown.yourGames === 1 ? "" : "s"}{shown.yourScore !== null && shown.yourScore !== undefined ? `, scoring ${pct(shown.yourScore)}` : ""}.</p>}
                  {!!shown.alts?.length && <p className="mt-1.5 text-muted">Also sound: {shown.alts.map((a) => `${a.san} (${pct(a.value)})`).join(", ")}.</p>}
                </>}
                {shown && !lastYou && <>
                  <p><b>{numbered(shown.san, shown.fen)}</b> in {pct(shown.p)} of their games here ({shown.games}); they scored {pct(shown.score ?? null)} with it.</p>
                  {(shown.loss ?? 0) >= 0.08 ? <p className="mt-1.5" style={{ color: WARN }}>The engine says this move gives away {pct(shown.loss)}: your chance to take over.</p> : <p className="mt-1.5 text-muted">A sound move by the engine's measure.</p>}
                </>}
              </div>
            </Panel>
            <Panel className="p-4">
              <Button className="w-full" onClick={() => save.mutate()} disabled={save.isPending || save.isSuccess}><BookMarked size={15} /> {save.isSuccess ? "Saved as a repertoire" : "Save as a repertoire to practise"}</Button>
              {save.isSuccess && <p className="mt-2 text-[12.5px] text-muted">Practise it in <Link to="/coach" className="text-accent underline">Coach → Openings</Link>.</p>}
              {save.isError && <p role="alert" className="mt-2 text-[12.5px] text-[var(--q-blunder)]">{(save.error as Error).message}</p>}
            </Panel>
          </div>
        </div>
      )}
      {tree && !!plan.lines?.length && (
        <Panel>
          <PanelTitle sub="The lines you are most likely to reach, with the chance they happen">Likeliest lines</PanelTitle>
          <ol className="divide-y divide-border/60 px-5 pb-3 pt-1 text-[13.5px]">
            {plan.lines.map((l, i) => <li key={i} className="flex items-baseline gap-3 py-2"><span className="tnum w-12 shrink-0 text-right text-[12.5px] text-muted">{pct(l.p)}</span><span className="font-mono">{l.moves}</span>{l.value !== null && <span className="ml-auto text-[12px] text-muted">{pct(l.value)}</span>}</li>)}
          </ol>
        </Panel>
      )}
    </div>
  );
}

// ---- their openings --------------------------------------------------------------------------------------------------------------------------------

function FamilyTable({ title, data, mine }: { title: string; data: Openings; mine: Map<string, MatchupRow> }) {
  if (!data.games) return <Panel><PanelTitle>{title}</PanelTitle><p className="px-5 pb-5 pt-2 text-[13px] text-muted">No games with this colour.</p></Panel>;
  return (
    <Panel>
      <PanelTitle sub={`${data.games} games, they score ${pct(data.overall)} overall`}>{title}</PanelTitle>
      <div className="overflow-x-auto px-2 pb-3">
        <table className="w-full min-w-[640px] text-[13px]">
          <thead><tr className="text-left text-[11.5px] uppercase tracking-wide text-faint"><th className="px-3 py-2 font-semibold">Opening</th><th className="px-3 py-2 font-semibold">Games</th><th className="px-3 py-2 font-semibold">Results</th><th className="px-3 py-2 font-semibold">Score</th><th className="px-3 py-2 font-semibold">Early errors</th><th className="px-3 py-2 font-semibold">You against it</th></tr></thead>
          <tbody>
            {data.families.slice(0, 12).map((f: Family) => {
              const m = mine.get(f.name);
              return (
                <tr key={f.name} className="border-t border-border/60 align-top">
                  <td className="px-3 py-2"><div className="font-medium">{f.name}</div>{f.weak && <div className="mt-1 flex flex-wrap gap-1">{f.why.map((w) => <Badge key={w} tone="warn"><AlertTriangle size={11} className="mr-1" />{w}</Badge>)}</div>}</td>
                  <td className="tnum px-3 py-2">{f.games} <span className="text-faint">({pct(f.share)})</span></td>
                  <td className="px-3 py-2"><ScoreBar w={f.wins} d={f.draws} l={f.losses} /></td>
                  <td className="tnum px-3 py-2">{pct(f.score)}</td>
                  <td className="tnum px-3 py-2">{f.earlyMistakes === null ? <span className="text-faint">not analysed</span> : pct(f.earlyMistakes)}</td>
                  <td className="tnum px-3 py-2">{m && m.yourGames ? <>{m.yourGames} games, {pct(m.yourScore)}</> : <span className="text-faint">no games yet</span>}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function OpeningsTab({ report }: { report: Report }) {
  // `plan[you].matchup` holds, for the opponent's colour, your record against each of their opening families
  const byOpp = (opp: Colour) => new Map((report.plan[other(opp)].matchup ?? []).map((m) => [m.name, m]));
  return (
    <div className="space-y-5">
      <p className="text-[13px] text-muted">An opening is marked when they score clearly below their usual with it, or often make a mistake in its first 12 moves (at least 4 games). Early errors are the share of their games with a mistake of at least 10 points in that stretch.</p>
      <FamilyTable title="When they have White" data={report.openings.white} mine={byOpp("white")} />
      <FamilyTable title="When they have Black" data={report.openings.black} mine={byOpp("black")} />
      <YourOpenings report={report} />
    </div>
  );
}

function YourOpenings({ report }: { report: Report }) {
  if (!report.you.games) return <Panel className="p-5 text-[13px] text-muted">Import your own games to see here what you play against these openings and how you score.</Panel>;
  return (
    <Panel>
      <PanelTitle sub={`From your ${report.you.games.toLocaleString()} games${report.you.rating ? `, rated about ${report.you.rating}` : ""}`}>What you play</PanelTitle>
      <div className="grid grid-cols-2 gap-6 px-5 pb-5 pt-2 max-md:grid-cols-1">
        {(["white", "black"] as Colour[]).map((c) => (
          <div key={c}><h3 className="mb-1.5 text-[12.5px] font-semibold uppercase tracking-wide text-faint">As {cap(c)}</h3>
            {!report.you[c].families.length ? <p className="text-[13px] text-muted">No games.</p> : <ul className="space-y-1 text-[13px]">{report.you[c].families.slice(0, 6).map((f) => <li key={f.name} className="flex items-center gap-3"><span className="min-w-0 flex-1 truncate">{f.name}</span><span className="tnum text-muted">{f.games}</span><span className="tnum w-10 text-right">{pct(f.score)}</span></li>)}</ul>}</div>
        ))}
      </div>
    </Panel>
  );
}

// ---- traps -----------------------------------------------------------------------------------------------------------------------------------------

function TrapCard({ t, you }: { t: Trap; you: Colour }) {
  const arrows: Arrow[] = t.punishUci ? [{ from: t.punishUci.slice(0, 2), to: t.punishUci.slice(2, 4), kind: "best" }] : [];
  return (
    <Panel className="grid grid-cols-[240px_minmax(0,1fr)] gap-5 p-4 max-md:grid-cols-1">
      <MiniBoard fen={t.fenAfter} orientation={you} arrows={arrows} size={240} />
      <div className="min-w-0 text-[13.5px]">
        <div className="flex flex-wrap items-center gap-2"><Badge tone="accent">You play {cap(you)}</Badge>{t.sound ? <Badge tone="good">your moves on the way are sound</Badge> : <Badge tone="warn">your way there costs {pct(t.yourWorstLoss)} against best play</Badge>}</div>
        <p className="mt-2 font-mono text-[13px] text-muted">{t.path || "from the start"}</p>
        <p className="mt-1.5"><b>They play {t.move}</b> in {t.games} of {t.visits} games here and score {pct(t.score)} with it. The engine says it gives away <b style={{ color: WARN }}>{pct(t.loss)}</b>{t.better ? <>; they should play <b>{t.better}</b></> : ""}.</p>
        {t.punish && <p className="mt-1.5">You answer <b>{t.punish}</b>{t.punishLine.length > 1 ? <> (the line: <span className="font-mono text-muted">{t.punishLine.join(" ")}</span>)</> : ""}. After it you stand at about <b>{pct(t.youStand)}</b>.</p>}
      </div>
    </Panel>
  );
}

function TrapsTab({ report }: { report: Report }) {
  const all = ([["black", "white"], ["white", "black"]] as [Colour, Colour][]).flatMap(([opp, you]) => report.traps[opp].map((t) => ({ t, you }))).sort((a, b) => b.t.games * b.t.loss - a.t.games * a.t.loss);
  if (!all.length) return <Panel><EmptyState icon={AlertTriangle} title="No clear traps" text="A trap is a position where their usual move gives away a lot (at least 8 points) and they have played it at least twice. Read more of their games, or use a deeper preparation." /></Panel>;
  return (
    <div className="space-y-4">
      <p className="text-[13px] text-muted">Positions from their own games where their usual move is a mistake, strongest first (how often × how much it gives away). The path is the way their games got there; the check says whether your own moves on it are sound.</p>
      {all.map(({ t, you }, i) => <TrapCard key={i} t={t} you={you} />)}
    </div>
  );
}

// ---- middlegame, endgame, clock ---------------------------------------------------------------------------------------------------------------------

function MomentCard({ m, you }: { m: Moment; you: Colour }) {
  const arrows: Arrow[] = [{ from: m.uci.slice(0, 2), to: m.uci.slice(2, 4), kind: "played" }];
  return (
    <Panel className="p-3">
      <MiniBoard fen={m.fen} orientation={you} arrows={arrows} size={220} />
      <div className="mt-2 text-[12.5px]">
        <p><b>{m.played}</b> gave away <b style={{ color: BAD }}>{pct(m.loss)}</b> in the {m.phase}{m.best ? <>; better was <b>{m.best}</b></> : ""}.</p>
        {m.url && <a href={m.url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-1 text-accent hover:underline">The game <ExternalLink size={12} /></a>}
      </div>
    </Panel>
  );
}

function RateTable({ title, rows }: { title: string; rows: { name: string; moves: number; rate: number; loss?: number }[] }) {
  return (
    <Panel>
      <PanelTitle>{title}</PanelTitle>
      <table className="w-full px-5 text-[13px]"><tbody>
        {rows.map((r) => <tr key={r.name} className="border-t border-border/60"><td className="px-5 py-2 capitalize">{r.name}</td><td className="tnum px-2 py-2 text-muted">{r.moves} moves</td><td className="tnum px-5 py-2 text-right">gives away points on {pct(r.rate)}</td></tr>)}
      </tbody></table>
    </Panel>
  );
}

function LaterTab({ report }: { report: Report }) {
  const w = report.weakness;
  if (!w.games) return <Panel><EmptyState icon={AlertTriangle} title="No whole games analysed" text="Middlegame and endgame weaknesses need their games analysed move by move. Run the preparation again with Standard or Deep." /></Panel>;
  const phases = Object.entries(w.profile.by_phase ?? {}).map(([name, r]) => ({ name, moves: r.moves, rate: r.mistake_rate }));
  const situ = Object.entries(w.profile.by_situation ?? {}).map(([name, r]) => ({ name: name === "ahead" ? "when they are better" : name === "behind" ? "when they are worse" : "in equal positions", moves: r.moves, rate: r.mistake_rate }));
  const you = (report.plan.white.tree ? "white" : "black") as Colour;
  const t = w.time, c = w.conversion;
  return (
    <div className="space-y-5">
      <Panel>
        <PanelTitle sub={`From ${w.games} games analysed move by move (${w.moves.toLocaleString()} of their moves)`}>Where they go wrong</PanelTitle>
        <ul className="space-y-2 px-5 pb-5 pt-2 text-[14px]">
          {[...w.sentences, ...w.referenceSentences].length ? [...w.sentences, ...w.referenceSentences].map((s, i) => <li key={i} className="flex gap-2.5"><Target size={16} className="mt-[3px] shrink-0 text-accent" /><span>{s}</span></li>) : <li className="text-muted">Nothing stands out clearly in these games.</li>}
        </ul>
      </Panel>
      <div className="grid grid-cols-2 gap-5 max-lg:grid-cols-1">
        <RateTable title="By phase" rows={phases} />
        <RateTable title="By situation" rows={situ} />
      </div>
      {w.endgames.length > 0 && (
        <Panel>
          <PanelTitle sub="Which kinds of endgame they handle badly (compared with their other endgames)">Endgames</PanelTitle>
          <table className="w-full text-[13px]"><tbody>
            {w.endgames.map((e) => <tr key={e.type} className="border-t border-border/60"><td className="px-5 py-2 capitalize">{e.type}{e.weak && <Badge tone="warn" className="ml-2">weak</Badge>}</td><td className="tnum px-2 py-2 text-muted">{e.moves} moves in {e.games} games</td><td className="tnum px-5 py-2 text-right">{pct(e.mistakeRate)}</td></tr>)}
          </tbody></table>
        </Panel>
      )}
      <div className="grid grid-cols-2 gap-5 max-lg:grid-cols-1">
        <Panel>
          <PanelTitle>The clock</PanelTitle>
          <div className="space-y-1.5 px-5 pb-5 pt-2 text-[13.5px]">
            {!t.games ? <p className="text-muted">These games carry no clock information.</p> : <>
              <p>Short of time in <b>{pct(t.troubleShare)}</b> of their games; they score {pct(t.scoreInTrouble ?? null)} then, against {pct(t.scoreOtherwise ?? null)} otherwise.</p>
              {t.mistakeRateLow !== null && t.mistakeRateLow !== undefined && <p>With little time they give away points on {pct(t.mistakeRateLow)} of their moves ({t.lowMoves} moves), against {pct(t.mistakeRateOk)} with time.</p>}
              <p>{t.flagLosses} of their {t.losses} losses were on time.</p>
            </>}
          </div>
        </Panel>
        <Panel>
          <PanelTitle>Winning and losing positions</PanelTitle>
          <div className="space-y-1.5 px-5 pb-5 pt-2 text-[13.5px]">
            <p>Of {c.hadWinning} games where they stood clearly better they won <b>{c.converted}</b>{c.hadWinning ? ` (${pct(c.converted / c.hadWinning)})` : ""}.</p>
            <p>Of {c.wasLosing} games where they stood clearly worse they saved <b>{c.saved}</b>{c.wasLosing ? ` (${pct(c.saved / c.wasLosing)})` : ""}.</p>
          </div>
        </Panel>
      </div>
      {w.moments.length > 0 && (
        <div>
          <h3 className="mb-3 text-[14px] font-semibold">Their biggest slips after the opening</h3>
          <div className="grid grid-cols-4 gap-4 max-xl:grid-cols-3 max-lg:grid-cols-2 max-sm:grid-cols-1">{w.moments.map((m, i) => <MomentCard key={i} m={m} you={you === "white" ? "black" : "white"} />)}</div>
        </div>
      )}
    </div>
  );
}

// ---- their games -----------------------------------------------------------------------------------------------------------------------------------

function GamesTab({ report }: { report: Report }) {
  return (
    <Panel>
      <PanelTitle sub="The newest first; the links open the game on the site">Their latest games</PanelTitle>
      <div className="overflow-x-auto px-2 pb-3">
        <table className="w-full min-w-[560px] text-[13px]">
          <thead><tr className="text-left text-[11.5px] uppercase tracking-wide text-faint"><th className="px-3 py-2 font-semibold">Date</th><th className="px-3 py-2 font-semibold">Colour</th><th className="px-3 py-2 font-semibold">Result</th><th className="px-3 py-2 font-semibold">Opening</th><th className="px-3 py-2 font-semibold">Speed</th><th className="px-3 py-2 font-semibold">Against</th><th /></tr></thead>
          <tbody>
            {report.recent.map((g) => (
              <tr key={g.id} className="border-t border-border/60">
                <td className="tnum px-3 py-2">{formatDate(g.date)}</td><td className="px-3 py-2 capitalize">{g.colour}</td>
                <td className="px-3 py-2">{g.score === null ? "–" : g.score === 1 ? <Badge tone="good">Won</Badge> : g.score === 0 ? <Badge tone="bad">Lost</Badge> : <Badge>Draw</Badge>}</td>
                <td className="px-3 py-2">{g.opening ?? "–"}</td><td className="px-3 py-2 capitalize">{g.speed ?? ""}</td><td className="tnum px-3 py-2">{g.against ?? ""}</td>
                <td className="px-3 py-2 text-right">{g.url && <a href={g.url} target="_blank" rel="noopener noreferrer" aria-label="Open the game on the site" className="text-accent"><ExternalLink size={14} /></a>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
