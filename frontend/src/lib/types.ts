export type MoveClass = "book" | "brilliant" | "great" | "best" | "excellent" | "good" | "inaccuracy" | "mistake" | "miss" | "blunder";
export interface AnalysedMove {
  san: string; uci: string; cls: MoveClass; loss: number; best: string;
  winBefore: number; winAfter: number;
  cp: number;                                   // evaluation after the move, white's point of view, centipawns
  acc?: number; phase?: string;                 // the move's accuracy (0..100) and the phase of the game
}
import type * as S from "@/api/schema";

export type Side = "white" | "black";
export type GameSummary = Omit<S.GameSummary, "user"> & { user: Side | null };
export type GameDetail = Omit<S.GameDetail, "moves" | "user"> & { user: Side | null; moves: AnalysedMove[] };
export type { S };
export const BAD: MoveClass[] = ["inaccuracy", "mistake", "miss", "blunder"];
export const SYMBOL: Partial<Record<MoveClass, string>> = { brilliant: "!!", great: "!", inaccuracy: "?!", mistake: "?", miss: "?", blunder: "??" };
export const CLASS_LABEL: Record<MoveClass, string> = {
  book: "Book", brilliant: "Brilliant", great: "Great", best: "Best", excellent: "Excellent", good: "Good",
  inaccuracy: "Inaccuracy", mistake: "Mistake", miss: "Miss", blunder: "Blunder",
};
export const CLASS_VAR: Record<MoveClass, string> = {
  brilliant: "var(--q-brilliant)", great: "var(--q-great)", best: "var(--q-best)", good: "var(--q-good)", excellent: "var(--q-excellent)", book: "var(--q-book)",
  inaccuracy: "var(--q-inaccuracy)", mistake: "var(--q-mistake)", miss: "var(--q-miss)", blunder: "var(--q-blunder)",
};
/** the order the classes are listed in a game summary (best news first) */
export const CLASS_ORDER: MoveClass[] = ["brilliant", "great", "best", "excellent", "good", "book", "inaccuracy", "mistake", "miss", "blunder"];
/** evaluation as a human reads it: +1.3, -0.4 ; a very large value is shown as a mate-like bound */
export function formatEval(cp: number): string {
  if (Math.abs(cp) >= 1000) return cp > 0 ? "+M" : "-M";
  const v = (cp / 100).toFixed(1);
  return (cp > 0 ? "+" : "") + v;
}
export const winPercent = (cp: number) => 50 + 50 * (2 / (1 + Math.exp(-0.00368208 * cp)) - 1);
