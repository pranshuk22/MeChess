export type MoveClass = "book" | "brilliant" | "great" | "best" | "excellent" | "good" | "inaccuracy" | "mistake" | "miss" | "blunder";
export interface AnalysedMove {
  san: string; uci: string; cls: MoveClass; loss: number; best: string;
  winBefore: number; winAfter: number;
  cp: number;                                   // evaluation after the move, white's point of view, centipawns
}
export interface GameRecord {
  id: string; white: string; black: string; whiteElo: number; blackElo: number; result: string; year: number;
  speed: string; opening: string; user: "white" | "black"; title?: string;
  accuracy: { white: number; black: number };
  moves: AnalysedMove[];
}
export const BAD: MoveClass[] = ["inaccuracy", "mistake", "miss", "blunder"];
export const SYMBOL: Partial<Record<MoveClass, string>> = { brilliant: "!!", great: "!", inaccuracy: "?!", mistake: "?", miss: "?", blunder: "??" };
export const CLASS_LABEL: Record<MoveClass, string> = {
  book: "Book move", brilliant: "Brilliant", great: "Great move", best: "Best move", excellent: "Excellent", good: "Good",
  inaccuracy: "Inaccuracy", mistake: "Mistake", miss: "Missed chance", blunder: "Blunder",
};
export const CLASS_VAR: Partial<Record<MoveClass, string>> = {
  brilliant: "var(--q-brilliant)", great: "var(--q-great)", best: "var(--q-best)", good: "var(--q-good)", excellent: "var(--q-good)", book: "var(--q-book)",
  inaccuracy: "var(--q-inaccuracy)", mistake: "var(--q-mistake)", miss: "var(--q-mistake)", blunder: "var(--q-blunder)",
};
/** evaluation as a human reads it: +1.3, -0.4 ; a very large value is shown as a mate-like bound */
export function formatEval(cp: number): string {
  if (Math.abs(cp) >= 1000) return cp > 0 ? "+M" : "-M";
  const v = (cp / 100).toFixed(1);
  return (cp > 0 ? "+" : "") + v;
}
export const winPercent = (cp: number) => 50 + 50 * (2 / (1 + Math.exp(-0.00368208 * cp)) - 1);
