# The web app (frontend)

A single-page app in `frontend/` (React, Vite, TypeScript, Tailwind CSS). The server side (FastAPI + SQLite, jobs, live engine analysis) and what the app does are described in [app.md](app.md); this page is about the frontend.

## Run it

The app is two parts: the **server** (Python: API, database, background jobs, Stockfish) and the **pages** (this frontend). Both must run.

```bash
# for using it: build the pages once, then serve everything on http://127.0.0.1:8765
make app                          # = cd frontend && npm install && npm run build, then python -m chessme app

# for developing it (hot reload): both parts with one command, then open http://localhost:5173
cd frontend && npm install && npm run dev:all
```

Starting only `npm run dev` shows a "the MeChess server is not running" screen: the pages have nothing to talk to. `npm run dev:api` starts only the server.

The production build (`make app`) is also much smoother than the development server, which runs React's slow development mode. Tests:

```bash
cd frontend
npm test                          # unit tests (Vitest)
npx playwright install chromium   # once
npx playwright test               # end-to-end tests against the real server with its own temporary data folder
```

Players who only use the app never need Node: the built files ship inside the Python package (planned).

## Design rules

* One neutral palette and one accent; colour for move quality only, always with a symbol (`?!`, `?`, `??`), never colour alone.
* No ads, popups, telemetry, or requests to other websites: fonts and piece images are bundled and a test fails on any other host.
* Plain words first, jargon on hover. Keyboard: arrows step through moves, `F` flips, `B` shows the engine's best move.
* The board is our own component (`src/board`): pieces move with CSS transforms, dragging uses pointer events and touches no React state while the piece moves, legality is checked in the browser, arrows and square marks are drawn with right-click (right-drag for arrows).
* Three independent choices, all remembered: **website** (four palettes, Glacier, Paper, Forest and Graphite, each with a light and a dark mode; light is the default, "system" is an option), **board** (seven original colour themes, an optional light texture, or your own two colours) and **pieces** (six bundled sets with permissive licences, credits in the settings). A quick switcher sits beside the board. Commercial sets of other chess sites are not bundled; the plan is a local folder of images that you can add yourself.
* Review shows what Chess.com-style reviews show: a class for every move (brilliant, great, best, excellent, good, book, inaccuracy, mistake, miss, blunder) as a round icon on the board, in the move list and in a summary with counts per player, accuracy for both players and accuracy by phase.

## Sample data

`tools/make_ui_samples.py` writes `frontend/src/samples/sample-games.json`: three public-domain classics and engine-played games, analysed with the same analysis code as the coach. It is replaced by your own games once the backend exists.
