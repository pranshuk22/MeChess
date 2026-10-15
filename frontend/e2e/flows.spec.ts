import { expect, test } from "@playwright/test";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PGN = `[Event "Rated Blitz game"]\n[Site "https://lichess.org/E2Etest01"]\n[Date "2026.06.01"]\n[White "e2e_player"]\n[Black "someone_else"]\n[Result "0-1"]\n[WhiteElo "1500"]\n[BlackElo "1520"]\n[TimeControl "180+0"]\n\n1. f3 e5 2. g4 Qh4# 0-1\n`;

test("home shows the numbers and the workspace checklist from the backend", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await expect(page.getByText("Games", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Your workspace")).toBeVisible();
  await expect(page.getByText("Games imported")).toBeVisible();
  await expect(page.getByText("Recent games")).toBeVisible();
  await page.getByRole("button", { name: "Import games" }).first().click();
  await expect(page.getByRole("dialog", { name: "Import games" })).toBeVisible();
  await page.keyboard.press("Escape");
});

test("the library searches and filters on the server", async ({ page }) => {
  await page.goto("/library");
  await page.getByLabel("Search games").fill("Anderssen");
  await expect(page.getByText("2 games match")).toBeVisible();
  await expect(page.locator("a[role=row]")).toHaveCount(2);
  await page.getByLabel("Search games").fill("");
  await page.getByRole("button", { name: "Not analysed" }).click();
  await expect(page.getByText(/10,000 games match/)).toBeVisible();
  await page.getByRole("button", { name: "Analysed", exact: true }).click();
  await expect(page.getByText("12 games match")).toBeVisible();
});

test("importing a PGN runs as a job, shows in Activity and lands in the library, and analysing it adds the review", async ({ page, request }) => {
  const ws = await (await request.get("/api/workspace")).json();
  await page.goto("/library");
  await page.getByRole("button", { name: "Import games" }).first().click();
  await page.getByRole("tab", { name: "PGN file" }).click();
  await page.getByLabel("PGN text").fill(PGN);
  await page.getByPlaceholder("as written in the PGN").fill("e2e_player");
  await page.getByRole("button", { name: "Import", exact: true }).click();
  await expect(page).toHaveURL(/\/activity/);
  await expect(page.getByText("Import PGN games")).toBeVisible();
  await expect(page.getByText(/1 new games/)).toBeVisible({ timeout: 15_000 });
  await page.goto("/library");
  await page.getByLabel("Search games").fill("e2e_player");
  await expect(page.locator("a[role=row]")).toHaveCount(1);
  await page.locator("a[role=row]").click();
  await expect(page.getByText("This game has not been analysed yet")).toBeVisible();
  await expect(page.locator(".board .piece")).toHaveCount(32);
  await page.keyboard.press("End");
  await expect(page.getByText(/was played. Analyse the game/)).toBeVisible();
  if (ws.checks.find((c: { id: string; state: string }) => c.id === "engine")?.state !== "ok") return;     // the rest needs Stockfish
  await request.patch("/api/settings", { data: { nodes: 2000, multipv: 2 } });
  await page.getByRole("button", { name: "Analyse this game" }).click();
  await expect(page.getByRole("tab", { name: "Summary" })).toBeVisible({ timeout: 45_000 });
  await page.getByRole("tab", { name: "Summary" }).click();
  await expect(page.getByRole("table", { name: "Moves by kind" })).toBeVisible();
  await expect(page.getByText("Retry your mistakes")).toBeVisible();
});

test("accounts and engine settings are saved by the backend", async ({ page, request }) => {
  await page.goto("/settings");
  await page.getByPlaceholder("username").first().fill("some_lichess_name");
  await page.getByRole("button", { name: "Save" }).first().click();
  await expect(page.getByText("Saved").first()).toBeVisible();
  expect((await (await request.get("/api/accounts")).json()).lichess).toBe("some_lichess_name");
  await page.getByRole("button", { name: "Quick" }).click();
  await page.getByRole("button", { name: "Save" }).nth(1).click();
  await expect.poll(async () => (await (await request.get("/api/settings")).json()).nodes).toBe(20000);
  await expect(page.getByText("Saved")).toHaveCount(2);                              // the form has taken the saved values back before the next edit
  await page.getByPlaceholder("/usr/local/bin/stockfish").fill("/definitely/not/here");
  await page.getByRole("button", { name: "Save" }).nth(1).click();
  await expect(page.getByText("that path is not an executable file")).toBeVisible();
});

test("a custom piece set can be added from the settings and used on the board", async ({ page }) => {
  const dir = mkdtempSync(join(tmpdir(), "mechess-pieces-"));
  const files = ["K", "Q", "R", "B", "N", "P"].flatMap((p) => ["w", "b"].map((c) => {
    const f = join(dir, `${c}${p}.svg`);
    writeFileSync(f, `<svg xmlns="http://www.w3.org/2000/svg" width="45" height="45"><rect width="45" height="45" fill="${c === "w" ? "#ffd166" : "#118ab2"}"/></svg>`);
    return f;
  }));
  await page.goto("/settings");
  await page.getByLabel("Name of the piece set").fill("Test set");
  await page.locator('input[type=file][multiple]').setInputFiles(files.slice(0, 5));
  await expect(page.getByText(/Choose all 12 files/)).toBeVisible();
  await page.locator('input[type=file][multiple]').setInputFiles(files);
  await expect(page.getByText('Added the piece set "Test set".')).toBeVisible();
  await page.getByRole("button", { name: "Test set", exact: true }).click();
  await page.goto("/review/s03");
  const bg = await page.locator(".board .piece").first().evaluate((e) => (e as HTMLElement).style.backgroundImage);
  expect(bg).toContain("/api/themes/pieces/Test%20set/");
  await page.goto("/settings");
  await page.getByRole("button", { name: "Delete Test set" }).click();
  await expect(page.getByRole("button", { name: "Test set", exact: true })).toHaveCount(0);
});

test("when the server is not reachable the app says so and reconnects by itself", async ({ page }) => {
  await page.route("**/api/health", (r) => r.abort());
  await page.goto("/");
  await expect(page.getByText("The MeChess server is not running")).toBeVisible();
  await page.unroute("**/api/health");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible({ timeout: 15_000 });
});

test("insights show the calendar, phases and move kinds", async ({ page }) => {
  await page.goto("/insights");
  await expect(page.getByRole("heading", { name: "Insights" })).toBeVisible();
  await expect(page.getByText("Accuracy by phase")).toBeVisible();
  await expect(page.getByRole("img", { name: /games in the last 26 weeks/ })).toBeVisible();
  await expect(page.getByRole("img", { name: "Move kinds" })).toBeVisible();
});

test("the opening cache can be built from your games, used, and deleted", async ({ page, request }) => {
  const ws = await (await request.get("/api/workspace")).json();
  test.skip(ws.checks.find((c: { id: string }) => c.id === "engine")?.state !== "ok", "needs Stockfish");
  const g = (id: string, tail: string) => `[Event "Rated Blitz game"]\n[Site "https://lichess.org/${id}"]\n[Date "2026.06.02"]\n[White "cacheme"]\n[Black "x"]\n[Result "1-0"]\n[TimeControl "180+0"]\n\n1. d4 d5 2. c4 e6 ${tail} 1-0\n`;
  await request.post("/api/import/pgn", { data: { text: g("CACHE001", "3. Nc3 Nf6") + "\n" + g("CACHE002", "3. Nf3 Nf6"), player: "cacheme" } });
  await request.patch("/api/settings", { data: { nodes: 2000, multipv: 1, use_cache: true } });
  await request.delete("/api/cache");
  await page.goto("/settings");
  await expect(page.getByText("Opening cache")).toBeVisible();
  await page.getByRole("button", { name: "Build for my openings" }).click();
  await expect(page).toHaveURL(/\/activity/);
  await expect(page.getByText(/opening positions added to the cache/)).toBeVisible({ timeout: 60_000 });
  await page.goto("/settings");
  await expect(page.getByText("Positions by move number")).toBeVisible();
  const n = (await (await request.get("/api/cache")).json()).positions;
  expect(n).toBeGreaterThanOrEqual(4);
  await page.getByRole("button", { name: "Delete all" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Delete" }).click();
  await expect.poll(async () => (await (await request.get("/api/cache")).json()).positions).toBe(0);
});
