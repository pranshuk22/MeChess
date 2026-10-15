import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  use: { baseURL: "http://127.0.0.1:4173", viewport: { width: 1440, height: 900 } },
  webServer: { command: "npm run build && npx vite preview --port 4173 --strictPort --host 127.0.0.1", url: "http://127.0.0.1:4173", reuseExistingServer: true, timeout: 120_000 },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
