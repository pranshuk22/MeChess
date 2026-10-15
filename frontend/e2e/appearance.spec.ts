import { expect, test } from "@playwright/test";
import { firstMistake } from "./helpers";

test("the website is light by default, even when the system prefers dark", async ({ browser }) => {
  const ctx = await browser.newContext({ colorScheme: "dark" });
  const page = await ctx.newPage();
  await page.goto("/");
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe("light");
  expect(await page.evaluate(() => document.documentElement.dataset.palette)).toBe("glacier");
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  expect(bg).toBe("rgb(243, 245, 247)");
  await ctx.close();
});

test("every palette has a light and a dark mode, and the choice is remembered", async ({ page }) => {
  await page.goto("/settings");
  const seen = new Set<string>();
  for (const palette of ["Glacier", "Paper", "Forest", "Graphite"]) {
    await page.getByRole("button", { name: palette, exact: true }).click();
    for (const mode of ["light", "dark"]) {
      await page.getByRole("button", { name: mode, exact: true }).click();
      const d = await page.evaluate(() => ({ t: document.documentElement.dataset.theme, p: document.documentElement.dataset.palette, bg: getComputedStyle(document.body).backgroundColor, accent: getComputedStyle(document.documentElement).getPropertyValue("--accent") }));
      expect(d.t).toBe(mode);
      seen.add(`${d.p}/${d.t}/${d.bg}`);
    }
  }
  expect(seen.size).toBe(8);                                                        // eight different page backgrounds: nothing falls back to another palette
  await page.getByRole("button", { name: "Paper", exact: true }).click();
  await page.getByRole("button", { name: "dark", exact: true }).click();
  await page.reload();
  expect(await page.evaluate(() => [document.documentElement.dataset.palette, document.documentElement.dataset.theme])).toEqual(["paper", "dark"]);
});

test("the top bar toggles light and dark", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Dark mode" }).click();
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe("dark");
  await page.getByRole("button", { name: "Light mode" }).click();
  expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe("light");
});

test("board and piece themes change the board and are remembered", async ({ page }) => {
  await page.goto("/review/s03");
  const light = () => page.locator(".board").evaluate((b) => getComputedStyle(b).getPropertyValue("--sq-light").trim());
  const first = await light();
  await page.getByRole("button", { name: "Board and pieces" }).click();
  await page.getByRole("button", { name: "Walnut", exact: true }).click();
  expect(await light()).toBe("#ecd9b8");
  expect(await light()).not.toBe(first);
  const img = () => page.locator(".board .piece").first().evaluate((e) => (e as HTMLElement).style.backgroundImage);
  const before = await img();
  await page.getByRole("button", { name: "Papercut", exact: true }).click();
  expect(await img()).not.toBe(before);
  await page.reload();
  expect(await light()).toBe("#ecd9b8");
  await page.getByRole("button", { name: "Board and pieces" }).click();
  await page.getByLabel("Light squares").fill("#ffeecc");
  expect(await light()).toBe("#ffeecc");
});

test("the evaluation bar stands out from the page in every palette and mode", async ({ page }) => {
  await page.goto("/review/s03");
  for (const [palette, mode] of [["glacier", "light"], ["paper", "light"], ["forest", "dark"], ["graphite", "dark"]]) {
    await page.evaluate(([p, m]) => { document.documentElement.dataset.palette = p; document.documentElement.dataset.theme = m; }, [palette, mode]);
    const c = await page.locator(".evalbar").evaluate((el) => { const s = getComputedStyle(el); return { track: s.backgroundColor, outline: s.boxShadow, page: getComputedStyle(document.body).backgroundColor }; });
    expect(c.track).toBe("rgb(43, 49, 57)");
    expect(c.outline).toContain("0px 0px 0px 1px");
    expect(c.track).not.toBe(c.page);
  }
});

test("moves get a class badge on the board and the summary counts them", async ({ page }) => {
  await page.goto("/review/s03");
  await page.getByRole("tab", { name: "Summary" }).click();
  await expect(page.getByRole("table", { name: "Moves by kind" })).toBeVisible();
  const rows = await page.getByRole("table", { name: "Moves by kind" }).locator("tbody tr").count();
  expect(rows).toBe(10);                                                            // brilliant ... blunder, always all ten
  const { i } = firstMistake("s03");                                                // step to the move that was the biggest mistake: it carries a badge
  for (let k = 0; k <= i; k++) await page.keyboard.press("ArrowRight");
  await expect(page.locator(".board .badge-pos")).toBeVisible();
});
