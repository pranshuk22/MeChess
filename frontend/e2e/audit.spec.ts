import { expect, test } from "@playwright/test";
import { firstMistake } from "./helpers";

const GAME = "s03";

async function kbGo(page: import("@playwright/test").Page, board: import("@playwright/test").Locator, target: string, black = false) {
  for (let guard = 0; guard < 20; guard++) {
    const cur = await board.getAttribute("data-kb");
    if (cur === target) return;
    const [cf, cr] = [cur!.charCodeAt(0) - 97, Number(cur![1]) - 1], [tf, tr] = [target.charCodeAt(0) - 97, Number(target[1]) - 1];
    // on screen: files run left to right for white at the bottom; ranks run upwards
    const key = cf !== tf ? ((tf > cf) !== black ? "ArrowRight" : "ArrowLeft") : ((tr > cr) !== black ? "ArrowUp" : "ArrowDown");
    await page.keyboard.press(key);
  }
  throw new Error("could not reach " + target);
}

test("a mistake can be retried with the keyboard alone", async ({ page }) => {
  await page.goto(`/review/${GAME}`);
  await page.getByRole("button", { name: /Retry your mistakes/ }).click();
  await expect(page.getByText(/Find a better move/)).toBeVisible();
  const { m, i } = firstMistake(GAME);
  const black = i % 2 === 1;
  const board = page.locator(".board");
  await board.focus();
  await expect(board).toHaveAttribute("data-kb", /^[a-h][1-8]$/);
  await kbGo(page, board, m.best.slice(0, 2), black);
  await page.keyboard.press("Enter");
  await expect(board.locator(".sq.select")).toHaveCount(1);
  await kbGo(page, board, m.best.slice(2, 4), black);
  await page.keyboard.press("Enter");
  await expect(page.getByText(/^Yes, /)).toBeVisible();
});

test("the browser's own shortcuts are not taken by the review page", async ({ page }) => {
  await page.goto(`/review/${GAME}`);
  await expect(page.locator(".board .piece")).toHaveCount(32);
  const prevented = await page.evaluate(() => new Promise<boolean>((resolve) => {
    window.addEventListener("keydown", (e) => setTimeout(() => resolve(e.defaultPrevented), 0), { once: true });
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "f", metaKey: true, cancelable: true, bubbles: true }));
  }));
  expect(prevented).toBe(false);
});

test("leaving a retry through the move list starts the next retry from the beginning", async ({ page }) => {
  await page.goto(`/review/${GAME}`);
  await page.getByRole("button", { name: /Retry your mistakes/ }).click();
  await page.getByRole("button", { name: "Reveal" }).click();
  await expect(page.getByText(/The better move was/)).toBeVisible();
  await page.getByRole("tab", { name: "Moves" }).click();
  await page.locator("[role=list][aria-label=Moves] button").nth(3).click();
  await page.getByRole("button", { name: /Retry your mistakes/ }).click();
  await expect(page.getByText(/Find a better move/)).toBeVisible();
});

test("settings can be reached on a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 600, height: 800 });
  await page.goto("/");
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Settings" }).click();
  await expect(page).toHaveURL(/\/settings/);
});

test("without the access key the app asks to be opened from its own address; with it the key is taken and the address cleaned", async ({ browser }) => {
  const ctx = await browser.newContext({ storageState: { cookies: [], origins: [] } });
  const page = await ctx.newPage();
  await page.goto("/");
  await expect(page.getByText("Open MeChess from its own address")).toBeVisible();
  await page.goto("/?t=wrong-key");
  await expect(page.getByText("Open MeChess from its own address")).toBeVisible();
  await page.goto("/library?t=e2e-access-key");
  await expect(page.getByRole("heading", { name: "Library" })).toBeVisible();
  expect(page.url()).not.toContain("t=e2e");
  expect((await ctx.cookies()).some((c) => c.name === "mechess_session" && c.httpOnly)).toBe(true);
  await ctx.close();
});

test("an unknown page shows a way back instead of a blank screen", async ({ page }) => {
  await page.goto("/review/does-not-exist");
  await expect(page.getByText("That game is not in your library")).toBeVisible();
});

test("the navigation links carry real classes (a function className was once turned into text by the tooltip) and mark the current page", async ({ page }) => {
  await page.goto("/library");
  const lib = page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Library" });
  expect(await lib.getAttribute("class")).not.toContain("=>");
  await expect(lib).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Home" })).not.toHaveAttribute("aria-current", "page");
  await page.goto("/review/s03");
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Library" })).not.toHaveAttribute("aria-current", "page");
});
