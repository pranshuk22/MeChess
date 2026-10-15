import { Lightbulb } from "lucide-react";
import { ClassIcon } from "@/components/ClassIcon";
import { pvToSan, uciToSan } from "@/lib/game";
import { BAD, CLASS_LABEL, CLASS_VAR, formatEval, type AnalysedMove } from "@/lib/types";

/** The analysis of the move just played, as chess.com and Lichess show it: its class and evaluation change, and the engine's best lines for the position it was
 *  played in (stored with the game). A click on a line tries it from that position. */
export function MoveCard({ fenBefore, move, cpBefore, next, onTry }: { fenBefore: string; move: AnalysedMove | null; cpBefore: number; next: string | null; onTry: (ucis: string[]) => void }) {
  if (!move) return <p className="text-muted">Step through the game with the arrow keys. {next && <>The engine would start with <b className="text-text">{next}</b>.</>}</p>;
  const bad = BAD.includes(move.cls);
  const lines = move.lines ?? [];
  const playedIn = lines.findIndex((l) => l.uci === move.uci);
  return (
    <div>
      <div className="flex items-center gap-2">
        <ClassIcon cls={move.cls} size={18} />
        <b className="font-semibold" style={{ color: CLASS_VAR[move.cls] }}>{move.san} · {CLASS_LABEL[move.cls]}</b>
        <span className="tnum font-display ml-auto text-[12.5px] text-muted">{formatEval(cpBefore)} → <b className="font-semibold text-text">{formatEval(move.cp)}</b></span>
      </div>
      <p className="mt-1.5 text-[13px] text-muted">
        {bad ? <>Gave away about <b className="text-text">{Math.round(move.loss * 100)}%</b> of the win chance. {lines[0] && <>The engine preferred <b className="text-text">{uciToSan(fenBefore, lines[0].uci)}</b>.</>}</>
          : move.cls === "best" || move.cls === "brilliant" || move.cls === "great" ? "The engine's top choice." : playedIn > 0 ? `The engine's choice number ${playedIn + 1}.` : "A sound move."}
      </p>
      {lines.length > 0 && (
        <ul className="mt-2.5 space-y-0.5">
          {lines.map((l, i) => {
            const san = pvToSan(fenBefore, l.pv, 6);
            const yours = l.uci === move.uci;
            return (
              <li key={i}>
                <button onClick={() => onTry(l.pv)} className={`grid w-full grid-cols-[52px_1fr] items-baseline gap-2.5 rounded-[7px] px-1.5 py-1 text-left text-[12.5px] transition-colors hover:bg-surface-2 cursor-pointer ${yours ? "bg-sunken" : ""}`} title="Try this line from the position before the move">
                  <span className="tnum font-display rounded-[5px] bg-sunken px-1 py-0.5 text-center text-[11.5px] font-semibold" style={yours ? { background: "var(--surface)" } : undefined}>{formatEval(l.cp)}</span>
                  <span className="min-w-0 truncate"><b className="font-semibold">{san[0]}</b> <span className="text-muted">{san.slice(1).join(" ")}</span>{yours && <span className="ml-1.5 text-[11px] font-medium text-accent">your move</span>}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
      {bad && lines.length === 0 && <p className="mt-2 flex items-center gap-1.5 text-[12.5px] text-faint"><Lightbulb size={14} /> Press <kbd className="rounded border border-border px-1 font-mono text-[11px]">B</kbd> to see the better move.</p>}
    </div>
  );
}
