import type { GameRecord } from "./types";

export function outcome(g: GameRecord): "win" | "loss" | "draw" {
  if (g.result === "1/2-1/2") return "draw";
  const whiteWon = g.result === "1-0";
  return (g.user === "white") === whiteWon ? "win" : "loss";
}
export const opponent = (g: GameRecord) => (g.user === "white" ? { name: g.black, elo: g.blackElo } : { name: g.white, elo: g.whiteElo });
export const mine = (g: GameRecord) => (g.user === "white" ? { name: g.white, elo: g.whiteElo } : { name: g.black, elo: g.blackElo });
export const myAccuracy = (g: GameRecord) => g.accuracy[g.user];
