import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath } from "node:url";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8765" } },
  build: { target: "es2022", sourcemap: false, chunkSizeWarningLimit: 250 },
  test: { include: ["src/**/*.test.{ts,tsx}"], environment: "jsdom", globals: true, setupFiles: ["./src/test-setup.ts"], css: false },
});
