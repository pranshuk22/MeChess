import { useVirtualizer } from "@tanstack/react-virtual";
import clsx from "clsx";
import { Download, Library as LibraryIcon, Search, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useAnalyse, useGamesInfinite, useStats } from "@/api/hooks";
import { MiniEval } from "@/components/MiniEval";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Badge, EmptyState, Skeleton } from "@/components/ui/Misc";
import { PageHeader, Panel } from "@/components/ui/Panel";
import { Segmented } from "@/components/ui/Segmented";
import { formatDate, me, myAccuracy, mySide, opponent, outcome } from "@/lib/format";
import { useDialogs } from "@/state/dialogs";

const COLS = "grid-cols-[64px_minmax(180px,1.5fr)_112px_minmax(150px,1.4fr)_72px_108px_104px] max-lg:grid-cols-[64px_minmax(0,1fr)_88px_92px]";
const RESULT = { win: ["Win", "good"], loss: ["Loss", "bad"], draw: ["Draw", "neutral"], unknown: ["–", "neutral"] } as const;
const ROW = 58;

export function LibraryPage() {
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [colour, setColour] = useState("all");
  const [result, setResult] = useState("all");
  const [analysed, setAnalysed] = useState("all");
  useEffect(() => { const t = setTimeout(() => setDebounced(q), 250); return () => clearTimeout(t); }, [q]);
  const filters = { q: debounced || undefined, colour: colour === "all" ? undefined : colour, result: result === "all" ? undefined : result, analysed: analysed === "all" ? undefined : analysed === "yes" };
  const query = useGamesInfinite(filters);
  const rows = query.data?.pages.flatMap((p) => p.items) ?? [];
  const total = query.data?.pages[0]?.total ?? 0;
  const stats = useStats().data;
  const setImportOpen = useDialogs((s) => s.setImportOpen);
  const analyse = useAnalyse(), nav = useNavigate();
  const todo = stats ? stats.games - stats.analysed : 0;

  const scroller = useRef<HTMLDivElement>(null);
  const v = useVirtualizer({ count: rows.length, getScrollElement: () => scroller.current, estimateSize: () => ROW, overscan: 10 });
  const items = v.getVirtualItems();
  const last = items.at(-1)?.index ?? 0;
  useEffect(() => { if (last >= rows.length - 25 && query.hasNextPage && !query.isFetchingNextPage) query.fetchNextPage(); }, [last, rows.length, query]);   // eslint-disable-line react-hooks/exhaustive-deps
  const filtered = !!(debounced || colour !== "all" || result !== "all" || analysed !== "all");

  return (
    <div className="mx-auto flex h-full max-w-[1240px] flex-col px-8 py-8 max-md:px-4">
      <PageHeader title="Library" sub={query.isLoading ? " " : `${total.toLocaleString()} game${total === 1 ? "" : "s"}${filtered ? " match" : ""}`}
        actions={<>
          {todo > 0 && <Button disabled={analyse.isPending} onClick={() => analyse.mutate({}, { onSuccess: () => nav("/activity") })}><Sparkles size={15} /> Analyse {todo.toLocaleString()} new</Button>}
          <Button variant="primary" onClick={() => setImportOpen(true)}><Download size={15} /> Import games</Button>
        </>} />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <div className="w-72 max-md:w-full"><Input icon={<Search size={15} />} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search players or openings" aria-label="Search games" /></div>
        <Segmented size="sm" label="Colour" value={colour} onChange={setColour} options={[["all", "Any colour"], ["white", "White"], ["black", "Black"]]} />
        <Segmented size="sm" label="Result" value={result} onChange={setResult} options={[["all", "Any result"], ["win", "Wins"], ["loss", "Losses"], ["draw", "Draws"]]} />
        <Segmented size="sm" label="Analysis" value={analysed} onChange={setAnalysed} options={[["all", "All"], ["yes", "Analysed"], ["no", "Not analysed"]]} />
      </div>

      <Panel className="flex min-h-0 flex-1 flex-col overflow-hidden" role="table" aria-label="Games" aria-rowcount={total + 1}>
        <div className={clsx("grid items-center gap-4 border-b border-border bg-surface-2/60 px-5 py-2.5 font-display text-[11px] font-semibold uppercase tracking-[0.06em] text-muted", COLS)} role="row">
          <span role="columnheader">Result</span><span role="columnheader">Opponent</span><span role="columnheader" className="max-lg:hidden">Accuracy</span><span role="columnheader" className="max-lg:hidden">Opening</span><span role="columnheader" className="max-lg:hidden">Speed</span><span role="columnheader">Evaluation</span><span role="columnheader" className="text-right">Date</span>
        </div>
        <div ref={scroller} className="min-h-0 flex-1 overflow-auto" role="rowgroup">
          {query.isLoading && Array.from({ length: 9 }, (_, i) => <div key={i} className="border-b border-border/60 px-5 py-3.5"><Skeleton className="h-7" /></div>)}
          {query.isError && <p className="p-8 text-[13.5px] text-[var(--q-blunder)]">The library could not be loaded: {(query.error as Error).message}</p>}
          {!query.isLoading && !query.isError && rows.length === 0 && (filtered
            ? <EmptyState icon={Search} title="No games match" text="Clear the search or the filters to see all your games." />
            : <EmptyState icon={LibraryIcon} title="Your library is empty" text="Import your games from Lichess, Chess.com or a PGN file to see them here." action={<Button variant="primary" onClick={() => setImportOpen(true)}><Download size={15} /> Import games</Button>} />)}
          <div style={{ height: v.getTotalSize(), position: "relative" }}>
            {items.map((it) => {
              const g = rows[it.index];
              if (!g) return null;
              const [label, tone] = RESULT[outcome(g)], opp = opponent(g), acc = myAccuracy(g), side = mySide(g);
              return (
                <Link key={g.id} to={`/review/${encodeURIComponent(g.id)}`} role="row" style={{ position: "absolute", top: 0, left: 0, right: 0, height: it.size, transform: `translateY(${it.start}px)` }}
                  className={clsx("grid items-center gap-4 border-b border-border/60 px-5 text-[13.5px] transition-colors hover:bg-surface-2/70", COLS)}>
                  <span role="cell"><Badge tone={tone} className="justify-center">{label}</Badge></span>
                  <span role="cell" className="min-w-0">
                    <span className="flex items-center gap-2"><span className={clsx("h-2.5 w-2.5 shrink-0 rounded-full border", side === "white" ? "border-[var(--border-strong)] bg-white" : "border-transparent bg-[#2b3139]")} title={`You played ${side}`} /><span className="truncate font-medium">{opp.name}</span></span>
                    <span className="tnum block truncate pl-[18px] text-[12px] text-muted">{opp.elo ?? "unrated"} · you {me(g).elo ?? ""}</span>
                  </span>
                  <span role="cell" className="max-lg:hidden">
                    {acc === null ? <span className="text-[12.5px] text-faint">not analysed</span> : <span className="flex items-center gap-2"><span className="tnum w-9 text-[13px] font-medium">{acc.toFixed(0)}%</span><span className="h-1 w-12 overflow-hidden rounded-full bg-sunken"><span className="block h-full rounded-full bg-accent" style={{ width: `${acc}%` }} /></span></span>}
                  </span>
                  <span role="cell" className="min-w-0 max-lg:hidden"><span className="block truncate">{g.title ?? (g.opening || "—")}</span>{g.title && g.opening && <span className="block truncate text-[12px] text-muted">{g.opening}</span>}</span>
                  <span role="cell" className="text-muted capitalize max-lg:hidden">{g.speed ?? ""}</span>
                  <span role="cell"><MiniEval cps={g.spark} /></span>
                  <span role="cell" className="tnum text-right text-[12.5px] text-muted">{formatDate(g.date)}</span>
                </Link>
              );
            })}
          </div>
          {query.isFetchingNextPage && <div className="p-3 text-center text-[12.5px] text-faint">Loading more…</div>}
        </div>
      </Panel>
    </div>
  );
}
