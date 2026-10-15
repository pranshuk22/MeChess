import { Eye, Lightbulb, RotateCcw, SkipForward, Target } from "lucide-react";
import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Drill, DrillStats } from "@/api/hooks";
import { Board } from "@/board/Board";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";
import { Progress } from "@/components/ui/Misc";
import { checkSquare, legalMap } from "@/lib/game";
import { FeedbackCard, type Feedback } from "./Feedback";

interface Answer { bestSan: string; bestUci: string; explanation: string; playedSan: string }
type Phase = { kind: "find" } | { kind: "wrong" } | { kind: "done"; ok: boolean; firstTry: boolean; verdict: string; loss: number | null; answer: Answer; fb: Feedback | null };
type Attempt = { verdict: string; loss: number | null; recorded?: string } & Partial<Answer> & Partial<Feedback>;

/** A practice session: the due positions one by one. Find a better move than the one you played; hints in three steps; the engine judges your try. */
export function Practice({ items, onFinish }: { items: Drill[]; onFinish: (found: number, total: number) => void }) {
  const qc = useQueryClient();
  const [i, setI] = useState(0);
  const [phase, setPhase] = useState<Phase>({ kind: "find" });
  const [tries, setTries] = useState(0);
  const [hints, setHints] = useState(0);
  const [hintText, setHintText] = useState<string[]>([]);
  const [found, setFound] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [lastFb, setLastFb] = useState<Feedback | null>(null);                     // what the last wrong try allowed, shown until the next try
  const [bonus, setBonus] = useState(false);                                       // trying for the best after a good move was accepted (nothing is recorded again)
  const d = items[i];
  const legal = useMemo(() => (phase.kind === "find" || bonus ? legalMap(d.fen) : undefined), [d.fen, phase.kind, bonus]);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["drills"] }); };

  const onMove = async (from: string, to: string, promo?: string) => {
    if (busy) return;
    setBusy(true); setError("");
    const uci = from + to + (promo ?? "");
    try {
      if (bonus) {                                                                 // a second look at a position that is already solved: feedback only
        const fb = await api<Feedback>("/api/coach/feedback", { method: "POST", json: { fen: d.fen, uci, hide_best: false } });
        setBonus(false);
        setPhase((p) => (p.kind === "done" ? { ...p, fb, loss: fb.loss, verdict: fb.grade === "best" ? "found" : "ok" } : p));
        return;
      }
      const r = await api<Attempt>(`/api/coach/drills/${d.id}/attempt`, { method: "POST", json: { uci, tries, hints } });
      const fb = r.reasons ? (r as unknown as Feedback) : null;
      if (r.verdict === "wrong") { setLastFb(fb); setPhase({ kind: "wrong" }); setTries((t) => t + 1); setTimeout(() => setPhase({ kind: "find" }), 1400); }
      else {
        const firstTry = tries === 0 && hints === 0;
        setLastFb(null);
        setPhase({ kind: "done", ok: true, firstTry, verdict: r.verdict, loss: r.loss, answer: r as Answer, fb });
        if (firstTry) setFound((f) => f + 1);
        refresh();
      }
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };
  const hint = async () => {
    const level = Math.min(3, hints + 1);
    try { const r = await api<{ text: string }>(`/api/coach/drills/${d.id}/hint?level=${level}`); setHints(level); setHintText((h) => [...h, r.text]); } catch (e) { setError((e as Error).message); }
  };
  const reveal = async () => {
    try { const r = await api<Answer>(`/api/coach/drills/${d.id}/reveal`, { method: "POST" }); setPhase({ kind: "done", ok: false, firstTry: false, verdict: "revealed", loss: null, answer: r, fb: null }); setLastFb(null); refresh(); } catch (e) { setError((e as Error).message); }
  };
  const next = () => {
    if (i + 1 >= items.length) { onFinish(found, items.length); return; }
    setI(i + 1); setPhase({ kind: "find" }); setTries(0); setHints(0); setHintText([]); setError(""); setLastFb(null); setBonus(false);
  };
  const showBest = phase.kind === "done" ? phase.answer.bestUci : null;
  const fen = d.fen;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_380px] gap-6 max-lg:grid-cols-1">
      <div className="mx-auto w-full" style={{ maxWidth: "min(100%, calc(100dvh - 180px))" }}>
        <div className="mb-2 flex items-center justify-between text-[13px] text-muted"><span className="tnum">Position {i + 1} of {items.length}</span><span>{d.colour === "white" ? "White" : "Black"} to move</span></div>
        <Progress value={(i + (phase.kind === "done" ? 1 : 0)) / items.length} className="mb-3" />
        <div className="overflow-hidden rounded-[6px] shadow-[0_1px_2px_rgba(16,24,32,0.12),0_12px_32px_-12px_rgba(16,24,32,0.3)]">
          <Board fen={fen} orientation={d.colour} legal={legal} movable={phase.kind === "find" || bonus ? (d.colour === "white" ? "w" : "b") : null} checkSquare={checkSquare(fen)} onMove={onMove}
            arrows={showBest ? [{ from: showBest.slice(0, 2), to: showBest.slice(2, 4), kind: "best" }] : []} />
        </div>
      </div>
      <div className="space-y-4">
        <Panel className="p-5" aria-live="polite">
          <div className="text-[12px] text-muted">From your game · move {d.move} · {d.phase}</div>
          {phase.kind !== "done" && <>
            <h2 className="mt-1 text-[18px] font-semibold leading-6">Find a better move</h2>
            <p className="mt-2 text-[13.5px] text-muted">You played <b className="text-text">{d.playedSan}</b> here{d.loss ? ` and gave away about ${Math.round(d.loss * 100)}% of the win chance` : ""}.</p>
            {lastFb && <div className="mt-3"><FeedbackCard fb={lastFb} compact /><p className="mt-2 text-[12.5px] text-muted">Try another move.</p></div>}
            {hintText.map((h, k) => <p key={k} className="mt-3 flex gap-2 rounded-[9px] bg-sunken px-3 py-2 text-[13px]"><Lightbulb size={15} className="mt-0.5 shrink-0 text-[var(--q-inaccuracy)]" />{h}</p>)}
            <div className="mt-4 flex flex-wrap gap-2">
              <Button size="sm" onClick={hint} disabled={hints >= 3}><Lightbulb size={14} /> {hints === 0 ? "Hint" : hints < 3 ? "Another hint" : "No more hints"}</Button>
              <Button size="sm" variant="ghost" onClick={reveal}><Eye size={14} /> Show me</Button>
            </div>
          </>}
          {phase.kind === "done" && <>
            {phase.fb && phase.ok ? <div className="mt-2"><FeedbackCard fb={phase.fb} /></div>
              : <div className="mt-1 flex items-center gap-2 text-[18px] font-semibold" style={{ color: "var(--q-mistake)" }}><RotateCcw size={20} />{`The move was ${phase.answer.bestSan}`}</div>}
            {phase.fb?.bestWhy && phase.fb.grade !== "best" && <p className="mt-2 text-[13px] text-muted"><b className="text-text">The best move: </b>{phase.fb.bestWhy.join(" ")}</p>}
            {phase.fb && phase.fb.grade !== "best" && phase.ok && (phase.fb.alternatives?.length ?? 0) > 0 && <p className="mt-2 text-[13px] text-muted">Other good moves: {phase.fb.alternatives!.join(", ")}.</p>}
            <p className="mt-3 text-[12.5px] text-faint">In your game: {phase.answer.explanation}</p>
            <p className="mt-2 text-[12.5px] text-faint">{phase.firstTry ? "First try without a hint: it comes back later than before." : "It will come back soon, until you find it on your own."}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {phase.ok && phase.fb && phase.fb.grade !== "best" && <Button size="sm" onClick={() => { setBonus(true); setError(""); }}><Target size={14} /> Try for the best</Button>}
              <Button variant="primary" onClick={next}>{i + 1 >= items.length ? "Finish" : <>Next <SkipForward size={14} /></>}</Button>
            </div>
            {bonus && <p className="mt-2 text-[12.5px] text-muted">Make a move on the board to see how it compares.</p>}
          </>}
          {error && <p role="alert" className="mt-3 text-[13px] text-[var(--q-blunder)]">{error}</p>}
        </Panel>
      </div>
    </div>
  );
}

export type { DrillStats };
