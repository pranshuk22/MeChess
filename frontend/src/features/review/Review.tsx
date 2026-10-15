import * as Tabs from "@radix-ui/react-tabs";
import { ChevronFirst, ChevronLast, ChevronLeft, ChevronRight, FlipVertical2, Lightbulb, RotateCcw, Target } from "lucide-react";
import { memo, useCallback, useDeferredValue, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useGame } from "@/api/games";
import type { Arrow } from "@/board/Arrows";
import { Board } from "@/board/Board";
import { AppearanceButton } from "@/components/Appearance";
import { ClassIcon } from "@/components/ClassIcon";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { Panel } from "@/components/ui/Panel";
import { checkSquare, fensFromUci, uciToSan } from "@/lib/game";
import { BAD, CLASS_LABEL, CLASS_VAR, formatEval, type GameRecord, type MoveClass } from "@/lib/types";
import { EvalBar } from "./EvalBar";
import { EvalGraph } from "./EvalGraph";
import { MoveList } from "./MoveList";
import { Summary } from "./Summary";
import { useRetry } from "./useRetry";

const NO_BADGE: MoveClass[] = ["book", "good", "excellent"];
const TAB_BODY = "min-h-0 flex-1 overflow-auto outline-none";

export function ReviewPage() {
  const { id } = useParams();
  const { data: game, isLoading } = useGame(id ?? "s01");
  if (isLoading) return <div className="p-8 text-muted">Loading…</div>;
  if (!game) return <div className="p-8 text-muted">That game is not in your library.</div>;
  return <ReviewGame key={game.id} game={game} />;
}

function ReviewGame({ game }: { game: GameRecord }) {
  const userIsWhite = game.user !== "black";
  const [ply, setPly] = useState(0);
  const [flipped, setFlipped] = useState(!userIsWhite);
  const [showBest, setShowBest] = useState(true);
  const [retryOn, setRetryOn] = useState(false);
  const fens = useMemo(() => fensFromUci(game.moves.map((m) => m.uci)), [game]);
  const checks = useMemo(() => fens.map(checkSquare), [fens]);                      // once per game, not on every render
  const n = game.moves.length;
  const fen = fens[ply];
  const last = ply > 0 ? game.moves[ply - 1] : null;
  const lastMove: [string, string] | null = last ? [last.uci.slice(0, 2), last.uci.slice(2, 4)] : null;
  const next = game.moves[ply];                                                            // the move played from this position
  const cp = ply === 0 ? 20 : game.moves[ply - 1].cp;

  const mistakes = useMemo(() => game.moves.map((m, i) => ({ m, i })).filter(({ m, i }) => (i % 2 === 0) === userIsWhite && m.loss >= 0.1 && (m.cls === "mistake" || m.cls === "blunder" || m.cls === "miss")).sort((a, b) => b.m.loss - a.m.loss), [game, userIsWhite]);
  const retry = useRetry(game, mistakes, retryOn, () => setRetryOn(false));

  const arrows = useMemo<Arrow[]>(() => {
    if (!showBest || !next || retry) return [];
    const out: Arrow[] = [{ from: next.best.slice(0, 2), to: next.best.slice(2, 4), kind: "best" }];
    if (next.uci !== next.best && BAD.includes(next.cls)) out.push({ from: next.uci.slice(0, 2), to: next.uci.slice(2, 4), kind: "played" });
    return out;
  }, [showBest, next, retry]);

  useEffect(() => {
    if (retryOn) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea, [role=dialog]")) return;
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
  const white = { name: game.white, elo: game.whiteElo, acc: game.accuracy.white }, black = { name: game.black, elo: game.blackElo, acc: game.accuracy.black };
  const top = flipped ? white : black, bottom = flipped ? black : white;
  const you = userIsWhite ? white : black;
  const goto = useCallback((p: number) => { setRetryOn(false); setPly(p); }, []);
  const dPly = useDeferredValue(ply);                                                  // the side panels follow one beat later: the board moves first
  const boardFen = retry ? retry.fen : fen;
  const badge = !retry && last && !NO_BADGE.includes(last.cls) ? { sq: last.uci.slice(2, 4), cls: last.cls } : null;

  return (
    <div className="mx-auto grid max-w-[1240px] grid-cols-[minmax(0,1fr)_380px] gap-5 p-5 lg:h-[calc(100dvh-52px)] max-lg:grid-cols-1 max-md:p-3">
      <section aria-label="Board" className="flex min-w-0 flex-col justify-self-center" style={{ width: "min(100%, calc(100dvh - 160px))" }}>
        <PlayerStrip {...top} />
        <div className="my-2 flex gap-2.5">
          <EvalBar cp={retry ? 0 : cp} orientation={orientation} />
          <div className="min-w-0 flex-1">
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
          {!retry && <IconButton label="Show engine's best move (B)" onClick={() => setShowBest(!showBest)} active={showBest}><Target size={18} /></IconButton>}
          <AppearanceButton />
        </div>
      </section>

      <Sidebar game={game} ply={dPly} fens={fens} you={you} userIsWhite={userIsWhite} mistakes={mistakes} retryOn={retryOn} onRetry={() => setRetryOn(true)} goto={goto} retryPanel={retry ? retry.panel : null} />
    </div>
  );
}

type SideProps = { game: GameRecord; ply: number; fens: string[]; you: { acc: number }; userIsWhite: boolean; mistakes: { m: GameRecord["moves"][number]; i: number }[]; retryOn: boolean; onRetry: () => void; goto: (p: number) => void; retryPanel: React.ReactNode };

const Sidebar = memo(function Sidebar({ game, ply, fens, you, userIsWhite, mistakes, retryOn, onRetry, goto, retryPanel }: SideProps) {
  const fen = fens[ply];
  const last = ply > 0 ? game.moves[ply - 1] : null;
  const next = game.moves[ply];
  const cp = ply === 0 ? 20 : game.moves[ply - 1].cp;
  return (
    <aside className="flex min-h-0 flex-col gap-4">
      <Panel className="p-4">
        <div className="flex items-baseline justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-[15px] font-semibold">{game.title ?? `${game.white} – ${game.black}`}</div>
            <div className="truncate text-[12.5px] text-muted">{game.opening || "Opening unknown"} · {game.speed} · {game.year}</div>
          </div>
          <div className="text-right"><div className="tnum text-[22px] font-semibold leading-none">{you.acc.toFixed(0)}<span className="text-[13px] text-muted">%</span></div><div className="text-[11px] text-muted">your accuracy</div></div>
        </div>
        <div className="mt-3"><EvalGraph moves={game.moves} ply={ply} onSelect={goto} userIsWhite={userIsWhite} /></div>
        <Button variant="primary" className="mt-3 w-full" disabled={mistakes.length === 0 || retryOn} onClick={onRetry}><RotateCcw size={15} /> Retry your mistakes{mistakes.length ? ` (${mistakes.length})` : ""}</Button>
      </Panel>

      <Panel className="flex min-h-[220px] flex-1 flex-col overflow-hidden">
        <Tabs.Root defaultValue="summary" className="flex min-h-0 flex-1 flex-col">
          <Tabs.List className="flex gap-1 border-b border-border px-2 pt-2" aria-label="Review sections">
            {[["summary", "Summary"], ["moves", "Moves"], ["moments", "Key moments"]].map(([v, l]) => (
              <Tabs.Trigger key={v} value={v} className="rounded-t-md px-3 py-2 text-[13px] font-medium text-muted data-[state=active]:text-text data-[state=active]:shadow-[inset_0_-2px_0_var(--accent)] cursor-pointer">{l}</Tabs.Trigger>
            ))}
          </Tabs.List>
          <Tabs.Content value="summary" className={TAB_BODY}><Summary game={game} /></Tabs.Content>
          <Tabs.Content value="moves" className={TAB_BODY + " p-2"}><MoveList moves={game.moves} ply={ply} onSelect={goto} /></Tabs.Content>
          <Tabs.Content value="moments" className={TAB_BODY + " p-2"}>
            {mistakes.length === 0 ? <p className="p-3 text-muted">No mistakes of yours in this game.</p> : mistakes.map(({ m, i }) => (
              <button key={i} onClick={() => goto(i)} className="flex w-full items-center justify-between rounded px-3 py-2 text-left hover:bg-surface-2 cursor-pointer">
                <span className="flex items-center gap-2"><ClassIcon cls={m.cls} size={16} /><span className="tnum text-faint">{Math.floor(i / 2) + 1}.</span> <b>{m.san}</b></span>
                <span className="tnum text-[12.5px] text-muted">−{(m.loss * 100).toFixed(0)}% win chance</span>
              </button>
            ))}
          </Tabs.Content>
        </Tabs.Root>
      </Panel>

      <Panel className="min-h-[128px] p-4 text-[13.5px]">
        {retryPanel ?? <MoveExplanation fen={ply > 0 ? fens[ply - 1] : fen} move={last} cp={cp} next={next ? uciToSan(fen, next.best) : null} />}
      </Panel>
    </aside>
  );
});

function PlayerStrip({ name, elo, acc }: { name: string; elo: number | null; acc: number }) {
  return (
    <div className="flex h-5 items-baseline justify-between px-0.5 text-[13.5px]">
      <span className="truncate font-medium">{name} {elo ? <span className="font-normal text-muted tnum">{elo}</span> : null}</span>
      <span className="tnum text-[12px] text-muted">{acc.toFixed(0)}% accuracy</span>
    </div>
  );
}

function MoveExplanation({ fen, move, cp, next }: { fen: string; move: GameRecord["moves"][number] | null; cp: number; next: string | null }) {
  if (!move) return <p className="text-muted">Step through the game with the arrow keys. {next && <>The engine would start with <b className="text-text">{next}</b>.</>}</p>;
  const bad = BAD.includes(move.cls);
  const better = bad ? uciToSan(fen, move.best) : null;
  return (
    <>
      <div className="flex items-center gap-2"><ClassIcon cls={move.cls} size={18} /><b style={{ color: CLASS_VAR[move.cls] }}>{move.san} · {CLASS_LABEL[move.cls]}</b><span className="tnum ml-auto text-muted">{formatEval(cp)}</span></div>
      <p className="mt-1.5 text-muted">
        {bad ? <>Gave away about <b className="text-text">{Math.round(move.loss * 100)}%</b> of the win chance. Better was <b className="text-text">{better}</b>.</>
          : move.cls === "best" || move.cls === "brilliant" || move.cls === "great" ? "The engine's top choice." : "A sound move."}
        {next && <> From here the engine likes <b className="text-text">{next}</b>.</>}
      </p>
      {bad && <p className="mt-2 flex items-center gap-1.5 text-[12.5px] text-faint"><Lightbulb size={14} /> Press <kbd className="rounded border border-border px-1">B</kbd> to see it on the board.</p>}
    </>
  );
}
