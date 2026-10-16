import { Chess } from "chess.js";

export const START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

/** Legal destination squares per origin square for the side to move. */
export function legalMap(fen: string): Map<string, string[]> {
  const map = new Map<string, string[]>();
  const chess = new Chess(fen);
  for (const m of chess.moves({ verbose: true })) {
    const list = map.get(m.from);
    if (list) list.push(m.to); else map.set(m.from, [m.to]);
  }
  return map;
}

/** The king's square when the side to move is in check, else null. */
export function checkSquare(fen: string): string | null {
  const chess = new Chess(fen);
  if (!chess.inCheck()) return null;
  const turn = chess.turn();
  for (const row of chess.board()) for (const p of row) if (p && p.type === "k" && p.color === turn) return p.square;
  return null;
}

/** FENs after each ply of a UCI move list (index 0 = start position). */
export function fensFromUci(uci: string[]): string[] {
  const chess = new Chess();
  const fens = [chess.fen()];
  for (const u of uci) {
    try { chess.move({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] }); } catch { break; }      // a move that does not fit (a game from another start position) ends the list
    fens.push(chess.fen());
  }
  return fens;
}

export function isPromotion(fen: string, from: string, to: string): boolean {
  const chess = new Chess(fen);
  const p = chess.get(from as never);
  return !!p && p.type === "p" && (to[1] === "8" || to[1] === "1");
}

/** The position after a UCI move, or null when the move is not legal there. */
export function applyUci(fen: string, uci: string): string | null {
  const chess = new Chess(fen);
  try { chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] }); } catch { return null; }
  return chess.fen();
}

/** "g1f3" in a position as "Nf3" (the UCI text when the move is not legal there). */
export function uciToSan(fen: string, uci: string): string {
  const chess = new Chess(fen);
  try { return chess.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] }).san; } catch { return uci; }
}

/** The moves of a PGN text (UCI and SAN), for games that have no analysis yet. */
export function movesFromPgn(pgn: string): { uci: string; san: string }[] {
  const chess = new Chess();
  try { chess.loadPgn(pgn); } catch { return []; }
  return chess.history({ verbose: true }).map((m) => ({ uci: m.from + m.to + (m.promotion ?? ""), san: m.san }));
}

/** A line of UCI moves from a position as SAN (stops at the first illegal move; at most `max` half-moves). */
export function pvToSan(fen: string, ucis: string[], max = 6): string[] {
  const chess = new Chess(fen);
  const out: string[] = [];
  for (const u of ucis.slice(0, max)) {
    try { out.push(chess.move({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] }).san); } catch { break; }
  }
  return out;
}

const PIECE_VALUE: Record<string, number> = { p: 1, n: 3, b: 3, r: 5, q: 9 };
export interface Captured { white: string[]; black: string[]; diff: number }       // pieces each side has taken (by type), and material: positive = white is ahead

/** The pieces taken so far after each half-move of a game given as UCI moves (index 0 = start); `white` lists what White has captured. Promotions count as the extra material they are. */
export function capturedAfter(uci: string[]): Captured[] {
  const chess = new Chess();
  const white: string[] = [], black: string[] = [];
  let diff = 0;
  const out: Captured[] = [{ white: [], black: [], diff: 0 }];
  for (const u of uci) {
    let m;
    try { m = chess.move({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] }); } catch { break; }
    const sign = m.color === "w" ? 1 : -1;
    if (m.captured) { (m.color === "w" ? white : black).push(m.captured); diff += sign * PIECE_VALUE[m.captured]; }
    if (m.promotion) diff += sign * (PIECE_VALUE[m.promotion] - 1);
    out.push({ white: [...white], black: [...black], diff });
  }
  return out;
}
