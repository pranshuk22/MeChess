import { defineConfig } from "@playwright/test";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

// The end-to-end tests run against the real backend (with its own empty data folder, seeded with the sample games) serving the built frontend.
const data = mkdtempSync(join(tmpdir(), "mechess-e2e-"));
const token = "e2e-access-key";
const python = process.env.MECHESS_PYTHON ?? resolve("../.venv/bin/python");

export default defineConfig({
  testDir: "./e2e",
  timeout: 40_000,
  fullyParallel: false,
  workers: 1,
  use: { baseURL: "http://127.0.0.1:4173", viewport: { width: 1440, height: 900 },
    storageState: { cookies: [{ name: "mechess_session", value: token, domain: "127.0.0.1", path: "/", expires: -1, httpOnly: true, secure: false, sameSite: "Strict" }], origins: [] } },
  webServer: {
    command: `npm run build && cd .. && MECHESS_TOKEN=${token} PYTHONPATH=. ${python} -m chessme app --data-dir ${data}/data --research-dir ${data}/research --legacy-coach-dir ${data}/coach --bot-dir ${data}/bot --port 4173 --no-browser --seed-samples frontend/src/samples/sample-games.json --seed-stress 10000`,
    url: "http://127.0.0.1:4173/api/health", reuseExistingServer: false, timeout: 180_000,
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
