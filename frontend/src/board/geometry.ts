import type { Colour, PieceInfo, Role } from "./pieces";

export const FILES = "abcdefgh";
export type Orientation = "white" | "black";

/** "e4" -> [file 0..7, rank 0..7] */
export function sqToCoords(sq: string): [number, number] {
  return [sq.charCodeAt(0) - 97, sq.charCodeAt(1) - 49];
}
export function coordsToSq(file: number, rank: number): string {
  return FILES[file] + (rank + 1);
}
/** Column and row on screen (0..7 from the top-left) of a square for the given orientation. */
export function sqToView(sq: string, o: Orientation): [number, number] {
  const [f, r] = sqToCoords(sq);
  return o === "white" ? [f, 7 - r] : [7 - f, r];
}
export function viewToSq(col: number, row: number, o: Orientation): string {
  return o === "white" ? coordsToSq(col, 7 - row) : coordsToSq(7 - col, row);
}

export interface PlacedPiece extends PieceInfo { sq: string }

/** Pieces of a FEN placement field. */
export function parsePieces(fen: string): PlacedPiece[] {
  const out: PlacedPiece[] = [];
  const rows = fen.split(" ")[0].split("/");
  rows.forEach((row, i) => {
    let file = 0;
    for (const ch of row) {
      if (ch >= "1" && ch <= "8") { file += Number(ch); continue; }
      const colour: Colour = ch === ch.toUpperCase() ? "w" : "b";
      out.push({ colour, role: ch.toLowerCase() as Role, sq: coordsToSq(file, 7 - i) });
      file++;
    }
  });
  return out;
}

export interface KeyedPiece extends PlacedPiece { id: number }

let nextId = 1;
/** Keep a piece's identity across positions so a move animates: pieces that did not move keep their id, the others take the nearest unmatched piece of the
 *  same kind (handles captures, castling and promotion without being told the move). */
export function matchPieces(prev: KeyedPiece[], next: PlacedPiece[]): KeyedPiece[] {
  const free = new Map<string, KeyedPiece[]>();
  const result: (KeyedPiece | null)[] = next.map(() => null);
  const prevAt = new Map(prev.map((p) => [p.sq, p]));
  const used = new Set<number>();
  next.forEach((n, i) => {
    const p = prevAt.get(n.sq);
    if (p && p.colour === n.colour && p.role === n.role) { result[i] = { ...n, id: p.id }; used.add(p.id); }
  });
  for (const p of prev) if (!used.has(p.id)) { const k = p.colour + p.role; (free.get(k) ?? free.set(k, []).get(k)!).push(p); }
  next.forEach((n, i) => {
    if (result[i]) return;
    const list = free.get(n.colour + n.role);
    if (list?.length) {
      const [nf, nr] = sqToCoords(n.sq);
      let best = 0, bd = Infinity;
      list.forEach((p, j) => { const [pf, pr] = sqToCoords(p.sq); const d = Math.abs(pf - nf) + Math.abs(pr - nr); if (d < bd) { bd = d; best = j; } });
      const [p] = list.splice(best, 1);
      result[i] = { ...n, id: p.id };
    }
  });
  return next.map((n, i) => result[i] ?? { ...n, id: nextId++ });
}
