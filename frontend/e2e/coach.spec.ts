import { expect, test } from "@playwright/test";

test("practice from your own mistakes: add, hint, reveal, finish, and the schedule moves", async ({ page, request }) => {
  await page.goto("/coach");
  await expect(page.getByRole("heading", { name: "Coach" })).toBeVisible();
  const empty = page.getByText("No practice positions yet");
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
