# The MeChess app

One program on your computer that does everything MeChess offers, in the browser, without the command line: import your games, review them with the engine, practise your
mistakes, play against the computer, see how you are doing. Nothing leaves your computer except the requests you start (importing your games from Lichess or Chess.com).

## Start it

```bash
make app                    # builds the pages once (needs Node), then starts the app and opens your browser
# or, when the pages are already built:
.venv/bin/python -m chessme app
```

The app opens at an address like `http://127.0.0.1:8765/?t=...`. The part after `?t=` is the **access key of this run**: it keeps other programs on the same computer from using
the app. The page hands it to the server once and keeps it in a cookie; if you open `http://127.0.0.1:8765` in a browser that does not have it, the app says to use the address
it printed.

| option | meaning |
|---|---|
| `--data-dir DIR` | where the database and your files live (default `~/.mechess`); one app per folder |
| `--engine PATH` | Stockfish (default: `stockfish` on the PATH; also settable in Settings) |
| `--port N` | default 8765 (the older `chessme coach` uses 8766) |
| `--no-browser` | do not open a browser, only print the address |
| `--host ADDR` | listen address (default 127.0.0.1); only for use inside a container |
| `--dev` | also accept the Vite dev server on `localhost:5173..5180` |

For development: `cd frontend && npm install && npm run dev:all` starts the server and the hot-reloading pages together and prints the address to open (the access key changes every run; set `MECHESS_TOKEN=some-long-secret` before the command to keep the same address, so an open browser tab keeps working after a restart)
([ui.md](ui.md)).

### In a container

```bash
docker compose up --build          # then open the address with ?t=... that the log prints
```

The image holds the server, Stockfish and the C++ engine (no PyTorch: the app does not need it); the data lives in a volume. The port is published to `127.0.0.1` only. Set `MECHESS_TOKEN` in your environment to keep the same access key between runs.
Not built in CI: try it before relying on it.

## What is where

| Part | What it does |
|---|---|
| **Home** | the numbers that matter (games, accuracy, mistakes, results), your next step, recent games, openings, activity calendar, a checklist of what MeChess found on your computer |
| **Library** | all your games, searchable and filterable, any size; import from Lichess, Chess.com or a PGN file |
| **Review** | the board, every move classed (brilliant to blunder) with an icon, accuracy, the engine's best lines for each move, live engine analysis, the opening explorer, side lines you try yourself, and **Retry your mistakes** |
| **Coach** | practice positions from your own mistakes (repeated on a schedule), and where you lose points compared with players of your rating |
| **Play** | a game against Stockfish at eight levels, or MeChess at a chosen strength; finished games go to your library |
| **Insights** | accuracy by phase, move kinds, rating over time, results by colour and speed |
| **Activity** | imports, analyses and other work running in the background, with progress and cancel |
| **Settings** | accounts, engine, opening cache, colours, board and pieces (also your own images) |

## Your data

One SQLite file, `mechess.db` in the data folder, holds games, analyses (with the engine's lines for every move), practice positions, jobs, settings and the opening cache. Your own piece
sets and board images are plain folders next to it (`pieces/`, `boards/`). Older work is found and offered for import: the coach's reviewed games (`~/.mechess-coach`) and the folders written by
`chessme analyse` (`data/analysis/*`). Deleting the opening cache is always safe.

### The opening cache

The engine's verdict on opening positions (the first ten moves) is kept, so the openings you play are not searched again: analysing games reads from it and fills it, and stepping through a
game shows the stored lines at once while the engine works on something deeper. Settings has a card for it: how many positions, how often it was used, a button to build it for the
openings in your own games (optionally the main opening lines too), and one to delete it all.

## Security model (what is and is not protected)

* The server listens on `127.0.0.1` only. Requests must carry one of our own host names (against DNS rebinding) and, when they change something, one of our own origins (against other websites).
* Every `/api` request and the live-analysis WebSocket needs the access key of the run (a cookie set from the address that opened the app, or an `X-MeChess-Token` header for tools).
* Pages may not be framed, and may only load their own files (Content-Security-Policy); fonts and piece images are bundled, so the app makes no request to other websites.
* An engine path you set is started once, to check that it answers as a chess engine; nothing is started by merely opening a page.
* Imports are public games only (no passwords or tokens), one at a time per site, and can be cancelled.
* Uploaded SVG pieces are checked (no scripts, links or embedded objects) and served with a restrictive policy.
* Not protected: someone who can read your terminal output (it contains the key), or who is you.

## The API

The same server answers `/api/...` (interactive description at `/api/docs` while the app runs; the TypeScript types of the frontend are generated from it, `tools/gen_ts_types.py`). Long work is a job: start it, watch `/api/events` (server-sent events) or `/api/jobs`.

## Tests

`python -m pytest tests/unit -k "app_"` (backend, database, jobs, WebSocket, security), `cd frontend && npm test && npx playwright test` (browser tests against the real server with a temporary data folder).
