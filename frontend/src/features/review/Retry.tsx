import { Eye, Lightbulb, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Board } from "@/board/Board";
import type { Arrow } from "@/board/Arrows";
import type { Orientation } from "@/board/geometry";
import type { PieceSet } from "@/board/pieces";
import { Button } from "@/components/ui/Button";
import { applyUci, checkSquare, fensFromUci, legalMap, uciToSan } from "@/lib/game";
import type { AnalysedMove, GameRecord } from "@/lib/types";
import { Panel } from "@/components/ui/Panel";

type Status = "find" | "wrong" | "right" | "revealed";

/** Guided replay: the position before one of your mistakes; find a better move, hints in steps, reveal, then play on. (Prototype: judged against the engine's first
 *  choice stored with the game; the real judge in the app uses the live engine.) */
export function Retry({ game, mistakes, orientation, pieceSet, showCoords, onExit }: {
  game: GameRecord; mistakes: { m: AnalysedMove; i: number }[]; orientation: Orientation; pieceSet: PieceSet; showCoords: boolean; onExit: () => void;
}) {
  const fens = useMemo(() => fensFromUci(game.moves.map((m) => m.uci)), [game]);
  const [k, setK] = useState(0);
  const [status, setStatus] = useState<Status>("find");
  const [hint, setHint] = useState(0);
  const [fen, setFen] = useState(fens[mistakes[0].i]);
  const [last, setLast] = useState<[string, string] | null>(null);
  const [tries, setTries] = useState(0);
  const cur = mistakes[k];
  const start = fens[cur.i];
  const userColour = game.user === "white" ? "w" : "b";

  const go = (nk: number) => { setK(nk); setStatus("find"); setHint(0); setTries(0); setFen(fens[mistakes[nk].i]); setLast(null); };
  const onMove = (from: string, to: string, promotion?: string) => {
    const uci = from + to + (promotion ?? "");
    const after = applyUci(start, uci);
    if (!after) return;
    setFen(after); setLast([from, to]);
    if (uci === cur.m.best) setStatus("right");
    else { setStatus("wrong"); setTries((t) => t + 1); }
  };
  const reset = () => { setFen(start); setLast(null); setStatus("find"); };
  const reveal = () => { const a = applyUci(start, cur.m.best); if (a) { setFen(a); setLast([cur.m.best.slice(0, 2), cur.m.best.slice(2, 4)]); } setStatus("revealed"); };

  const interactive = status === "find";
  const legal = useMemo(() => (interactive ? legalMap(fen) : new Map()), [fen, interactive]);
  const arrows: Arrow[] = status === "revealed" || status === "right" ? [{ from: cur.m.best.slice(0, 2), to: cur.m.best.slice(2, 4), kind: "best" }] : [];
  const marks = hint === 1 && status === "find" ? [cur.m.best.slice(0, 2)] : [];
  const bestSan = uciToSan(start, cur.m.best), playedSan = cur.m.san;

  return (
    <div>
      <Board fen={fen} orientation={orientation} legal={legal} movable={userColour} lastMove={last} checkSquare={checkSquare(fen)} arrows={arrows} marks={marks} pieceSet={pieceSet} showCoords={showCoords} onMove={onMove} />
      <Panel className="mt-3 p-3.5" aria-live="polite">
        <div className="flex items-center gap-2 text-[12px] text-muted">
          <span className="tnum">Mistake {k + 1} of {mistakes.length}</span><span>· move {Math.floor(cur.i / 2) + 1}</span>
          <button className="ml-auto cursor-pointer rounded p-1 hover:bg-surface-2" onClick={onExit} aria-label="Leave the retry"><X size={15} /></button>
        </div>
        {status === "find" && <p className="mt-1 text-[14px]">You played <b>{playedSan}</b> here and gave away {Math.round(cur.m.loss * 100)}% of the win chance. <b>Find a better move.</b></p>}
        {status === "wrong" && <p className="mt-1 text-[14px]">Not the engine's choice. {tries >= 2 ? "Try the hint, or reveal the answer." : "Take it back and try again."}</p>}
        {status === "right" && <p className="mt-1 text-[14px]"><b style={{ color: "var(--q-best)" }}>Yes, {bestSan}.</b> That avoids the loss you made with {playedSan}. Play on from the next mistake, or look at the position again.</p>}
        {status === "revealed" && <p className="mt-1 text-[14px]">The better move was <b>{bestSan}</b>; you played {playedSan}.</p>}
        <div className="mt-3 flex flex-wrap gap-2">
          {status === "wrong" && <Button size="sm" onClick={reset}>Try again</Button>}
          {(status === "find" || status === "wrong") && <>
            <Button size="sm" onClick={() => { if (status === "wrong") reset(); setHint(hint + 1); if (hint >= 1) reveal(); }}><Lightbulb size={14} /> {hint === 0 ? "Hint" : "Show the move"}</Button>
            <Button size="sm" variant="ghost" onClick={reveal}><Eye size={14} /> Reveal</Button>
          </>}
          {(status === "right" || status === "revealed") && <>
            <Button size="sm" onClick={() => go(k)}>Try again</Button>
            {k + 1 < mistakes.length ? <Button size="sm" variant="primary" onClick={() => go(k + 1)}>Next mistake</Button> : <Button size="sm" variant="primary" onClick={onExit}>Done</Button>}
          </>}
        </div>
      </Panel>
    </div>
  );
}
