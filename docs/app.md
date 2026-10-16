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
| **Review** | the board with captured pieces, the clocks and a performance rating for each side; a **coach card** pinned above the move list that says in plain words why each move was good or bad (what it allows, what was better) with the engine's lines; **Next key moment** (N / P): the last move of opening theory, your brilliant and great moves, your mistakes and the opponent's; a graph with both players' mistakes marked, hover and click; a chart of the time spent per move; the opening name as you step and where theory ended; live engine, explorer, side lines; **Retry your mistakes**; sounds, autoplay (Space), copy FEN / PGN, download, open on the analysis board; `?` lists the shortcuts |
| **Analysis** | the analysis board: paste a FEN or a PGN, move the pieces for both sides, step back and try another line, with the engine and the explorer |
| **Coach** | practice positions from your own mistakes (repeated on a schedule), opening practice, endgames, steered games, and where you lose points compared with players of your rating. Every move you try is **graded with reasons**: best, great (as good), good but not the best (it counts, and you may try for the best), inaccuracy, mistake, blunder; a bad try says what it allows (checkmate, a lost piece, the engine's line) without giving the answer away |
| **Coach → Openings** | an **opening library** from the opening database (named openings as repertoires, pruned by what players really play), **your own repertoire made from your games** (practise it, find its gaps), saved repertoires and your own PGN |
| **Prepare** | **Prepare against an opponent**: give their Lichess / Chess.com user name(s) (or paste a PGN) and get their weak openings, traps in their own games with the punishing move, a plan of your moves against what they really play (saved as a repertoire for the opening practice), their middlegame, endgame and clock weaknesses, and their latest games. See below |
| **Play** | a game against Stockfish at eight levels, or MeChess at a chosen strength, with or without a clock (1 minute to 3 hours, increments, flagging). The computer **takes its time like a person** (quick in the opening and for a recapture, longer in a tense position, its clock running while it thinks; it can be turned off). MeChess can learn to **choose moves like a person from your own games** (typical players of your library, or you). Finished games go to your library, with their clocks |
| **Insights** | your profile, filtered by speed, colour and period (the address keeps the filter): performance by play and by result, rating over time, results against stronger and weaker opponents, your openings with links to the games, accuracy by phase and by kind of endgame, tactics found / missed / allowed with the positions, habits (time of day, weekday, how a session goes, what a loss does to the next game), converting and saving, the clock, quality over time |
| **Activity** | imports, analyses and other work running in the background, with progress and cancel |
| **Settings** | accounts, engine, opening cache, colours, board and pieces (also your own images) |

## Prepare against an opponent

`Prepare` reads the opponent's public games (newest first, one request at a time, no passwords; or a pasted PGN), keeps them for this preparation only (deleted with it), and analyses them with
your engine and the opening cache: the openings of every game, and whole games for the most recent ones (*Quick*: none; *Standard*: 40; *Deep*: 120). The report has:

- **Your plan**: for each of your colours a tree of your moves and the replies this opponent has actually played (with how often). At each of your turns the planner picks the move with the best
  *expected* result against their observed replies, never more than 5 points under the engine's best move, or up to 12 points under when the opponent has been seen at least four times after
  it (a marked *gamble*). Your own record at each position breaks near-ties. Save a plan as a repertoire and practise it in Coach → Openings.
- **Their openings** by colour: games, results, score, how often they err in the first 12 moves, marked weak when they score clearly below their usual or often err early, next to your own record against it.
- **Traps**: positions in their games where their usual move gives away at least 8 points, how to get there (and whether your moves on the way are sound), the punishing reply and where it leaves you.
- **Middlegame and endgame**: where their mistakes are (phase, equal / better / worse positions, kind of mistake, kind of endgame, when short of time, converting advantages), against players of their rating when
  the reference counts exist.

All numbers come from the games found: with few games the report says so. Nothing is sent anywhere but the requests for their public games.

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
