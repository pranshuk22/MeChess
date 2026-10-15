import type { Locator, Page } from "@playwright/test";
import games from "../src/samples/sample-games.json" with { type: "json" };

export type Sample = { id: string; user: "white" | "black"; moves: { san: string; uci: string; cls: string; loss: number; best: string }[] };
export const sample = (id: string) => (games as unknown as Sample[]).find((g) => g.id === id)!;

/** the user's biggest mistake of a sample game, in the order the retry list shows them (largest loss first) */
export function firstMistake(id: string) {
  const g = sample(id);
  const list = g.moves.map((m, i) => ({ m, i })).filter(({ m, i }) => (i % 2 === 0) === (g.user === "white") && m.loss >= 0.1 && ["mistake", "blunder", "miss"].includes(m.cls)).sort((a, b) => b.m.loss - a.m.loss);
  return list[0];
}

/** screen centre of a square on the board (white at the bottom unless `black`) */
export async function squareCentre(board: Locator, sq: string, black = false) {
  const box = (await board.boundingBox())!;
  const f = sq.charCodeAt(0) - 97, r = Number(sq[1]) - 1;
  const col = black ? 7 - f : f, row = black ? r : 7 - r;
  return { x: box.x + ((col + 0.5) * box.width) / 8, y: box.y + ((row + 0.5) * box.height) / 8 };
}

export async function drag(page: Page, board: Locator, from: string, to: string, black = false, steps = 12) {
  const a = await squareCentre(board, from, black), b = await squareCentre(board, to, black);
  await page.mouse.move(a.x, a.y);
  await page.mouse.down();
  await page.mouse.move(b.x, b.y, { steps });
  await page.mouse.up();
}
export async function click(page: Page, board: Locator, sq: string, black = false) {
  const a = await squareCentre(board, sq, black);
  await page.mouse.click(a.x, a.y);
}
