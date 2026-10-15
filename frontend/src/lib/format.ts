import type { GameSummary, Side } from "./types";

type Result = Pick<GameSummary, "result" | "user">;

/** The player's result; for a game without a known side, white's point of view. */
export function outcome(g: Result): "win" | "loss" | "draw" | "unknown" {
  if (g.result === "1/2-1/2") return "draw";
  if (g.result !== "1-0" && g.result !== "0-1") return "unknown";
  const side: Side = g.user ?? "white";
  return (side === "white") === (g.result === "1-0") ? "win" : "loss";
}
export const mySide = (g: Pick<GameSummary, "user">): Side => g.user ?? "white";
export const opponent = (g: Pick<GameSummary, "white" | "black" | "whiteElo" | "blackElo" | "user">) => (mySide(g) === "white" ? { name: g.black, elo: g.blackElo } : { name: g.white, elo: g.whiteElo });
export const me = (g: Pick<GameSummary, "white" | "black" | "whiteElo" | "blackElo" | "user">) => (mySide(g) === "white" ? { name: g.white, elo: g.whiteElo } : { name: g.black, elo: g.blackElo });
export const myAccuracy = (g: Pick<GameSummary, "accuracy" | "user">): number | null => (g.accuracy ? g.accuracy[mySide(g)] : null);
export const yearOf = (date: string | null) => (date ? date.slice(0, 4) : "");

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
/** "2026-06-14" as "14 Jun 2026"; a bare year stays a year */
export function formatDate(date: string | null): string {
  if (!date) return "";
  const m = date.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${Number(m[3])} ${MONTHS[Number(m[2]) - 1]} ${m[1]}` : date;
}
export const plural = (n: number, one: string, many = one + "s") => `${n.toLocaleString()} ${n === 1 ? one : many}`;
