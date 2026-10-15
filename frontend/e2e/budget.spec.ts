import { expect, test } from "@playwright/test";
import { gzipSync } from "node:zlib";

// The performance budget (plan 20 §6): what a first visit downloads, measured as the browser requested it.
test("a first visit stays within the size budget and loads only what the page needs", async ({ browser }) => {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const sizes: Record<string, number> = { js: 0, css: 0, font: 0, other: 0 };
  const fonts: string[] = [];
  page.on("response", async (r) => {
    const url = new URL(r.url());
    if (url.pathname.startsWith("/api")) return;
    try {
      const body = await r.body();
      const kind = /\.js$/.test(url.pathname) ? "js" : /\.css$/.test(url.pathname) ? "css" : /\.woff2?$/.test(url.pathname) ? "font" : "other";
      sizes[kind] += kind === "font" ? body.length : gzipSync(body).length;                  // text is compared gzipped (what a normal server sends); fonts are already compressed
      if (kind === "font") fonts.push(url.pathname);
    } catch { /* a response without a body */ }
  });
  await ctx.addCookies([{ name: "mechess_session", value: "e2e-access-key", url: "http://127.0.0.1:4173" }]);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await page.waitForTimeout(800);
  expect(sizes.js, `initial JavaScript ${sizes.js} bytes gzipped`).toBeLessThan(200 * 1024);
  expect(sizes.css, `CSS ${sizes.css} bytes gzipped`).toBeLessThan(30 * 1024);
  expect(fonts.length, fonts.join(", ")).toBeLessThanOrEqual(3);                              // only the Latin subsets are fetched, not every script of the font
  expect(sizes.font).toBeLessThan(260 * 1024);
  await ctx.close();
});

test("heavy pages are loaded only when visited", async ({ page }) => {
  const scripts = new Set<string>();
  page.on("request", (r) => { if (r.resourceType() === "script") scripts.add(new URL(r.url()).pathname); });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
  await page.waitForTimeout(400);
  const home = scripts.size;
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Library" }).click();
  await expect(page.getByRole("heading", { name: "Library" })).toBeVisible();
  expect(scripts.size).toBeGreaterThan(home);                                                  // the library's code arrived on demand
});
