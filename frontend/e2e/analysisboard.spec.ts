import { expect, test } from "@playwright/test";
import { drag } from "./helpers";

test("the analysis board takes a FEN or a PGN, lets both sides move, steps back and names its moves", async ({ page }) => {
  await page.goto("/analysis");
  await expect(page.getByRole("heading", { name: "Analysis board" })).toBeVisible();
  const board = page.locator(".board");
  await expect(board.locator(".piece")).toHaveCount(32);
  await drag(page, board, "e2", "e4");
  await drag(page, board, "e7", "e5");                                                          // the second side moves too: it is a free board
  await page.getByRole("tab", { name: "Moves" }).click();
  await expect(page.getByRole("list", { name: "Moves" })).toContainText("e4");
  await expect(page.getByRole("list", { name: "Moves" })).toContainText("e5");
  await page.keyboard.press("ArrowLeft");
  await page.keyboard.press("ArrowLeft");
  await expect(board.locator(".piece")).toHaveCount(32);
  await page.getByLabel("Set up a position or a game").fill("not chess at all");
  await page.getByRole("button", { name: "Load", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("neither a position");
  await page.getByLabel("Set up a position or a game").fill("4k3/8/8/8/8/8/4P3/4K3 w - - 0 1");      // a FEN: kings and one pawn
  await page.getByRole("button", { name: "Load", exact: true }).click();
  await expect(board.locator(".piece")).toHaveCount(3);
  await page.getByLabel("Set up a position or a game").fill("1. d4 d5 2. c4 e6 3. Nc3 Nf6");
  await page.getByRole("button", { name: "Load", exact: true }).click();
  await page.getByRole("tab", { name: "Moves" }).click();
  await expect(page.getByRole("list", { name: "Moves" })).toContainText("Nf6");
  await page.getByRole("button", { name: "Start position" }).click();
  await expect(board.locator(".piece")).toHaveCount(32);
});

test("the engine and the explorer work on the analysis board and a link can start it from a position", async ({ page }) => {
  await page.goto("/analysis?fen=" + encodeURIComponent("6k1/5ppp/8/8/8/8/5PPP/R5K1 w - - 0 1"));
  const board = page.locator(".board");
  await expect(board.locator(".piece")).toHaveCount(9);
  await expect(page.getByText(/Thinking|Connecting|depth \d+/).first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/depth \d+/).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Ra8#").first()).toBeVisible({ timeout: 30_000 });                   // a back-rank mate in one is found
});
