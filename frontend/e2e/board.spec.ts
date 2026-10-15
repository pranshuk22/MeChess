import { expect, test } from "@playwright/test";
import { click, drag, firstMistake, sample } from "./helpers";

const GAME = "s03";                                   // a sample game in which the user is white and makes mistakes

test("the review board shows the position and steps with the keyboard", async ({ page }) => {
  await page.goto(`/review/${GAME}`);
  const board = page.locator(".board");
  await expect(board.locator(".piece")).toHaveCount(32);
  await page.keyboard.press("ArrowRight");
  await page.keyboard.press("ArrowRight");
  await expect(page.getByRole("button", { name: "Previous (←)" })).toBeEnabled();
  await page.keyboard.press("Home");
  await expect(page.getByRole("button", { name: "Previous (←)" })).toBeDisabled();
});

test.describe("retry your mistakes", () => {
  const { m, i } = firstMistake(GAME);
  const from = m.best.slice(0, 2), to = m.best.slice(2, 4);
  const blackToMove = i % 2 === 1;

  test.beforeEach(async ({ page }) => {
    await page.goto(`/review/${GAME}`);
    await page.getByRole("button", { name: /Retry your mistakes/ }).click();
    await expect(page.getByText(/Find a better move/)).toBeVisible();
  });

  test("dragging the engine's move is accepted", async ({ page }) => {
    await drag(page, page.locator(".board"), from, to, blackToMove);
    await expect(page.getByText(/^Yes, /)).toBeVisible();
  });

  test("click, then click works too", async ({ page }) => {
    const board = page.locator(".board");
    await click(page, board, from, blackToMove);
    await expect(board.locator(".sq.select")).toHaveCount(1);
    await expect(board.locator(".sq.dot, .sq.ring").first()).toBeVisible();
    await click(page, board, to, blackToMove);
    await expect(page.getByText(/^Yes, /)).toBeVisible();
  });

  test("another move is not accepted, and try again puts the position back", async ({ page }) => {
    const board = page.locator(".board");
    const before = await board.locator(".piece").evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.sq).sort().join());
    // the move the user actually played is a legal move that is not the engine's choice
    await drag(page, board, sample(GAME).moves[i].uci.slice(0, 2), sample(GAME).moves[i].uci.slice(2, 4), blackToMove);
    await expect(page.getByText(/Not the engine's choice/)).toBeVisible();
    await page.getByRole("button", { name: "Try again" }).click();
    await expect(page.getByText(/Find a better move/)).toBeVisible();
    const after = await board.locator(".piece").evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.sq).sort().join());
    expect(after).toBe(before);
  });

  test("an illegal drop snaps back", async ({ page }) => {
    const board = page.locator(".board");
    const before = await board.locator(".piece").evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.sq).sort().join());
    await drag(page, board, from, from[0] + (from[1] === "1" ? "5" : "4"), blackToMove);   // a square that is almost surely not a legal target for that piece
    const after = await board.locator(".piece").evaluateAll((els) => els.map((e) => (e as HTMLElement).dataset.sq).sort().join());
    expect(after).toBe(before);                                       // every piece is back where it was
    await expect(page.getByText(/Find a better move/)).toBeVisible(); // and the exercise is still open
  });
});

test("right-drag draws an arrow, right-click marks a square, a left click clears both", async ({ page }) => {
  await page.goto(`/review/${GAME}`);
  const board = page.locator(".board");
  await page.getByRole("button", { name: "Show engine's best move (B)" }).click();       // engine arrows off
  const box = (await board.boundingBox())!;
  const at = (c: number, r: number) => ({ x: box.x + ((c + 0.5) * box.width) / 8, y: box.y + ((r + 0.5) * box.height) / 8 });
  const a = at(0, 4), b = at(3, 4);
  await page.mouse.move(a.x, a.y); await page.mouse.down({ button: "right" }); await page.mouse.move(b.x, b.y, { steps: 5 }); await page.mouse.up({ button: "right" });
  await expect(board.locator("svg polygon")).toHaveCount(1);
  const c = at(5, 2);
  await page.mouse.click(c.x, c.y, { button: "right" });
  await expect(board.locator(".sq.mark")).toHaveCount(1);
  await page.mouse.click(at(7, 0).x, at(7, 0).y);
  await expect(board.locator("svg polygon")).toHaveCount(0);
  await expect(board.locator(".sq.mark")).toHaveCount(0);
});

test("the app makes no request to any other host", async ({ page }) => {
  const hosts = new Set<string>();
  page.on("request", (r) => { const u = new URL(r.url()); if (u.protocol.startsWith("http")) hosts.add(u.host); });
  for (const path of ["/", "/library", `/review/${GAME}`, "/settings", "/activity"]) { await page.goto(path); await page.waitForLoadState("domcontentloaded"); await page.waitForTimeout(700); }
  expect([...hosts]).toEqual(["127.0.0.1:4173"]);
});

test("dragging does not block the main thread", async ({ page }) => {
  await page.goto(`/review/${GAME}`);
  await page.getByRole("button", { name: /Retry your mistakes/ }).click();
  await page.evaluate(() => { (window as any).__long = []; new PerformanceObserver((l) => (window as any).__long.push(...l.getEntries().map((e) => e.duration))).observe({ entryTypes: ["longtask"] }); });
  const { m, i } = firstMistake(GAME);
  const board = page.locator(".board");
  await drag(page, board, m.best.slice(0, 2), m.best.slice(2, 4), i % 2 === 1, 120);
  const long: number[] = await page.evaluate(() => (window as any).__long);
  expect(Math.max(0, ...long)).toBeLessThan(50);
});

test("a library of 10,000 games renders only the visible rows, loads more while scrolling and stays fast", async ({ page }) => {
  await page.goto("/library");
  await expect(page.getByText(/10,0\d\d games/)).toBeVisible();
  const rows = await page.locator("a[role=row]").count();
  expect(rows).toBeLessThan(60);
  const t = await page.evaluate(async () => {
    const el = document.querySelector("[role=rowgroup]") as HTMLElement;
    const t0 = performance.now();
    for (let k = 0; k < 60; k++) { el.scrollTop += 3000; await new Promise((r) => requestAnimationFrame(r)); }
    return performance.now() - t0;
  });
  expect(t).toBeLessThan(2500);                       // 60 frames of fast scrolling, with more pages being fetched meanwhile
  expect(await page.locator("a[role=row]").count()).toBeLessThan(60);
});
