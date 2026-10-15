import { expect, test } from "@playwright/test";
import { firstMistake } from "./helpers";

const GAME = "s03";

test("the board never changes size while stepping through a game", async ({ page }) => {
  await page.goto(`/review/${GAME}`);
  const board = page.locator(".board");
  const first = (await board.boundingBox())!;
  const sizes = new Set<string>();
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press("ArrowRight");
    const b = (await board.boundingBox())!;
    sizes.add(`${Math.round(b.x)},${Math.round(b.y)},${Math.round(b.width)},${Math.round(b.height)}`);
  }
  expect(sizes.size).toBe(1);
  expect(sizes.has(`${Math.round(first.x)},${Math.round(first.y)},${Math.round(first.width)},${Math.round(first.height)}`)).toBe(true);
  for (const tab of ["Moves", "Key moments", "Summary"]) {                          // other tabs have different heights of content
    await page.getByRole("tab", { name: tab }).click();
    const b = (await board.boundingBox())!;
    expect(Math.round(b.width)).toBe(Math.round(first.width));
  }
});

test("the board keeps its size in the retry mode and while moves are tried", async ({ page }) => {
  await page.goto(`/review/${GAME}`);
  const board = page.locator(".board");
  const before = (await board.boundingBox())!;
  await page.getByRole("button", { name: /Retry your mistakes/ }).click();
  await expect(page.getByText(/Find a better move/)).toBeVisible();
  const during = (await board.boundingBox())!;
  expect([Math.round(during.x), Math.round(during.y), Math.round(during.width)]).toEqual([Math.round(before.x), Math.round(before.y), Math.round(before.width)]);
  await page.getByRole("button", { name: "Reveal" }).click();
  const after = (await board.boundingBox())!;
  expect(Math.round(after.width)).toBe(Math.round(before.width));
  expect(firstMistake(GAME)).toBeTruthy();
});

test("the page does not scroll sideways or change width when content changes (stable scrollbar gutter)", async ({ page }) => {
  await page.goto(`/review/${GAME}`);
  const w0 = await page.evaluate(() => document.querySelector("main")!.clientWidth);
  await page.getByRole("tab", { name: "Moves" }).click();
  const w1 = await page.evaluate(() => document.querySelector("main")!.clientWidth);
  expect(w1).toBe(w0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test("on a phone the pages do not scroll sideways and the bottom bar shows the main places", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  for (const path of ["/", "/library", `/review/${GAME}`, "/coach", "/play"]) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), path).toBe(true);
  }
  const bar = page.getByRole("navigation", { name: "Main" });
  for (const name of ["Home", "Library", "Coach", "Play", "Settings"]) await expect(bar.getByRole("link", { name }).first()).toBeVisible();
});
