import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const PAGES = ["/", "/library", "/review/s03", "/coach", "/play", "/insights", "/activity", "/settings", "/explorer", "/books", "/bot", "/prepare"];

for (const [palette, mode] of [["slate", "light"], ["slate", "dark"], ["catppuccin", "light"], ["catppuccin", "dark"], ["macchiato", "dark"], ["glacier", "light"], ["paper", "light"], ["paper", "dark"], ["forest", "dark"], ["graphite", "dark"]]) {
  test(`no serious accessibility problems in ${palette} ${mode}`, async ({ page }) => {
    await page.addInitScript(([p, m]) => { localStorage.setItem("mechess.palette", p); localStorage.setItem("mechess.mode", m); }, [palette, mode]);
    const found: string[] = [];
    for (const path of PAGES) {
      await page.goto(path);
      await page.waitForLoadState("domcontentloaded");
      await page.waitForTimeout(600);
      const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
      for (const v of r.violations.filter((x) => x.impact === "serious" || x.impact === "critical")) found.push(`${path} [${v.id}] ${v.help}: ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
    }
    expect(found, found.join("\n")).toEqual([]);
  });
}
