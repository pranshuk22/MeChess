# The web app (frontend)

A single-page app in `frontend/` (React, Vite, TypeScript, Tailwind CSS). Status: **prototype** (home, library, review with the retry-your-mistakes loop, settings) running on bundled sample games; the Python backend (FastAPI + SQLite) that replaces the samples comes next.

## Run it

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
npm run build      # type check + production build in frontend/dist
npm test           # unit tests (Vitest)
npx playwright install chromium   # once
npx playwright test               # end-to-end tests: board, retry loop, no external requests, long list
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
