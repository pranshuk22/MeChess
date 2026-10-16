import { expect, test } from "@playwright/test";

test("practice from your own mistakes: add, hint, reveal, finish, and the schedule moves", async ({ page, request }) => {
  await page.goto("/coach");
  await expect(page.getByRole("heading", { name: "Coach" })).toBeVisible();
  const empty = page.getByText("Where to start");
  await expect(empty.or(page.getByText(/positions? due of \d+/))).toBeVisible({ timeout: 10_000 });      // (the page has loaded one way or the other)
  if (await empty.isVisible()) await page.getByRole("button", { name: "Add from my games" }).first().click();
  await expect(page.getByText(/positions? due of \d+/)).toBeVisible({ timeout: 10_000 });
  const before = await (await request.get("/api/coach/drills")).json();
  expect(before.total).toBeGreaterThan(3);
  await page.getByRole("button", { name: "Start practice" }).click();
  await expect(page.getByText("Position 1 of 5")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Find a better move" })).toBeVisible();
  await page.getByRole("button", { name: "Hint" }).click();
  await expect(page.getByText(/./, { hasText: /attack|capture|check|Nothing is hanging|win material/ }).first()).toBeVisible();
  for (let k = 1; k <= 5; k++) {
    await page.getByRole("button", { name: "Show me" }).click();
    await expect(page.getByText(/The move was /)).toBeVisible();
    await page.getByRole("button", { name: k < 5 ? /Next/ : "Finish" }).click();
  }
  await expect(page.getByText(/Done: you found 0 of 5/)).toBeVisible();
  const after = await (await request.get("/api/coach/drills")).json();
  expect(after.boxes[0]).toBeGreaterThanOrEqual(5);                                               // missed ones are back in the first box
});

test("the weakness profile reads from the analysed games", async ({ page }) => {
  await page.goto("/coach");
  await page.getByRole("tab", { name: "Weaknesses" }).click();
  await expect(page.getByText("What stands out")).toBeVisible();
  await expect(page.getByText("By phase and situation")).toBeVisible();
  await expect(page.getByText("Kinds of mistake")).toBeVisible();
});

test("the home page shows how many practice positions are due", async ({ page, request }) => {
  await request.post("/api/coach/drills/refresh");
  await page.goto("/");
  await expect(page.getByText(/positions? (is|are) due/)).toBeVisible();
});

test("opening practice and endgames say what data they need when it is missing", async ({ page }) => {
  await page.goto("/coach");
  await page.getByRole("tab", { name: "Openings" }).click();
  await expect(page.getByText("Opening practice needs the opening explorer")).toBeVisible();
  await page.getByRole("tab", { name: "Endgames" }).click();
  await expect(page.getByText("Endgame practice needs endgame tables")).toBeVisible();
});

test("a steered game: choose a focus, play, finish, see the report, review the saved game", async ({ page, request }) => {
  const ws = await (await request.get("/api/workspace")).json();
  test.skip(ws.checks.find((c: { id: string }) => c.id === "engine")?.state !== "ok", "needs Stockfish");
  const { drag } = await import("./helpers");
  await page.goto("/coach");
  await page.getByRole("tab", { name: "Steered game" }).click();
  const start = page.getByRole("button", { name: "Start the game" });
  await expect(start).toBeDisabled();                                                              // nothing chosen yet
  await page.getByRole("group", { name: "Focus" }).getByLabel(/Notice threats/).check();
  await start.click();
  const board = page.locator(".board");
  await expect(board.locator(".piece")).toHaveCount(32);
  await drag(page, board, "e2", "e4");
  await expect(board.locator('.piece[data-sq="e4"]')).toHaveCount(1);
  await page.getByRole("button", { name: /Finish and see how it went/ }).click();
  await expect(page.getByText("How it went")).toBeVisible({ timeout: 60_000 });
  await page.getByRole("link", { name: "Review the game" }).click();
  await expect(page).toHaveURL(/\/review\/steer%3A/);
  await expect(page.getByRole("tab", { name: "Summary" })).toBeVisible();
});

test("a move tried in practice is graded and explained, whatever it is", async ({ page, request }) => {
  await request.post("/api/coach/drills/refresh");
  const first = (await (await request.get("/api/coach/drills/next?limit=1")).json()).items[0];
  const { Chess } = await import("chess.js");
  const chess = new Chess(first.fen);
  const move = chess.moves({ verbose: true })[0];                                                 // any legal move: the engine says how good it is
  const fb = await (await request.post("/api/coach/feedback", { data: { fen: first.fen, uci: move.from + move.to + (move.promotion ?? "") } })).json();
  expect(["best", "great", "good", "inaccuracy", "mistake", "blunder"]).toContain(fb.grade);
  expect(fb.title.length).toBeGreaterThan(3);
  expect(fb.reasons.length).toBeGreaterThan(0);
  if (!fb.solved) expect(fb.bestSan).toBeUndefined();                                             // a try that is not good does not give the answer away
  await page.goto("/coach");
  await page.getByRole("button", { name: "Start practice" }).click();
  await expect(page.getByRole("heading", { name: "Find a better move" })).toBeVisible();
});
