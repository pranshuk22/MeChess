# The web app (frontend)

A single-page app in `frontend/` (React 19, Vite, TypeScript, Tailwind CSS 4, Radix UI primitives, TanStack Query and Virtual, react-router, zustand, chess.js, lucide icons). The server side (FastAPI + SQLite, jobs, live engine analysis) and what the app does are described in [app.md](app.md); this page is about the frontend.

## Run it

The app is two parts: the **server** (Python: API, database, background jobs, Stockfish) and the **pages** (this frontend). Both must run.

```bash
# for using it: build the pages once, then serve everything on http://127.0.0.1:8765
make app                          # = cd frontend && npm install && npm run build, then python -m chessme app

# for developing it (hot reload): both parts with one command, then open the address it prints (http://localhost:5173/?t=...)
cd frontend && npm install && npm run dev:all      # MECHESS_TOKEN=some-long-secret keeps the same address between runs
```

Starting only `npm run dev` shows a "the MeChess server is not running" screen: the pages have nothing to talk to. `npm run dev:api` starts only the server. The production build (`make app`) is much smoother than the development server, which runs React's slow development mode.

Tests:

```bash
cd frontend
npm test                          # unit tests (Vitest)
npx playwright install chromium   # once
npx playwright test               # end-to-end tests against the real server with its own temporary data folder (a few minutes)
```

`tools/gen_ts_types.py` writes `src/api/schema.ts` from the server's OpenAPI description; a backend test fails when the file is stale. Players who only use the app never need Node once the built files ship inside the Python package.

## Design rules

* **Look.** One neutral cool-grey palette ("Studio", the default) with a single green accent, Inter for everything (tabular figures for numbers; the monospace face only for notation), small radii, one control height (32 px), hairline borders instead of shadows, underlined tabs, a top bar with search, a light navigation rail with a profile block. Colour carries meaning only for move quality, always with a symbol (`?!`, `?`, `??`), never colour alone; text colours made from the quality palette are darkened toward the text colour so they pass the contrast checks.
* **No ads, popups, telemetry, or requests to other websites**: fonts and piece images are bundled and a test fails on any other host. Sounds are synthesised with the Web Audio API (no sound files).
* **Plain words first**, jargon on hover, technical set-up steps folded under "How to set this up". Empty states say what to do next.
* **Keyboard.** `Ctrl/Cmd + K` opens the command palette (pages, actions, your games by player or opening); `?` lists the shortcuts. In a review: arrows step, `Home` / `End`, `N` / `P` next and previous key moment, `Space` plays the game, `F` flips, `B` the engine's best move, `E` the engine, `Esc` leaves a side line. The board is operable from the keyboard.
* **Board.** Our own component (`src/board`): pieces move with CSS transforms, dragging uses pointer events and touches no React state while the piece moves, legality is checked in the browser, arrows and square marks with right-click (right-drag for arrows). The squares are flat by default (a light texture is an option). The size is adjustable (60 to 130 percent of the largest board that fits the window; 100 is the default), remembered.
* **Appearance** is three independent, remembered choices: the **website** (Studio, Catppuccin, Macchiato, Glacier, Paper, Forest, Graphite, each with a light and a dark mode; light is the default, "system" an option), the **board** (colour themes, an optional texture, your own two colours or your own images) and the **pieces** (six bundled sets with permissive licences, credits in Settings, your own SVG sets). A quick switcher sits beside the board. Commercial sets of other chess sites are not bundled.
* **Review** shows a class for every move (brilliant, great, best, excellent, good, book, inaccuracy, mistake, miss, blunder) as a round icon on the board and in the move list, a coach card with the reasons, captured pieces, clocks, performance and accuracy, a graph with both players' mistakes, and a chart of the time per move when the game has clocks.
* **Phones**: the same pages in one column, a bottom bar (Home, Library, Coach, Play) and a "More" sheet for the rest; a test fails when any page scrolls sideways at 390 px.
* **Performance budget** (tested): under 200 KB of JavaScript on a first visit (the command palette, the import dialog and the heavy pages load on demand), 10,000 games in the library stay smooth, dragging a piece does not block the main thread.
* **Accessibility** (tested with axe on every page in several palettes and both modes): contrast of at least 4.5 to 1, names for every control, a focusable main region, `aria-sort` on sortable columns, status text for background work.

## Sample data

`tools/make_ui_samples.py` writes `frontend/src/samples/sample-games.json`: three public-domain classics and engine-played games, analysed with the same analysis code as the coach. They seed the end-to-end tests and the first-run demo (`chessme app --seed-samples`).
