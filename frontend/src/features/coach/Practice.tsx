import { CheckCircle2, Eye, Lightbulb, RotateCcw, SkipForward, XCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Drill, DrillStats } from "@/api/hooks";
import { Board } from "@/board/Board";
import { Button } from "@/components/ui/Button";
import { Panel } from "@/components/ui/Panel";
import { Progress } from "@/components/ui/Misc";
import { checkSquare, legalMap } from "@/lib/game";

interface Answer { bestSan: string; bestUci: string; explanation: string; playedSan: string }
type Phase = { kind: "find" } | { kind: "wrong"; loss: number } | { kind: "done"; ok: boolean; firstTry: boolean; verdict: string; loss: number | null; answer: Answer };

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
  const d = items[i];
  const legal = useMemo(() => (phase.kind === "find" ? legalMap(d.fen) : undefined), [d.fen, phase.kind]);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["drills"] }); };

  const onMove = async (from: string, to: string, promo?: string) => {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const r = await api<{ verdict: string; loss: number | null; recorded?: string } & Partial<Answer>>(`/api/coach/drills/${d.id}/attempt`, { method: "POST", json: { uci: from + to + (promo ?? ""), tries, hints } });
      if (r.verdict === "wrong") { setPhase({ kind: "wrong", loss: r.loss ?? 0 }); setTries((t) => t + 1); setTimeout(() => setPhase({ kind: "find" }), 1400); }
      else {
        const firstTry = tries === 0 && hints === 0;
        setPhase({ kind: "done", ok: true, firstTry, verdict: r.verdict, loss: r.loss, answer: r as Answer });
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
    try { const r = await api<Answer>(`/api/coach/drills/${d.id}/reveal`, { method: "POST" }); setPhase({ kind: "done", ok: false, firstTry: false, verdict: "revealed", loss: null, answer: r }); refresh(); } catch (e) { setError((e as Error).message); }
  };
  const next = () => {
    if (i + 1 >= items.length) { onFinish(found, items.length); return; }
    setI(i + 1); setPhase({ kind: "find" }); setTries(0); setHints(0); setHintText([]); setError("");
  };
  const showBest = phase.kind === "done" ? phase.answer.bestUci : null;
  const fen = d.fen;

  return (
    <div className="grid grid-cols-[minmax(0,1fr)_380px] gap-6 max-lg:grid-cols-1">
      <div className="mx-auto w-full" style={{ maxWidth: "min(100%, calc(100dvh - 180px))" }}>
        <div className="mb-2 flex items-center justify-between text-[13px] text-muted"><span className="tnum">Position {i + 1} of {items.length}</span><span>{d.colour === "white" ? "White" : "Black"} to move</span></div>
        <Progress value={(i + (phase.kind === "done" ? 1 : 0)) / items.length} className="mb-3" />
        <div className="overflow-hidden rounded-[6px] shadow-[0_1px_2px_rgba(16,24,32,0.12),0_12px_32px_-12px_rgba(16,24,32,0.3)]">
          <Board fen={fen} orientation={d.colour} legal={legal} movable={phase.kind === "find" ? (d.colour === "white" ? "w" : "b") : null} checkSquare={checkSquare(fen)} onMove={onMove}
            arrows={showBest ? [{ from: showBest.slice(0, 2), to: showBest.slice(2, 4), kind: "best" }] : []} />
        </div>
      </div>
      <div className="space-y-4">
        <Panel className="p-5" aria-live="polite">
          <div className="text-[12px] text-muted">From your game · move {d.move} · {d.phase}</div>
          {phase.kind !== "done" && <>
            <h2 className="mt-1 text-[18px] font-semibold leading-6">Find a better move</h2>
            <p className="mt-2 text-[13.5px] text-muted">You played <b className="text-text">{d.playedSan}</b> here{d.loss ? ` and gave away about ${Math.round(d.loss * 100)}% of the win chance` : ""}.</p>
            {phase.kind === "wrong" && <p className="mt-3 flex items-center gap-2 text-[13.5px] text-[var(--q-mistake)]"><XCircle size={16} /> Not quite: that costs about {Math.round(phase.loss * 100)}%. Try again.</p>}
            {hintText.map((h, k) => <p key={k} className="mt-3 flex gap-2 rounded-[9px] bg-sunken px-3 py-2 text-[13px]"><Lightbulb size={15} className="mt-0.5 shrink-0 text-[var(--q-inaccuracy)]" />{h}</p>)}
            <div className="mt-4 flex flex-wrap gap-2">
              <Button size="sm" onClick={hint} disabled={hints >= 3}><Lightbulb size={14} /> {hints === 0 ? "Hint" : hints < 3 ? "Another hint" : "No more hints"}</Button>
              <Button size="sm" variant="ghost" onClick={reveal}><Eye size={14} /> Show me</Button>
            </div>
          </>}
          {phase.kind === "done" && <>
            <div className="mt-1 flex items-center gap-2 text-[18px] font-semibold" style={{ color: phase.ok ? "var(--q-best)" : "var(--q-mistake)" }}>{phase.ok ? <CheckCircle2 size={20} /> : <RotateCcw size={20} />}{phase.ok ? (phase.verdict === "found" ? `Yes, ${phase.answer.bestSan}` : "A good move") : `The move was ${phase.answer.bestSan}`}</div>
            <p className="mt-2 text-[13.5px] text-muted">{phase.ok && phase.verdict === "ok" && <>The engine's choice was <b className="text-text">{phase.answer.bestSan}</b>; yours costs almost nothing. </>}{phase.answer.explanation}</p>
            <p className="mt-2 text-[12.5px] text-faint">{phase.firstTry ? "First try without a hint: it comes back later than before." : "It will come back soon, until you find it on your own."}</p>
            <div className="mt-4 flex gap-2"><Button variant="primary" onClick={next}>{i + 1 >= items.length ? "Finish" : <>Next <SkipForward size={14} /></>}</Button></div>
          </>}
          {error && <p role="alert" className="mt-3 text-[13px] text-[var(--q-blunder)]">{error}</p>}
        </Panel>
      </div>
    </div>
  );
}

export type { DrillStats };
