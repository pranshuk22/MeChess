import { expect, test } from "@playwright/test";

/** PGN text of one game: `sans` with the players' names. */
function game(i: number, white: string, black: string, sans: string, result: string, opening: string) {
  const moves = sans.split(" ").map((s, k) => (k % 2 === 0 ? `${k / 2 + 1}. ${s}` : s)).join(" ");
  return `[Event "Rated Blitz game"]\n[Site "https://lichess.org/Prep${String(i).padStart(4, "0")}x"]\n[White "${white}"]\n[Black "${black}"]\n[Result "${result}"]\n[UTCDate "2026.09.${String(1 + (i % 27)).padStart(2, "0")}"]\n[UTCTime "10:00:00"]\n[WhiteElo "${white === "TestRival" ? 1800 : 1750}"]\n[BlackElo "${black === "TestRival" ? 1800 : 1750}"]\n[TimeControl "180+0"]\n[Opening "${opening}"]\n\n${moves} ${result}\n`;
}
const PGN = [
  ...Array.from({ length: 6 }, (_, i) => game(i, "someone", "TestRival", "e4 e5 Qh5 Nc6 Bc4 Nf6 Qxf7#", "1-0", "Bishop's Opening")),
  ...Array.from({ length: 4 }, (_, i) => game(10 + i, "TestRival", "other", "e4 e5 Nf3 Nc6 Bb5 a6", "1/2-1/2", "Ruy Lopez")),
].join("\n\n");

test("prepare against an opponent: start from a PGN, read the plan, openings, traps, save the plan and delete the preparation", async ({ page, request }) => {
  await page.goto("/prepare");
  await expect(page.getByRole("heading", { name: "Prepare against an opponent" })).toBeVisible();
  await page.getByLabel("Opponent's user name").fill("TestRival");
  await page.getByRole("radio", { name: /Quick/ }).click();
  await page.getByRole("button", { name: "Or paste a PGN of their games" }).click();
  await page.getByLabel("PGN of the opponent's games").fill(PGN);
  await page.getByRole("button", { name: "Prepare", exact: true }).click();
  await expect(page.getByRole("heading", { name: /Preparing against/ })).toBeVisible();
  await expect(page.getByText("The short version")).toBeVisible({ timeout: 180_000 });

  await expect(page.getByRole("tab", { name: "Your plan" })).toBeVisible();
  await expect(page.getByRole("tree").first()).toBeVisible();
  const first = page.getByRole("treeitem").first();
  await first.getByRole("button", { name: /e4/ }).first().click();
  await expect(page.getByText(/expected score/i).first()).toBeVisible();
  await page.getByRole("button", { name: "You play Black" }).click();
  await expect(page.getByRole("tree").first()).toBeVisible();

  await page.getByRole("tab", { name: "Their openings" }).click();
  await expect(page.getByText("Bishop's Opening", { exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Traps" }).click();
  await expect(page.getByText(/They play Nf6/).first()).toBeVisible();
  await page.getByRole("tab", { name: "Middlegame and endgame" }).click();
  await expect(page.getByText("No whole games analysed")).toBeVisible();                       // Quick: the report says what it did not do
  await page.getByRole("tab", { name: "Their games" }).click();
  await expect(page.getByRole("link", { name: "Open the game on the site" }).first()).toHaveAttribute("href", /lichess\.org\/Prep/);

  await page.getByRole("tab", { name: "Your plan" }).click();
  await page.getByRole("button", { name: "You play White" }).click();
  await page.getByRole("button", { name: /Save as a repertoire/ }).click();
  await expect(page.getByText("Saved as a repertoire")).toBeVisible();
  const reps = await (await request.get("/api/coach/repertoires")).json();
  expect(reps.some((r: { name: string }) => r.name.includes("TestRival"))).toBe(true);

  await page.getByRole("button", { name: "Delete" }).first().click();
  await page.getByRole("button", { name: "Delete", exact: true }).last().click();
  await expect(page.getByRole("heading", { name: "Prepare against an opponent" })).toBeVisible();
  await expect(page.getByText("Nothing prepared yet")).toBeVisible();
});

test("a name that does not exist is explained, not a blank page", async ({ page }) => {
  await page.goto("/prepare");
  await page.getByLabel("Opponent's user name").fill("x");
  await expect(page.getByRole("button", { name: "Prepare", exact: true })).toBeDisabled();                  // one letter is not a user name
});

test("the finished report passes the accessibility scan on every tab", async ({ page }) => {
  test.setTimeout(240_000);
  const AxeBuilder = (await import("@axe-core/playwright")).default;
  await page.goto("/prepare");
  await page.getByLabel("Opponent's user name").fill("TestRival");
  await page.getByRole("radio", { name: /Quick/ }).click();
  await page.getByRole("button", { name: "Or paste a PGN of their games" }).click();
  await page.getByLabel("PGN of the opponent's games").fill(PGN);
  await page.getByRole("button", { name: "Prepare", exact: true }).click();
  await expect(page.getByText("The short version")).toBeVisible({ timeout: 180_000 });
  for (const tab of ["Your plan", "Their openings", "Traps", "Middlegame and endgame", "Their games"]) {
    await page.getByRole("tab", { name: tab }).click();
    const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
    expect(r.violations.map((v) => `${tab}: ${v.id} ${v.nodes[0]?.html?.slice(0, 100)}`)).toEqual([]);
  }
});

const LONG = "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O h3 Nb8 d4 Nbd7 c4 c6 Nbd2 Bb7 Bc2 Re8 Nf1 Bf8 Ng3 g6 a4 Bg7 Bg5 h6 Bd2 Nh7";      // 36 half-moves: long enough to be analysed as a whole game

test("a standard preparation analyses whole games and fills the middlegame and endgame tab", async ({ page }) => {
  test.setTimeout(300_000);
  const AxeBuilder = (await import("@axe-core/playwright")).default;
  const text = Array.from({ length: 4 }, (_, i) => game(20 + i, "TestRival", "other", LONG, ["1-0", "0-1", "1/2-1/2", "1-0"][i], "Ruy Lopez: Closed")).join("\n\n");
  await page.goto("/prepare");
  await page.getByLabel("Opponent's user name").fill("TestRival");
  await page.getByRole("radio", { name: /Standard/ }).click();
  await page.getByRole("button", { name: "Or paste a PGN of their games" }).click();
  await page.getByLabel("PGN of the opponent's games").fill(text);
  await page.getByRole("button", { name: "Prepare", exact: true }).click();
  await expect(page.getByText("The short version")).toBeVisible({ timeout: 280_000 });
  await page.getByRole("tab", { name: "Middlegame and endgame" }).click();
  await expect(page.getByText("Where they go wrong")).toBeVisible();
  await expect(page.getByText("By phase")).toBeVisible();
  await expect(page.getByText("The clock")).toBeVisible();
  const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
  expect(r.violations.map((v) => `${v.id} ${v.nodes[0]?.html?.slice(0, 100)}`)).toEqual([]);
});
