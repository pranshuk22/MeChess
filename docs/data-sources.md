# Data sources and privacy

## Where games come from

| Source | Used for | How | Terms |
|---|---|---|---|
| **Lichess API** (`/api/games/user/<name>`) | your games (`fetch`); cohort players' recent games (`style-cohort-fetch`) | HTTPS, PGN, one request at a time with polite pauses. Parameters used: `max`, `rated`, `perfType`, `moves`, `tags`, `clocks`, `opening`, `evals`, `since`; header `Accept: application/x-chess-pgn` | Lichess API terms and rate limits apply; an optional `LICHESS_TOKEN` (environment only) raises limits |
| **Lichess open database** (monthly `lichess_db_standard_rated_YYYY-MM.pgn.zst` at database.lichess.org) | pretraining data; population baseline; picking cohort candidates | **streamed** over HTTPS and decompressed in memory (`zstandard`); nothing is downloaded to disk; a byte budget (`--budget-mb`) stops the read | published under CC0 per the download page |
| **chess.com public API** (`api.chess.com/pub/player/<name>/games/...`) | your chess.com games (`fetch`) | monthly archives as JSON / PGN | chess.com API terms apply |
| **PGN Mentor** (`pgnmentor.com/players/<Name>.zip`) | famous players' games for the anchors | one small ZIP per player (0.4 to 2.5 MB), downloaded, sampled and **deleted immediately**; only derived decisions are kept | the site carries a copyright notice and no licence text; used for local analysis only, **never redistribute the archives** |
| Your own files | anchors without a downloadable archive | `--files DIR` with `<anchor>.pgn` | yours |

## What is stored, and where

Everything downloaded or derived is under `data/` (git-ignored):

- `data/raw/`: downloaded PGN files;
- `data/processed/games.jsonl`: normalised games;
- `data/me/`, `data/style/`: training shards, datasets and logs;
- cohort players are stored under **salted hashed ids** (the salt stays in your `data/`); their sampled decisions
  (position, played move, rating, game number) are kept, **not** their raw games; the list of candidate usernames
  (`candidates.json`) stays on your disk and must not be published.

## Text, annotated games and opening data

| Source | Terms | Used for |
|---|---|---|
| Lichess database (`database.lichess.org`) | CC0 | the opening explorer and theory books (streamed, never stored whole) |
| Lichess chess-openings | CC0 | opening names |
| Public-domain books (Project Gutenberg, Internet Archive) | public domain (check per country) | game lines and concept counts |
| Annotated games (GameKnot, PGN Library, Path to Chess Mastery, Lichess studies, `chess_studies`) | each source's own terms | comments and glyphs for the language model; research and learning use, not redistribution |
| Chess Stack Exchange, chess Wikipedia articles | CC BY-SA | explanations in prose for concept tagging; not redistributed |

What is stored from them: text, positions, glyphs, ratings, opening codes, results and **public game ids**. **Player names, usernames and
annotator names are never stored** (the code drops them on purpose, and tests check it). The explorer keeps counts, not games. Outputs stay local
(`data/` is git-ignored). Full list with verification notes: [training-resources.md](training-resources.md).

## Privacy rules the code follows

- Your account names live only in your profile file, which is git-ignored (`configs/profiles/*` except the example).
- Tokens are read only from the environment; no command writes a token to disk.
- The HTTP client sends a generic user agent (`chessme/0.1 (personal research project)`), never contact details.
- Only public games are used. Bots (BOT title in the game headers), variants, casual and abandoned games are skipped.
- Opponents appear in your games; only your own moves are used as your data.
- If you publish results, publish aggregates, not other people's games or usernames.

## Being a good API citizen

One request at a time, pauses between requests (`--pause`), back-off on HTTP 429 (a 65-second wait), retries on network
errors, and a clean stop after several failed requests in a row (a failed request never counts as a rejected player).
