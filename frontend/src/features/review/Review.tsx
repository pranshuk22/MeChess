import * as Tabs from "@radix-ui/react-tabs";
import clsx from "clsx";
import { ChevronFirst, ChevronLast, ChevronLeft, ChevronRight, FlipVertical2, Lightbulb, RotateCcw, Target } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useGame } from "@/api/games";
import { Board } from "@/board/Board";
import type { Arrow } from "@/board/Arrows";
import { Button } from "@/components/ui/Button";
import { IconButton } from "@/components/ui/IconButton";
import { Panel } from "@/components/ui/Panel";
import { checkSquare, fensFromUci, uciToSan } from "@/lib/game";
import { BAD, CLASS_LABEL, CLASS_VAR, formatEval, type GameRecord } from "@/lib/types";
import { useUi } from "@/state/ui";
import { EvalBar } from "./EvalBar";
import { EvalGraph } from "./EvalGraph";
import { MoveList } from "./MoveList";
import { Retry } from "./Retry";

export function ReviewPage() {
  const { id } = useParams();
  const { data: game, isLoading } = useGame(id ?? "s01");
  if (isLoading) return <div className="p-8 text-muted">Loading…</div>;
  if (!game) return <div className="p-8 text-muted">That game is not in your library.</div>;
  return <ReviewGame key={game.id} game={game} />;
}

function ReviewGame({ game }: { game: GameRecord }) {
  const pieceSet = useUi((s) => s.pieceSet)();
  const showCoords = useUi((s) => s.showCoords);
  const userIsWhite = game.user === "white";
  const [ply, setPly] = useState(0);
  const [flipped, setFlipped] = useState(!userIsWhite);
  const [showBest, setShowBest] = useState(true);
  const [retry, setRetry] = useState(false);
  const fens = useMemo(() => fensFromUci(game.moves.map((m) => m.uci)), [game]);
  const n = game.moves.length;
  const fen = fens[ply];
  const last = ply > 0 ? game.moves[ply - 1] : null;
  const lastMove: [string, string] | null = last ? [last.uci.slice(0, 2), last.uci.slice(2, 4)] : null;
  const next = game.moves[ply];                                                            // the move played from this position
  const cp = ply === 0 ? 20 : game.moves[ply - 1].cp;

  const arrows = useMemo<Arrow[]>(() => {
    if (!showBest || !next || retry) return [];
    const out: Arrow[] = [{ from: next.best.slice(0, 2), to: next.best.slice(2, 4), kind: "best" }];
    if (next.uci !== next.best && BAD.includes(next.cls)) out.push({ from: next.uci.slice(0, 2), to: next.uci.slice(2, 4), kind: "played" });
    return out;
  }, [showBest, next, retry]);

  const mistakes = useMemo(() => game.moves.map((m, i) => ({ m, i })).filter(({ m, i }) => (i % 2 === 0) === userIsWhite && m.loss >= 0.1 && (m.cls === "mistake" || m.cls === "blunder" || m.cls === "miss")).sort((a, b) => b.m.loss - a.m.loss), [game, userIsWhite]);

  useEffect(() => {
    if (retry) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).closest("input, textarea")) return;
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
  }, [n, retry]);

  const orientation = flipped ? "black" : "white";
  const you = { name: userIsWhite ? game.white : game.black, elo: userIsWhite ? game.whiteElo : game.blackElo, acc: game.accuracy[game.user] };
  const opp = { name: userIsWhite ? game.black : game.white, elo: userIsWhite ? game.blackElo : game.whiteElo, acc: game.accuracy[userIsWhite ? "black" : "white"] };
  const top = flipped ? you : opp, bottom = flipped ? opp : you;

  return (
    <div className="mx-auto grid max-w-[1240px] grid-cols-[minmax(0,1fr)_380px] gap-5 p-5 max-lg:grid-cols-1 max-md:p-3">
      <section aria-label="Board" className="min-w-0 justify-self-center" style={{ width: "min(100%, calc(100vh - 210px + 24px))" }}>
        <PlayerStrip {...top} />
        <div className="my-2 flex gap-2.5">
          <EvalBar cp={retry ? 0 : cp} orientation={orientation} />
          <div className="min-w-0 flex-1">
            {retry ? <Retry game={game} mistakes={mistakes} orientation={orientation} pieceSet={pieceSet} showCoords={showCoords} onExit={() => setRetry(false)} />
              : <Board fen={fen} orientation={orientation} lastMove={lastMove} checkSquare={checkSquare(fen)} arrows={arrows} pieceSet={pieceSet} showCoords={showCoords} />}
          </div>
        </div>
        <PlayerStrip {...bottom} />
        {!retry && (
          <div className="mt-2 flex items-center justify-center gap-1">
            <IconButton label="First move (Home)" onClick={() => setPly(0)} disabled={ply === 0}><ChevronFirst size={18} /></IconButton>
            <IconButton label="Previous (←)" onClick={() => setPly(ply - 1)} disabled={ply === 0}><ChevronLeft size={18} /></IconButton>
            <IconButton label="Next (→)" onClick={() => setPly(ply + 1)} disabled={ply === n}><ChevronRight size={18} /></IconButton>
            <IconButton label="Last move (End)" onClick={() => setPly(n)} disabled={ply === n}><ChevronLast size={18} /></IconButton>
            <span className="mx-2 h-5 w-px bg-border" />
            <IconButton label="Flip board (F)" onClick={() => setFlipped(!flipped)}><FlipVertical2 size={18} /></IconButton>
            <IconButton label="Show engine's best move (B)" onClick={() => setShowBest(!showBest)} active={showBest}><Target size={18} /></IconButton>
          </div>
        )}
      </section>

      <aside className="flex min-h-0 flex-col gap-4">
        <Panel className="p-4">
          <div className="flex items-baseline justify-between gap-3">
            <div className="min-w-0">
              <div className="truncate text-[15px] font-semibold">{game.title ?? `${game.white} – ${game.black}`}</div>
              <div className="truncate text-[12.5px] text-muted">{game.opening || "Opening unknown"} · {game.speed} · {game.year}</div>
            </div>
            <div className="text-right"><div className="tnum text-[22px] font-semibold leading-none">{you.acc.toFixed(0)}<span className="text-[13px] text-muted">%</span></div><div className="text-[11px] text-muted">your accuracy</div></div>
          </div>
          <div className="mt-3"><EvalGraph moves={game.moves} ply={ply} onSelect={(p) => { setRetry(false); setPly(p); }} userIsWhite={userIsWhite} /></div>
          <div className="mt-3 flex gap-2">
            <Button variant="primary" className="flex-1" disabled={mistakes.length === 0} onClick={() => setRetry(true)}><RotateCcw size={15} /> Retry your mistakes{mistakes.length ? ` (${mistakes.length})` : ""}</Button>
          </div>
        </Panel>

        <Panel className="flex min-h-0 flex-1 flex-col">
          <Tabs.Root defaultValue="moves" className="flex min-h-0 flex-1 flex-col">
            <Tabs.List className="flex gap-1 border-b border-border px-2 pt-2" aria-label="Review sections">
              {[["moves", "Moves"], ["moments", "Key moments"], ["explorer", "Explorer"]].map(([v, l]) => (
                <Tabs.Trigger key={v} value={v} disabled={v === "explorer"} className="rounded-t-md px-3 py-2 text-[13px] font-medium text-muted data-[state=active]:text-text data-[state=active]:shadow-[inset_0_-2px_0_var(--accent)] disabled:opacity-40 cursor-pointer">{l}</Tabs.Trigger>
              ))}
            </Tabs.List>
            <Tabs.Content value="moves" className="min-h-0 flex-1 overflow-auto p-2 outline-none" style={{ maxHeight: "calc(100vh - 480px)", minHeight: 160 }}><MoveList moves={game.moves} ply={ply} onSelect={(p) => { setRetry(false); setPly(p); }} /></Tabs.Content>
            <Tabs.Content value="moments" className="min-h-0 flex-1 overflow-auto p-2 outline-none" style={{ maxHeight: "calc(100vh - 480px)", minHeight: 160 }}>
              {mistakes.length === 0 ? <p className="p-3 text-muted">No mistakes of yours in this game.</p> : mistakes.map(({ m, i }) => (
                <button key={i} onClick={() => { setRetry(false); setPly(i); }} className="flex w-full items-center justify-between rounded px-3 py-2 text-left hover:bg-surface-2 cursor-pointer">
                  <span><span className="tnum text-faint">{Math.floor(i / 2) + 1}.</span> <b>{m.san}</b> <span style={{ color: CLASS_VAR[m.cls] }}>{CLASS_LABEL[m.cls]}</span></span>
                  <span className="tnum text-[12.5px] text-muted">−{(m.loss * 100).toFixed(0)}% win chance</span>
                </button>
              ))}
            </Tabs.Content>
          </Tabs.Root>
        </Panel>

        {!retry && <MoveExplanation fen={ply > 0 ? fens[ply - 1] : fen} move={last} cp={cp} next={next ? uciToSan(fen, next.best) : null} />}
      </aside>
    </div>
  );
}

function PlayerStrip({ name, elo, acc }: { name: string; elo: number; acc: number }) {
  return (
    <div className="flex items-baseline justify-between px-0.5 text-[13.5px]">
      <span className="truncate font-medium">{name} <span className="font-normal text-muted tnum">{elo}</span></span>
      <span className="tnum text-[12px] text-muted">{acc.toFixed(0)}% accuracy</span>
    </div>
  );
}

function MoveExplanation({ fen, move, cp, next }: { fen: string; move: GameRecord["moves"][number] | null; cp: number; next: string | null }) {
  if (!move) return <Panel className="p-4 text-[13px] text-muted">Step through the game with the arrow keys. {next && <>The engine would start with <b className="text-text">{next}</b>.</>}</Panel>;
  const bad = BAD.includes(move.cls);
  const better = bad ? uciToSan(fen, move.best) : null;
  return (
    <Panel className={clsx("p-4 text-[13.5px]")}>
      <div className="flex items-center gap-2"><b style={{ color: CLASS_VAR[move.cls] }}>{move.san} · {CLASS_LABEL[move.cls]}</b><span className="tnum ml-auto text-muted">{formatEval(cp)}</span></div>
      <p className="mt-1.5 text-muted">
        {bad ? <>Gave away about <b className="text-text">{Math.round(move.loss * 100)}%</b> of the win chance. Better was <b className="text-text">{better}</b>.</>
          : move.cls === "best" || move.cls === "brilliant" || move.cls === "great" ? "The engine's top choice." : "A sound move."}
        {next && <> From here the engine likes <b className="text-text">{next}</b>.</>}
      </p>
      {bad && <p className="mt-2 flex items-center gap-1.5 text-[12.5px] text-faint"><Lightbulb size={14} /> Press <kbd className="rounded border border-border px-1">B</kbd> to see it on the board, or retry it from the button above.</p>}
    </Panel>
  );
}
