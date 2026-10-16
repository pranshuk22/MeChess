import { Captured } from "./Captured";

export interface Strip { name: string; elo: number | null; colour: "white" | "black"; acc?: number | null; perf?: number | null; taken?: string[]; lead?: number; clock?: number | null; title?: string }

const fmtClock = (s: number) => (s >= 3600 ? `${Math.floor(s / 3600)}:${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}:${String(Math.floor(s % 60)).padStart(2, "0")}` : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`);

/** Above and below the board: who, their rating, what they have taken, and (when known) accuracy, performance and the clock. */
export function PlayerStrip({ name, elo, colour, acc = null, perf = null, taken = [], lead = 0, clock = null, title }: Strip) {
  return (
    <div className="flex min-h-7 items-center justify-between gap-3 px-0.5 text-[13.5px]">
      <span className="flex min-w-0 items-center gap-2"><span className="h-3 w-3 shrink-0 rounded-[3px] border" style={{ background: colour === "white" ? "#fff" : "#2b3139", borderColor: "var(--border-strong)" }} aria-hidden />
        <span className="truncate font-semibold">{name}</span>{elo ? <span className="tnum text-muted">{elo}</span> : null}
        <Captured taken={taken} takenColour={colour === "white" ? "b" : "w"} lead={lead} /></span>
      <span className="flex shrink-0 items-center gap-3 text-[12.5px] text-muted">
        {perf !== null && <span className="tnum" title={title ?? "Estimated performance in this game"}>perf <b className="font-semibold text-text">{perf}</b></span>}
        {acc !== null && <span className="tnum" title="Accuracy">{acc.toFixed(0)}%</span>}
        {clock !== null && <span className="tnum rounded-[5px] bg-sunken px-1.5 py-0.5 font-medium text-text">{fmtClock(clock)}</span>}
      </span>
    </div>
  );
}
