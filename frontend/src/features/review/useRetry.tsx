import { Eye, Lightbulb, X } from "lucide-react";
import { useMemo, useState } from "react";
import type { Arrow } from "@/board/Arrows";
import { Button } from "@/components/ui/Button";
import { applyUci, fensFromUci, legalMap, uciToSan } from "@/lib/game";
import type { AnalysedMove, GameDetail } from "@/lib/types";

type Status = "find" | "wrong" | "right" | "revealed";

/** Guided replay: the position before one of the player's mistakes; find a better move, hints in steps, reveal, then the next mistake. The board props and the
 *  prompt are returned separately so the prompt can sit beside the board (the board never changes size). Prototype: judged against the engine's first choice stored
 *  with the game; the real judge in the app uses the live engine. */
export function useRetry(game: GameDetail, mistakes: { m: AnalysedMove; i: number }[], active: boolean, onExit: () => void) {
  const fens = useMemo(() => fensFromUci(game.moves.map((m) => m.uci)), [game]);
  const [k, setK] = useState(0);
  const [status, setStatus] = useState<Status>("find");
  const [hint, setHint] = useState(0);
  const [fen, setFen] = useState<string | null>(null);
  const [last, setLast] = useState<[string, string] | null>(null);
  const [tries, setTries] = useState(0);
  const cur = mistakes[k];
  const start = cur ? fens[cur.i] : "";
  const shown = fen ?? start;

  const go = (nk: number) => { setK(nk); setStatus("find"); setHint(0); setTries(0); setFen(null); setLast(null); };
  const reset = () => { setFen(null); setLast(null); setStatus("find"); };
  const reveal = () => { const a = applyUci(start, cur.m.best); if (a) { setFen(a); setLast([cur.m.best.slice(0, 2), cur.m.best.slice(2, 4)]); } setStatus("revealed"); };
  const exit = () => { go(0); onExit(); };
  const onMove = (from: string, to: string, promotion?: string) => {
    const uci = from + to + (promotion ?? "");
    const after = applyUci(start, uci);
    if (!after) return;
    setFen(after); setLast([from, to]);
    if (uci === cur.m.best) setStatus("right");
    else { setStatus("wrong"); setTries((t) => t + 1); }
  };

  const interactive = active && cur && status === "find";
  const legal = useMemo(() => (interactive ? legalMap(shown) : new Map<string, string[]>()), [shown, interactive]);
  if (!active || !cur) return null;
  const arrows: Arrow[] = status === "revealed" || status === "right" ? [{ from: cur.m.best.slice(0, 2), to: cur.m.best.slice(2, 4), kind: "best" }] : [];
  const marks = hint === 1 && status === "find" ? [cur.m.best.slice(0, 2)] : [];
  const bestSan = uciToSan(start, cur.m.best), playedSan = cur.m.san;

  const panel = (
    <div aria-live="polite">
      <div className="flex items-center gap-2 text-[12px] text-muted">
        <span className="tnum">Mistake {k + 1} of {mistakes.length}</span><span>· move {Math.floor(cur.i / 2) + 1}</span>
        <button className="ml-auto cursor-pointer rounded p-1 hover:bg-surface-2" onClick={exit} aria-label="Leave the retry"><X size={15} /></button>
      </div>
      {status === "find" && <p className="mt-1 text-[14px]">You played <b>{playedSan}</b> here and gave away {Math.round(cur.m.loss * 100)}% of the win chance. <b>Find a better move.</b></p>}
      {status === "wrong" && <p className="mt-1 text-[14px]">Not the engine's choice. {tries >= 2 ? "Try the hint, or reveal the answer." : "Take it back and try again."}</p>}
      {status === "right" && <p className="mt-1 text-[14px]"><b style={{ color: "var(--q-best)" }}>Yes, {bestSan}.</b> That avoids the loss you made with {playedSan}.</p>}
      {status === "revealed" && <p className="mt-1 text-[14px]">The better move was <b>{bestSan}</b>; you played {playedSan}.</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        {status === "wrong" && <Button size="sm" onClick={reset}>Try again</Button>}
        {(status === "find" || status === "wrong") && <>
          <Button size="sm" onClick={() => { if (status === "wrong") reset(); setHint(hint + 1); if (hint >= 1) reveal(); }}><Lightbulb size={14} /> {hint === 0 ? "Hint" : "Show the move"}</Button>
          <Button size="sm" variant="ghost" onClick={reveal}><Eye size={14} /> Reveal</Button>
        </>}
        {(status === "right" || status === "revealed") && <>
          <Button size="sm" onClick={() => go(k)}>Try again</Button>
          {k + 1 < mistakes.length ? <Button size="sm" variant="primary" onClick={() => go(k + 1)}>Next mistake</Button> : <Button size="sm" variant="primary" onClick={exit}>Done</Button>}
        </>}
      </div>
    </div>
  );
  return { fen: shown, lastMove: last, legal, arrows, marks, onMove, panel };
}
