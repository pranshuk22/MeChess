// One command for development: the Python backend (API, database, jobs) and the Vite dev server (hot reload) together, with prefixed output.
//   npm run dev:all          (set MECHESS_PYTHON to use another Python than ../.venv/bin/python or python3)
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "../..");
const venv = resolve(root, ".venv/bin/python");
const python = process.env.MECHESS_PYTHON ?? (existsSync(venv) ? venv : "python3");

const run = (name, cmd, args, opts) => {
  const p = spawn(cmd, args, { stdio: ["ignore", "pipe", "pipe"], ...opts });
  const tag = (d) => d.toString().split("\n").filter(Boolean).forEach((l) => console.log(`[${name}] ${l}`));
  p.stdout.on("data", tag); p.stderr.on("data", tag);
  p.on("exit", (code) => { console.log(`[${name}] stopped (${code})`); shutdown(); });
  return p;
};
const children = [
  run("api", python, ["-m", "chessme", "app", "--dev", "--no-browser"], { cwd: root, env: { ...process.env, PYTHONPATH: root } }),
  run("web", "npx", ["vite"], { cwd: resolve(here, "..") }),
];
let closing = false;
function shutdown() { if (closing) return; closing = true; children.forEach((c) => c.kill("SIGTERM")); setTimeout(() => process.exit(0), 500); }
process.on("SIGINT", shutdown); process.on("SIGTERM", shutdown);
console.log("Starting the MeChess API (http://127.0.0.1:8765) and the web app (http://localhost:5173). Open the second address. Ctrl+C stops both.");
