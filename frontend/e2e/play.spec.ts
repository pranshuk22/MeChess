import { expect, test } from "@playwright/test";
import { drag } from "./helpers";

test("a game against Stockfish: move, reply, take back, resign, review", async ({ page, request }) => {
  const opts = await (await request.get("/api/play/options")).json();
  test.skip(!opts.stockfish.available, "needs Stockfish");
  await page.goto("/play");
  await expect(page.getByRole("heading", { name: "Play" })).toBeVisible();
  await page.getByRole("group", { name: "Level" }).getByRole("button", { name: /Beginner/ }).click();
  await page.getByRole("button", { name: "Start the game" }).click();
  const board = page.locator(".board");
  await expect(board.locator(".piece")).toHaveCount(32);
  await drag(page, board, "e2", "e4");
  const moves = page.getByRole("list", { name: "Moves" });
  await expect(moves.locator("b")).toHaveCount(2, { timeout: 15_000 });                    // e4 and the reply (the empty cell of an unfinished row counts too)
  await expect(moves).toContainText("e4");
  await page.getByRole("button", { name: "Take back" }).click();
  await expect(page.getByText("Your move.")).toBeVisible();
  await drag(page, board, "d2", "d4");
  await expect(moves).toContainText("d4", { timeout: 15_000 });
  await page.getByRole("button", { name: "Resign" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Resign" }).click();
  await expect(page.getByText("You lost by resignation")).toBeVisible();
  await page.getByRole("button", { name: "Review the game" }).click();
  await expect(page).toHaveURL(/\/review\/play%3A/);
  await expect(page.getByText("This game has not been analysed yet")).toBeVisible();
});

test("the setup says when an opponent is not available", async ({ page, request }) => {
  await page.route("**/api/play/options", (r) => r.fulfill({ json: { stockfish: { available: false, levels: [{ id: 1, label: "Beginner" }] }, mechess: { available: false, min: 800, max: 2600 } } }));
  await page.goto("/play");
  await expect(page.getByText("Stockfish was not found")).toBeVisible();
  await expect(page.getByRole("button", { name: "Start the game" })).toBeDisabled();
  await page.getByRole("button", { name: /MeChess/ }).click();
  await expect(page.getByText("The MeChess engine is not built")).toBeVisible();
  void request;
});

test("a timed game: clocks run, the computer takes its time, and its reply is not instant", async ({ page, request }) => {
  const opts = await (await request.get("/api/play/options")).json();
  test.skip(!opts.stockfish.available, "needs Stockfish");
  await page.goto("/play");
  await page.getByRole("group", { name: "Level" }).getByRole("button", { name: /Beginner/ }).click();
  await page.getByRole("group", { name: "Time control" }).getByRole("button", { name: "1 min" }).click();
  await page.getByRole("button", { name: "Start the game" }).click();
  const board = page.locator(".board");
  await expect(board.locator(".piece")).toHaveCount(32);
  await expect(page.getByText("1:00").first()).toBeVisible();                                   // both clocks start at one minute
  const t0 = Date.now();
  await drag(page, board, "e2", "e4");
  const moves = page.getByRole("list", { name: "Moves" });
  await expect(page.getByRole("status").filter({ hasText: "thinking" })).toBeVisible();          // the computer is "thinking"
  await expect(moves).toHaveText(/1\.\s*e4\s*\S+/, { timeout: 15_000 });                          // ... and answers after a person's pause
  expect(Date.now() - t0).toBeGreaterThan(350);
  await expect(page.getByText(/^0:[0-5]\d$/).first()).toBeVisible();                              // a clock is below a minute now
});

test("a game with the pace turned off gets its reply at once", async ({ page, request }) => {
  const opts = await (await request.get("/api/play/options")).json();
  test.skip(!opts.stockfish.available, "needs Stockfish");
  await page.goto("/play");
  await page.getByRole("group", { name: "Level" }).getByRole("button", { name: /Beginner/ }).click();
  await page.getByLabel("The computer takes its time like a person").uncheck();
  await page.getByRole("button", { name: "Start the game" }).click();
  const board = page.locator(".board");
  await expect(board.locator(".piece")).toHaveCount(32);
  const t0 = Date.now();
  await drag(page, board, "e2", "e4");
  await expect(page.getByRole("list", { name: "Moves" }).locator("b")).toHaveCount(2, { timeout: 15_000 });
  expect(Date.now() - t0).toBeLessThan(1500);
});
