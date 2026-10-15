import { useVirtualizer } from "@tanstack/react-virtual";
import clsx from "clsx";
import { Download, Search } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useGames } from "@/api/games";
import { MiniEval } from "@/components/MiniEval";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";
import { myAccuracy, opponent, outcome } from "@/lib/format";
import type { GameRecord } from "@/lib/types";
import { ImportDialog } from "./ImportDialog";

const COLS = "grid-cols-[56px_minmax(160px,1.4fr)_64px_minmax(140px,1.6fr)_72px_100px_72px] max-md:grid-cols-[48px_1fr_56px]";
const RESULT = { win: ["Win", "var(--q-best)"], loss: ["Loss", "var(--q-blunder)"], draw: ["Draw", "var(--faint)"] } as const;

export function LibraryPage() {
  const { data = [], isLoading } = useGames();
  const [params] = useSearchParams();
  const stress = Number(params.get("stress") || 0);                         // ?stress=10000 repeats the sample games to check that a long list stays smooth
  const [q, setQ] = useState("");
  const [colour, setColour] = useState<"all" | "white" | "black">("all");
  const [result, setResult] = useState<"all" | "win" | "loss" | "draw">("all");
  const [open, setOpen] = useState(false);

  const all = useMemo<GameRecord[]>(() => (stress && data.length ? Array.from({ length: stress }, (_, i) => data[i % data.length]) : data), [data, stress]);
  const rows = useMemo(() => all.filter((g) => {
    if (colour !== "all" && g.user !== colour) return false;
    if (result !== "all" && outcome(g) !== result) return false;
    const t = q.trim().toLowerCase();
    return !t || `${g.white} ${g.black} ${g.opening} ${g.title ?? ""}`.toLowerCase().includes(t);
  }), [all, q, colour, result]);

  const scroller = useRef<HTMLDivElement>(null);
  const v = useVirtualizer({ count: rows.length, getScrollElement: () => scroller.current, estimateSize: () => 52, overscan: 12 });

  return (
    <div className="mx-auto flex h-full max-w-[1180px] flex-col gap-3 p-5 max-md:p-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="relative">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search players or openings" aria-label="Search games"
            className="h-9 w-64 rounded-md border border-border bg-surface pl-9 pr-3 text-[13.5px] outline-none placeholder:text-faint focus:border-accent max-md:w-full" />
        </label>
        <Seg label="Colour" value={colour} onChange={setColour} options={[["all", "Any colour"], ["white", "White"], ["black", "Black"]]} />
        <Seg label="Result" value={result} onChange={setResult} options={[["all", "Any result"], ["win", "Wins"], ["loss", "Losses"], ["draw", "Draws"]]} />
        <div className="ml-auto flex items-center gap-3">
          <span className="tnum text-[12.5px] text-muted">{rows.length.toLocaleString()} games</span>
          <Button variant="primary" onClick={() => setOpen(true)}><Download size={15} /> Import games</Button>
        </div>
      </div>

      <Panel className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className={clsx("grid gap-3 border-b border-border px-4 py-2 text-[11.5px] font-semibold uppercase tracking-wide text-muted", COLS)} role="row">
          <span>Result</span><span>Opponent</span><span className="max-md:hidden">Acc.</span><span className="max-md:hidden">Opening</span><span className="max-md:hidden">Speed</span><span className="max-md:hidden">Evaluation</span><span className="text-right max-md:text-left">Year</span>
        </div>
        <div ref={scroller} className="min-h-0 flex-1 overflow-auto" role="rowgroup">
          {isLoading && <div className="p-6 text-muted">Loading…</div>}
          {!isLoading && rows.length === 0 && <Empty />}
          <div style={{ height: v.getTotalSize(), position: "relative" }}>
            {v.getVirtualItems().map((it) => {
              const g = rows[it.index], opp = opponent(g), [label, colourVar] = RESULT[outcome(g)];
              return (
                <Link key={it.key} to={`/review/${g.id}`} role="row" style={{ position: "absolute", top: 0, left: 0, right: 0, height: it.size, transform: `translateY(${it.start}px)` }}
                  className={clsx("grid items-center gap-3 border-b border-border/60 px-4 text-[13.5px] hover:bg-surface-2", COLS)}>
                  <span className="text-[12.5px] font-semibold" style={{ color: colourVar }}>{label}</span>
                  <span className="min-w-0"><span className="block truncate font-medium">{opp.name}</span><span className="tnum text-[12px] text-muted">{opp.elo} · you played {g.user}</span></span>
                  <span className="tnum max-md:hidden">{myAccuracy(g).toFixed(0)}%</span>
                  <span className="truncate text-muted max-md:hidden">{g.title ?? (g.opening || "—")}</span>
                  <span className="capitalize text-muted max-md:hidden">{g.speed}</span>
                  <span className="max-md:hidden"><MiniEval moves={g.moves} /></span>
                  <span className="tnum text-right text-muted max-md:text-left">{g.year}</span>
                </Link>
              );
            })}
          </div>
        </div>
      </Panel>
      <ImportDialog open={open} onOpenChange={setOpen} />
    </div>
  );
}

function Seg<T extends string>({ label, value, onChange, options }: { label: string; value: T; onChange: (v: T) => void; options: [T, string][] }) {
  return (
    <div role="group" aria-label={label} className="inline-flex rounded-md border border-border bg-surface p-0.5">
      {options.map(([v, l]) => (
        <button key={v} onClick={() => onChange(v)} aria-pressed={value === v} className={clsx("h-8 rounded px-2.5 text-[12.5px] font-medium cursor-pointer", value === v ? "bg-accent-soft text-accent" : "text-muted hover:text-text")}>{l}</button>
      ))}
    </div>
  );
}

function Empty() {
  return (
    <div className="grid place-items-center gap-2 p-14 text-center">
      <p className="text-[15px] font-medium">No games match.</p>
      <p className="max-w-sm text-muted">Clear the filters, or import more games from Lichess, Chess.com or a PGN file.</p>
    </div>
  );
}
