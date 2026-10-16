import { Lightbulb } from "lucide-react";
import type { ReactNode } from "react";
import { ClassIcon } from "@/components/ClassIcon";
import { pvToSan, uciToSan } from "@/lib/game";
import { BAD, CLASS_LABEL, CLASS_VAR, formatEval, type AnalysedMove } from "@/lib/types";

/** The coach card, pinned above the move list: the move just played with its class, the evaluation change, plain-language reasons (from the server) and the engine's best lines for the
 *  position it was played in (a click tries a line). `actions` holds the buttons (retry, next key moment). */
export function CoachCard({ fenBefore, move, cpBefore, next, onTry, actions }: { fenBefore: string; move: AnalysedMove | null; cpBefore: number; next: string | null; onTry: (ucis: string[]) => void; actions?: ReactNode }) {
  if (!move) return (
    <div>
      <p className="text-[13.5px] text-muted">Step through the game with the arrow keys, or jump to a key moment. {next && <>The engine would start with <b className="text-text">{next}</b>.</>}</p>
      {actions && <div className="mt-3 flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
  const bad = BAD.includes(move.cls);
  const lines = (move.lines ?? []).slice(0, 3);
  const why = move.why?.length ? move.why.join(" ") : bad ? `Gave away about ${Math.round(move.loss * 100)}% of the win chance.` : move.cls === "best" || move.cls === "great" || move.cls === "brilliant" ? "The engine's top choice." : "A sound move.";
  return (
    <div>
      <div className="flex items-center gap-2">
        <ClassIcon cls={move.cls} size={20} />
        <b className="text-[14.5px] font-semibold" style={{ color: `color-mix(in srgb, ${CLASS_VAR[move.cls]} 60%, var(--text))` }}>{move.san} · {CLASS_LABEL[move.cls]}</b>
        <span className="tnum ml-auto text-[12.5px] text-muted">{formatEval(cpBefore)} → <b className="font-semibold text-text">{formatEval(move.cp)}</b></span>
      </div>
      <p className="mt-2 text-[13.5px] leading-[1.45]">{why}</p>
      {lines.length > 0 && (
        <ul className="mt-2.5 space-y-0.5" aria-label="Engine lines for the position before this move">
          {lines.map((l, i) => {
            const san = pvToSan(fenBefore, l.pv, 6);
            const yours = l.uci === move.uci;
            return (
              <li key={i}>
                <button onClick={() => onTry(l.pv)} className={`grid w-full grid-cols-[52px_1fr] items-baseline gap-2.5 rounded-[5px] px-1.5 py-1 text-left text-[12.5px] transition-colors hover:bg-surface-2 cursor-pointer ${yours ? "bg-sunken" : ""}`} title="Try this line from the position before the move">
                  <span className="tnum rounded-[5px] bg-sunken px-1 py-0.5 text-center text-[11.5px] font-semibold" style={yours ? { background: "var(--surface)" } : undefined}>{formatEval(l.cp)}</span>
                  <span className="min-w-0 truncate"><b className="font-semibold">{san[0]}</b> <span className="text-muted">{san.slice(1).join(" ")}</span>{yours && <span className="ml-1.5 text-[11px] font-medium text-accent">your move</span>}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {bad && lines.length === 0 && <p className="mt-2 flex items-center gap-1.5 text-[12.5px] text-faint"><Lightbulb size={14} /> Press <kbd className="rounded border border-border px-1 font-mono text-[11px]">B</kbd> to see the better move.</p>}
      {move.lines?.[0] && bad && <p className="sr-only">The engine preferred {uciToSan(fenBefore, move.lines[0].uci)}.</p>}
      {actions && <div className="mt-3 flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}
