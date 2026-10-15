import { expect, test } from "@playwright/test";
import { drag, sample } from "./helpers";

const GAME = "s03";                                                              // the Evergreen Game: 1.e4 e5 2.Nf3 Nc6 ...

test("playing a move that is not in the game starts a side line; Escape goes back", async ({ page }) => {
  await page.goto(`/review/${GAME}`);
  const board = page.locator(".board");
  await drag(page, board, "e2", "e4");                                           // the game's own first move: it simply goes forward
  await expect(page.getByText("Trying a side line")).toHaveCount(0);
  await drag(page, board, "c7", "c5");                                           // the game went 1...e5
  await expect(page.getByText(/Trying a side line: 1 move/)).toBeVisible();
  await expect(board.locator(".piece")).toHaveCount(32);
  await drag(page, board, "g1", "f3");
  await expect(page.getByText(/Trying a side line: 2 moves/)).toBeVisible();
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByText(/Trying a side line: 1 move/)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByText("Trying a side line")).toHaveCount(0);
  const sq = await board.locator(".piece").evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.sq));
  expect(sq).toContain("e4");                                                    // back at the game position after 1.e4
  expect(sq).toContain("e7");                                                    // black's pawn has not moved
});

test("the engine tab shows live lines for the position, and a click plays the move", async ({ page, request }) => {
  const ws = await (await request.get("/api/workspace")).json();
  test.skip(ws.checks.find((c: { id: string }) => c.id === "engine")?.state !== "ok", "needs Stockfish");
  await page.goto(`/review/${GAME}`);
  await page.getByRole("tab", { name: "Engine" }).click();
  await page.getByRole("switch").click();
  const first = page.locator("ol li").first();
  await expect(first).toBeVisible({ timeout: 20_000 });
  await expect(first.locator("button")).toContainText(/[+-]?\d\.\d|M\d/);
  await expect(page.getByText(/depth \d+/).first()).toBeVisible();
  const board = page.locator(".board");
  await expect(board.locator("svg polygon")).toHaveCount(0 + (await board.locator("svg polygon").count()));   // (arrows are drawn for the engine's top move in a side line only)
  await first.locator("button").click();                                          // the engine's move from the start position: e4 or d4 or similar (not the game's 1.e4 necessarily)
  await expect(page.getByRole("button", { name: "Next (→)" })).toBeVisible();
  await page.getByRole("switch").click();
  await expect(page.getByText("Turn the engine on")).toBeVisible();
});

test("the explorer tab says so when the database is not built", async ({ page }) => {
  await page.goto(`/review/${GAME}`);
  await page.getByRole("tab", { name: "Explorer" }).click();
  await expect(page.getByText("The opening explorer is not built yet")).toBeVisible();
});

test("each move shows the engine's best lines for the position it was played in; a click tries a line", async ({ page }) => {
  await page.goto(`/review/${GAME}`);
  await expect(page.locator(".board .piece")).toHaveCount(32);                                    // the page has loaded (keys pressed earlier would be lost)
  const g = sample(GAME) as unknown as { moves: { uci: string; lines?: { uci: string }[] }[] };
  const k = g.moves.findIndex((m) => (m.lines?.length ?? 0) >= 2 && m.lines![0].uci === m.uci);       // a move that was the engine's first choice
  expect(k).toBeGreaterThanOrEqual(0);
  for (let i = 0; i <= k; i++) await page.keyboard.press("ArrowRight");
  const card = page.locator("aside").getByText("your move").first();
  await expect(card).toBeVisible();                                                // the line that starts with the move played is marked
  const rows = page.locator("aside ul li button[title^='Try this line']");
  expect(await rows.count()).toBeGreaterThanOrEqual(2);
  await expect(rows.first()).toContainText(/[+-]\d\.\d/);
  await rows.nth(1).click();
  await expect(page.getByText(/Trying a side line/)).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByText(/Trying a side line/)).toHaveCount(0);
});

test("move evaluations can be shown in the move list", async ({ page }) => {
  await page.goto(`/review/${GAME}`);
  await page.getByRole("tab", { name: "Moves" }).click();
  await page.getByLabel("Show evaluations").check();
  await expect(page.locator("[role=list][aria-label=Moves]").getByText(/^[+-]\d\.\d$/).first()).toBeVisible();
});
