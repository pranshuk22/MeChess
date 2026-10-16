import { BAD, type AnalysedMove } from "./types";

export interface Moment { ply: number; kind: "book" | "brilliant" | "great" | "mine-bad" | "opp-bad-punished" | "opp-bad-missed"; label: string; mine: boolean; move: AnalysedMove }

/** The moments worth stopping at, in game order: the last move of opening theory, your brilliant and great moves, your mistakes, and the opponent's mistakes (with whether you punished them).
 *  `ply` is the half-move number (1 = White's first move). */
export function keyMoments(moves: AnalysedMove[], userIsWhite: boolean, bookEnd: number): Moment[] {
  const out: Moment[] = [];
  if (bookEnd > 1 && bookEnd <= moves.length) out.push({ ply: bookEnd, kind: "book", label: `Last move of opening theory (move ${Math.ceil(bookEnd / 2)})`, mine: false, move: moves[bookEnd - 1] });
  moves.forEach((m, i) => {
    const mine = (i % 2 === 0) === userIsWhite;
    if (mine && (m.cls === "brilliant" || m.cls === "great")) out.push({ ply: i + 1, kind: m.cls, label: m.cls === "brilliant" ? "A brilliant move" : "A great move", mine, move: m });
    else if (mine && BAD.includes(m.cls) && m.loss >= 0.1) out.push({ ply: i + 1, kind: "mine-bad", label: m.cls === "miss" ? "A missed chance" : m.cls === "blunder" ? "A blunder" : "A mistake", mine, move: m });
    else if (!mine && BAD.includes(m.cls) && m.loss >= 0.15) {
      const reply = moves[i + 1];
      const punished = !!reply && reply.loss <= 0.05;
      out.push({ ply: i + 1, kind: punished ? "opp-bad-punished" : "opp-bad-missed", label: punished ? "The opponent erred and you took advantage" : "The opponent erred and it was not punished", mine, move: m });
    }
  });
  return out.sort((a, b) => a.ply - b.ply).filter((m, i, all) => i === 0 || m.ply !== all[i - 1].ply);
}

/** The next moment after `ply` (wrapping to the first), or the previous one before it. */
export function stepMoment(moments: Moment[], ply: number, dir: 1 | -1): Moment | null {
  if (!moments.length) return null;
  if (dir === 1) return moments.find((m) => m.ply > ply) ?? moments[0];
  return [...moments].reverse().find((m) => m.ply < ply) ?? moments[moments.length - 1];
}
