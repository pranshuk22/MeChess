import * as Tabs from "@radix-ui/react-tabs";
import { ChevronFirst, ChevronLast, ChevronLeft, ChevronRight, FlipVertical2, Lightbulb, RotateCcw, Sparkles, Target } from "lucide-react";
import { memo, useCallback, useDeferredValue, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useAnalyse, useGame } from "@/api/hooks";
import type { Arrow } from "@/board/Arrows";
import { Board } from "@/board/Board";
import { AppearanceButton } from "@/components/Appearance";
import { ClassIcon } from "@/components/ClassIcon";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { EmptyState, Skeleton } from "@/components/ui/Misc";
import { Panel } from "@/components/ui/Panel";
import { formatDate } from "@/lib/format";
import { checkSquare, fensFromUci, movesFromPgn, uciToSan } from "@/lib/game";
import { BAD, CLASS_LABEL, CLASS_VAR, formatEval, type AnalysedMove, type GameDetail, type MoveClass } from "@/lib/types";
import { EvalBar } from "./EvalBar";
import { EvalGraph } from "./EvalGraph";
import { MoveList } from "./MoveList";
import { Summary } from "./Summary";
import { useRetry } from "./useRetry";

const NO_BADGE: MoveClass[] = ["book", "good", "excellent"];
const TAB_BODY = "min-h-0 flex-1 overflow-auto outline-none";

export function ReviewPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const { data: game, isLoading, isError } = useGame(id);
  if (!id) return <div className="p-10"><Panel><EmptyState icon={Target} title="Pick a game to review" text="Open a game from your library." action={<Button variant="primary" onClick={() => nav("/library")}>Go to the library</Button>} /></Panel></div>;
  if (isLoading) return <div className="mx-auto grid max-w-[1240px] grid-cols-[minmax(0,1fr)_380px] gap-5 p-6"><Skeleton className="aspect-square w-full rounded-[12px]" /><Skeleton className="h-[480px] rounded-[12px]" /></div>;
  if (isError || !game) return <div className="p-10"><Panel><EmptyState icon={Target} title="That game is not in your library" action={<Button onClick={() => nav("/library")}>Back to the library</Button>} /></Panel></div>;
  return <ReviewGame key={game.id} game={game} />;
}

/** The moves to show: the analysed moves, or (for a game without analysis) the plain moves of its PGN, so it can still be stepped through. */
function useMoves(game: GameDetail): AnalysedMove[] {
  return useMemo(() => game.moves.length ? game.moves : movesFromPgn(game.pgn ?? "").map((m) => ({ san: m.san, uci: m.uci, cls: "good" as MoveClass, loss: 0, best: m.uci, winBefore: 0.5, winAfter: 0.5, cp: 0 })), [game]);
}

function ReviewGame({ game: loaded }: { game: GameDetail }) {
  const moves = useMoves(loaded);
  const game = useMemo<GameDetail>(() => ({ ...loaded, moves }), [loaded, moves]);
  const analysed = loaded.analysed;
  const userIsWhite = game.user !== "black";
  const [ply, setPly] = useState(0);
  const [flipped, setFlipped] = useState(!userIsWhite);
  const [showBest, setShowBest] = useState(true);
  const [retryOn, setRetryOn] = useState(false);
  const fens = useMemo(() => fensFromUci(moves.map((m) => m.uci)), [moves]);
  const checks = useMemo(() => fens.map(checkSquare), [fens]);                      // once per game, not on every render
  const n = moves.length;
  const fen = fens[ply];
  const last = ply > 0 ? moves[ply - 1] : null;
  const lastMove: [string, string] | null = last ? [last.uci.slice(0, 2), last.uci.slice(2, 4)] : null;
  const next = moves[ply];
  const cp = ply === 0 ? 20 : moves[ply - 1].cp;

  const mistakes = useMemo(() => analysed ? moves.map((m, i) => ({ m, i })).filter(({ m, i }) => (i % 2 === 0) === userIsWhite && m.loss >= 0.1 && (m.cls === "mistake" || m.cls === "blunder" || m.cls === "miss")).sort((a, b) => b.m.loss - a.m.loss) : [], [moves, userIsWhite, analysed]);
  const retry = useRetry(game, mistakes, retryOn, () => setRetryOn(false));

  const arrows = useMemo<Arrow[]>(() => {
    if (!analysed || !showBest || !next || retry) return [];
    const out: Arrow[] = [{ from: next.best.slice(0, 2), to: next.best.slice(2, 4), kind: "best" }];
    if (next.uci !== next.best && BAD.includes(next.cls)) out.push({ from: next.uci.slice(0, 2), to: next.uci.slice(2, 4), kind: "played" });
    return out;
  }, [analysed, showBest, next, retry]);

  useEffect(() => {
    if (retryOn) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, select, [role=dialog]")) return;
      if (e.key === "ArrowLeft") setPly((p) => Math.max(0, p - 1));
      else if (e.key === "ArrowRight") setPly((p) => Math.min(n, p + 1));
      else if (e.key === "Home") setPly(0);
      else if (e.key === "End") setPly(n);
      else if (e.key === "f") setFlipped((f) => !f);
      else if (e.key === "b") setShowBest((b) => !b);
      else return;
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [n, retryOn]);

  const orientation = flipped ? "black" : "white";
  const white = { name: game.white, elo: game.whiteElo, acc: game.accuracy?.white ?? null, colour: "white" as const }, black = { name: game.black, elo: game.blackElo, acc: game.accuracy?.black ?? null, colour: "black" as const };
  const top = flipped ? white : black, bottom = flipped ? black : white;
  const goto = useCallback((p: number) => { setRetryOn(false); setPly(p); }, []);
  const dPly = useDeferredValue(ply);                                                  // the side panels follow one beat later: the board moves first
  const boardFen = retry ? retry.fen : fen;
  const badge = analysed && !retry && last && !NO_BADGE.includes(last.cls) ? { sq: last.uci.slice(2, 4), cls: last.cls } : null;

  return (
    <div className="mx-auto grid max-w-[1240px] grid-cols-[minmax(0,1fr)_388px] gap-6 p-6 lg:h-[100dvh] max-lg:grid-cols-1 max-md:p-3">
      <section aria-label="Board" className="flex min-h-0 min-w-0 flex-col justify-self-center" style={{ width: "min(100%, calc(100dvh - 140px))" }}>
        <PlayerStrip {...top} />
        <div className="my-2.5 flex gap-2.5">
          <EvalBar cp={retry || !analysed ? 0 : cp} orientation={orientation} muted={!analysed} />
          <div className="min-w-0 flex-1 overflow-hidden rounded-[6px] shadow-[0_1px_2px_rgba(16,24,32,0.12),0_12px_32px_-12px_rgba(16,24,32,0.3)]">
            <Board fen={boardFen} orientation={orientation} lastMove={retry ? retry.lastMove : lastMove} checkSquare={retry ? checkSquare(boardFen) : checks[ply]} arrows={retry ? retry.arrows : arrows}
              marks={retry?.marks} legal={retry?.legal} movable={retry ? (userIsWhite ? "w" : "b") : null} badge={badge} onMove={retry?.onMove} />
          </div>
        </div>
        <PlayerStrip {...bottom} />
        <div className="mt-2 flex h-9 items-center justify-center gap-1">
          {!retry && <>
            <IconButton label="First move (Home)" onClick={() => setPly(0)} disabled={ply === 0}><ChevronFirst size={18} /></IconButton>
            <IconButton label="Previous (←)" onClick={() => setPly(ply - 1)} disabled={ply === 0}><ChevronLeft size={18} /></IconButton>
            <IconButton label="Next (→)" onClick={() => setPly(ply + 1)} disabled={ply === n}><ChevronRight size={18} /></IconButton>
            <IconButton label="Last move (End)" onClick={() => setPly(n)} disabled={ply === n}><ChevronLast size={18} /></IconButton>
            <span className="mx-2 h-5 w-px bg-border" />
          </>}
          <IconButton label="Flip board (F)" onClick={() => setFlipped(!flipped)}><FlipVertical2 size={18} /></IconButton>
          {!retry && analysed && <IconButton label="Show engine's best move (B)" onClick={() => setShowBest(!showBest)} active={showBest}><Target size={18} /></IconButton>}
          <AppearanceButton />
        </div>
      </section>

      <Sidebar game={game} analysed={analysed} ply={dPly} fens={fens} userIsWhite={userIsWhite} mistakes={mistakes} retryOn={retryOn} onRetry={() => setRetryOn(true)} goto={goto} retryPanel={retry ? retry.panel : null} />
    </div>
  );
}

type SideProps = { game: GameDetail; analysed: boolean; ply: number; fens: string[]; userIsWhite: boolean; mistakes: { m: AnalysedMove; i: number }[]; retryOn: boolean; onRetry: () => void; goto: (p: number) => void; retryPanel: React.ReactNode };

const Sidebar = memo(function Sidebar({ game, analysed, ply, fens, userIsWhite, mistakes, retryOn, onRetry, goto, retryPanel }: SideProps) {
  const analyse = useAnalyse();
  const fen = fens[ply];
  const moves = game.moves;
  const last = ply > 0 ? moves[ply - 1] : null;
  const next = moves[ply];
  const cp = ply === 0 ? 20 : moves[ply - 1]?.cp ?? 0;
  const you = game.accuracy ? game.accuracy[userIsWhite ? "white" : "black"] : null;
  return (
    <aside className="flex min-h-0 flex-col gap-4 lg:h-full">
      <Panel className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="truncate text-[16px] font-semibold leading-6">{game.title ?? `${game.white} – ${game.black}`}</h1>
            <p className="truncate text-[12.5px] text-muted">{game.opening || "Opening unknown"}{game.speed ? ` · ${game.speed}` : ""}{game.date ? ` · ${formatDate(game.date)}` : ""}</p>
          </div>
          {you !== null && <div className="shrink-0 text-right"><div className="tnum font-display text-[24px] font-semibold leading-none tracking-[-0.04em]">{you.toFixed(0)}<span className="text-[13px] text-muted">%</span></div><div className="mt-1 text-[11px] text-muted">your accuracy</div></div>}
        </div>
        {analysed ? <>
          <div className="mt-4"><EvalGraph moves={moves} ply={ply} onSelect={goto} userIsWhite={userIsWhite} /></div>
          <Button variant="primary" className="mt-4 w-full" disabled={mistakes.length === 0 || retryOn} onClick={onRetry}><RotateCcw size={15} /> Retry your mistakes{mistakes.length ? ` (${mistakes.length})` : ""}</Button>
        </> : (
          <div className="mt-4 rounded-[10px] bg-sunken p-4">
            <p className="text-[13.5px] text-muted">This game has not been analysed yet. You can step through the moves now; analysis adds move classes, accuracy and the best moves.</p>
            <Button variant="primary" className="mt-3" disabled={analyse.isPending || analyse.isSuccess} onClick={() => analyse.mutate({ ids: [game.id] })}><Sparkles size={15} /> {analyse.isSuccess ? "Analysing…" : "Analyse this game"}</Button>
            {analyse.isError && <p role="alert" className="mt-2 text-[12.5px] text-[var(--q-blunder)]">{(analyse.error as Error).message}</p>}
          </div>
        )}
      </Panel>

      <Panel className="flex min-h-[220px] flex-1 flex-col overflow-hidden">
        <Tabs.Root defaultValue={analysed ? "summary" : "moves"} className="flex min-h-0 flex-1 flex-col">
          <Tabs.List className="flex gap-1 border-b border-border px-3 pt-2" aria-label="Review sections">
            {[["summary", "Summary"], ["moves", "Moves"], ["moments", "Key moments"]].filter(([v]) => analysed || v === "moves").map(([v, l]) => (
              <Tabs.Trigger key={v} value={v} className="rounded-t-md px-3 py-2.5 text-[13px] font-medium text-muted transition-colors hover:text-text data-[state=active]:text-text data-[state=active]:shadow-[inset_0_-2px_0_var(--accent)] cursor-pointer">{l}</Tabs.Trigger>
            ))}
          </Tabs.List>
          {analysed && <Tabs.Content value="summary" className={TAB_BODY}><Summary game={game} /></Tabs.Content>}
          <Tabs.Content value="moves" className={TAB_BODY + " p-2"}><MoveList moves={moves} ply={ply} onSelect={goto} plain={!analysed} /></Tabs.Content>
          {analysed && <Tabs.Content value="moments" className={TAB_BODY + " p-2"}>
            {mistakes.length === 0 ? <p className="p-3 text-muted">No mistakes of yours in this game.</p> : mistakes.map(({ m, i }) => (
              <button key={i} onClick={() => goto(i)} className="flex w-full items-center justify-between rounded-[8px] px-3 py-2 text-left transition-colors hover:bg-surface-2 cursor-pointer">
                <span className="flex items-center gap-2"><ClassIcon cls={m.cls} size={16} /><span className="tnum text-faint">{Math.floor(i / 2) + 1}.</span> <b className="font-medium">{m.san}</b></span>
                <span className="tnum text-[12.5px] text-muted">−{(m.loss * 100).toFixed(0)}% win chance</span>
              </button>
            ))}
          </Tabs.Content>}
        </Tabs.Root>
      </Panel>

      <Panel className="min-h-[132px] p-5 text-[13.5px]">
        {retryPanel ?? (analysed ? <MoveExplanation fen={ply > 0 ? fens[ply - 1] : fen} move={last} cp={cp} next={next ? uciToSan(fen, next.best) : null} /> : <p className="text-muted">{last ? <><b className="text-text">{last.san}</b> was played. Analyse the game to see how good it was.</> : "Step through the game with the arrow keys."}</p>)}
      </Panel>
    </aside>
  );
});

function PlayerStrip({ name, elo, acc, colour }: { name: string; elo: number | null; acc: number | null; colour: "white" | "black" }) {
  return (
    <div className="flex h-6 items-center justify-between gap-3 px-0.5 text-[13.5px]">
      <span className="flex min-w-0 items-center gap-2"><span className="h-3 w-3 shrink-0 rounded-[3px] border" style={{ background: colour === "white" ? "#fff" : "#2b3139", borderColor: "var(--border-strong)" }} aria-hidden /><span className="truncate font-medium">{name}</span>{elo ? <span className="tnum text-muted">{elo}</span> : null}</span>
      {acc !== null && <span className="tnum font-display text-[12px] text-muted">{acc.toFixed(0)}%</span>}
    </div>
  );
}

function MoveExplanation({ fen, move, cp, next }: { fen: string; move: AnalysedMove | null; cp: number; next: string | null }) {
  if (!move) return <p className="text-muted">Step through the game with the arrow keys. {next && <>The engine would start with <b className="text-text">{next}</b>.</>}</p>;
  const bad = BAD.includes(move.cls);
  const better = bad ? uciToSan(fen, move.best) : null;
  return (
    <>
      <div className="flex items-center gap-2"><ClassIcon cls={move.cls} size={18} /><b className="font-semibold" style={{ color: CLASS_VAR[move.cls] }}>{move.san} · {CLASS_LABEL[move.cls]}</b><span className="tnum font-display ml-auto text-muted">{formatEval(cp)}</span></div>
      <p className="mt-2 text-muted">
        {bad ? <>Gave away about <b className="text-text">{Math.round(move.loss * 100)}%</b> of the win chance. Better was <b className="text-text">{better}</b>.</>
          : move.cls === "best" || move.cls === "brilliant" || move.cls === "great" ? "The engine's top choice." : "A sound move."}
        {next && <> From here the engine likes <b className="text-text">{next}</b>.</>}
      </p>
      {bad && <p className="mt-2 flex items-center gap-1.5 text-[12.5px] text-faint"><Lightbulb size={14} /> Press <kbd className="rounded border border-border px-1 font-mono text-[11px]">B</kbd> to see it on the board.</p>}
    </>
  );
}
