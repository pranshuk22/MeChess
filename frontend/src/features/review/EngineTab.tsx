import { Cpu } from "lucide-react";
import { formatScore, type Live } from "@/api/live";
import { Select } from "@/components/ui/Field";

/** The engine's lines for the position on the board; a click plays the line's first move. */
export function EngineTab({ enabled, onToggle, live, multipv, onMultipv, onPlay }: { enabled: boolean; onToggle: (v: boolean) => void; live: Live; multipv: number; onMultipv: (n: number) => void; onPlay: (uci: string) => void }) {
  return (
    <div className="p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <label className="flex cursor-pointer items-center gap-2.5 text-[13.5px] font-medium">
          <button role="switch" aria-checked={enabled} onClick={() => onToggle(!enabled)} className={`relative h-5 w-9 rounded-full transition-colors cursor-pointer ${enabled ? "bg-accent" : "bg-[var(--border-strong)]"}`}>
            <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-[left] ${enabled ? "left-[18px]" : "left-0.5"}`} />
          </button>
          Engine
          {enabled && live.cached && live.lines.length > 0 && <span className="rounded-full bg-accent-soft px-2 py-0.5 text-[11px] font-medium text-accent" title="Stored from an earlier analysis of this position; the engine is working on something deeper">cached</span>}
        </label>
        <div className="flex items-center gap-2 text-[12.5px] text-muted">Lines <div className="w-16"><Select value={multipv} onChange={(e) => onMultipv(Number(e.target.value))} className="!h-8 !px-2" aria-label="Number of lines">{[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n}</option>)}</Select></div></div>
      </div>
      {!enabled && <p className="text-[13px] text-muted">Turn the engine on to see the best moves for any position you step to or set up on the board. It runs on this computer.</p>}
      {enabled && live.status === "error" && <p role="alert" className="rounded-[9px] bg-[color-mix(in_srgb,var(--q-blunder)_10%,transparent)] px-3 py-2 text-[13px] text-[var(--q-blunder)]">{live.error}</p>}
      {enabled && live.status !== "error" && live.lines.length === 0 && <p className="flex items-center gap-2 text-[13px] text-muted"><Cpu size={15} className="animate-pulse" /> {live.status === "connecting" ? "Connecting to the engine…" : "Thinking…"}</p>}
      <ol className="space-y-1.5">
        {enabled && live.lines.map((l) => (
          <li key={l.multipv}>
            <button onClick={() => onPlay(l.uci[0])} className="grid w-full grid-cols-[62px_1fr] items-start gap-3 rounded-[9px] px-2.5 py-2 text-left transition-colors hover:bg-surface-2 cursor-pointer">
              <span className="tnum font-display rounded-[6px] bg-sunken px-1.5 py-0.5 text-center text-[12.5px] font-semibold">{formatScore(l.kind, l.score)}</span>
              <span className="min-w-0"><span className="block text-[13.5px] leading-5"><b className="font-semibold">{l.san[0]}</b> <span className="text-muted">{l.san.slice(1, 9).join(" ")}</span></span><span className="text-[11.5px] text-faint">depth {l.depth}</span></span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
