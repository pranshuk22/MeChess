# Code audit: bugs, issues and mistakes

Date: 2026-10-11. Scope: the C++ engine (`engine/`), the `chessme` Python package, the uncommitted work in the tree
(`chessme/book/rangescan.py`, the `explorer-range-scan` command in `chessme/cli.py`), `tools/*.sh`, the packaging files and the docs.

**Status (2026-10-11, later the same day): every finding below has been fixed, with a regression test, except where marked "not changed".**
Each section ends with a "Fixed:" line saying what was done. The summary table's last column was the state at audit time.

**Baseline:** `make test` passes: C++ unit tests, the perft suite, and 916 Python unit tests in about 130 s. Every finding below
is either **reproduced** (a command or snippet showed the wrong behaviour) or **from reading the code** (the logic is clear, but I did
not trigger it). Each finding says which.

No personal data turned up in tracked files or in git history: none of the account names in `data/raw/` appear in either, and no
commit has a co-author line.

---

## Summary

| # | Severity | Area | Finding | Status |
|---|---|---|---|---|
| 1 | High | books / kaggle | `books-nlp-train --slim` deletes the real corpus folders when they are not symlinks | reproduced |
| 2 | High | CLI / docs | The README quick start fails: `fetch`/`ingest`/`audit`/`book` require `--profile`, so `CHESSME_PROFILE` is ignored | reproduced |
| 3 | High | range-scan (uncommitted) | The merge loads every window's counts into memory at once, so memory is not bounded per window | code reading |
| 4 | Medium | range-scan (uncommitted) | Range fetch never checks for `206` or the body length; a zero-length window sends an invalid `Range` header | code reading |
| 5 | Medium | explorer / range-scan | Packed 24-bit counters overflow silently once a band is uncapped | code reading |
| 6 | Medium | range-scan (uncommitted) | Per-window pruning understates what was dropped (`pruned_below` is a max, not a sum) | code reading |
| 7 | Medium | engine | `set_fen` accepts castling rights without a rook and impossible en-passant squares, which corrupts the board | reproduced |
| 8 | Medium | engine | `set_fen` accepts pawns on rank 1/8, so movegen shifts by 64 (undefined behaviour) | reproduced |
| 9 | Medium | engine | The 50-move rule is applied before mate: the engine misses mate-in-1 at halfmove 99 | reproduced |
| 10 | Medium | analysis | Game keys include the file index, so re-running `report-select` re-analyses every game and double-counts it in reports | code reading |
| 11 | Medium | analysis | A crashed or timed-out Stockfish stays cached in the worker, so every later game in that worker fails | code reading |
| 12 | Medium | ingest | chess.com monthly archives older than last month are never refreshed, so partially fetched months lose games for good | code reading |
| 13 | Medium | packaging | `pyproject.toml` leaves out `chessme.analysis`, `chessme.books` and `sources.json`; `config.ROOT` breaks once installed | code reading |
| 14 | Low/Med | ingest | Lichess arena and team-battle games are stored as unrated | reproduced on local data |
| 15 | Low/Med | ingest | Fallback time class puts 2+0, 2+1 and 1+2 in blitz (Lichess: bullet below 180 s) | reproduced |
| 16 | Low/Med | model | `--freeze-body` still updates BatchNorm running stats in the "frozen" body | code reading |
| 17 | Low | controller | Temperature 0 underflows every weight to 0 and picks the engine's first move, not the most likely one | reproduced |
| 18 | Low | audit | `audit` crashes when a kept game has no rating | reproduced |
| 19 | Low | ingest | Colour defaults to black when neither player name matches the account | code reading |
| 20 | Low | tools | `tools/watch.sh` always exits 0, so failures and OOM kills are invisible to the chain scripts | code reading |
| 21-35 | Low | various | Smaller correctness, robustness and documentation issues | see below |

---

## High

### 1. `books-nlp-train --slim` deletes the real data folders (data loss)
`chessme/kaggle.py:81` (`slim_nlp`), called from `chessme/cli.py:954`.

`slim_nlp` is meant to "remove the linked data". For each of `annotated/`, `prose/` and `books/` it unlinks the path when it is a
symlink and otherwise **`shutil.rmtree`s it**. On Kaggle these are symlinks. Run locally (no `--input-root`/`--data-dir`, with
`--data data/books_learn`), they are the real collected corpus, so `--slim` erases hours of downloads after training.

**Reproduced:** I made a temp folder with real `annotated/`, `books/` and `prose/` directories and called
`KG.slim_nlp(folder)`. All three were deleted.

**Fix:** only unlink symlinks (`if p.is_symlink(): p.unlink()`), never `rmtree` a data directory; or refuse `--slim` unless
`--input-root`/`--data-dir` was given. The `nlp_dry` folder can stay as an `rmtree` because the code creates it.

**Fixed: `slim_nlp` now only unlinks symlinks (and still removes `nlp_dry`). Test: `test_slim_nlp_never_deletes_a_real_data_folder`.**

### 2. The README quick start fails: `CHESSME_PROFILE` is ignored by the core commands
`chessme/cli.py:1319, 1325, 1329, 1368, 1387` (`--profile required=True`); `README.md:70-75`; `docs/getting-started.md:44, 60-63`;
`docs/cli.md:4-5`.

The README says `export CHESSME_PROFILE=me`, then `python -m chessme fetch`. But `fetch`, `ingest`, `audit`, `openings`,
`texel-data` and `book` declare `--profile` as required, and only later commands default to `DEFAULT_PROFILE`.
**Reproduced:** `python -m chessme fetch` gives `error: the following arguments are required: --profile`. `docs/cli.md` also says
every `--profile` defaults to `$CHESSME_PROFILE`, which is wrong for these commands.

Also, `me-data user` has `--profile` with no default, so without it `load_profile(None)` looks for `configs/profiles/None.yaml`.

**Fix:** `default=DEFAULT_PROFILE` everywhere (drop `required=True`), including `me-data`.

**Fixed: every `--profile` defaults to `$CHESSME_PROFILE` (`me-data` included). Test: `test_commands_with_a_profile_take_it_from_the_environment`.**

### 3. `explorer-range-scan`: the merge holds every window in memory at once (uncommitted code)
`chessme/book/rangescan.py:212`: `merge_counts([EX.load_state(t[-1]) for t in tasks])`.

The docstring says "Memory is bounded per window (`max_entries`), not by how many windows there are". The list comprehension loads
**all** window states (200 by default, up to 5M entries each via the CLI default) before merging starts. The merged tables also have
no `max_entries` cap.

After that, `cmd_explorer_range_scan` pickles the merged counts and `EX.rebuild` loads that pickle again, so two full copies are
in memory at the peak. On a RAM-tight laptop this is the step most likely to be OOM-killed, and it happens after the long scan.

**Fix:** merge incrementally (load one window, add it, drop it), prune the merged counts against a cap, and pass the merged
`Counts` straight to the output writer instead of pickling and reloading.

**Fixed, then superseded by the plan.md 8u work: windows are saved as key slices and merged one slice at a time (peak memory is one slice, `--slices`), exactly; the CLI drops the merged counts before `rebuild` reloads the checkpoint. Tests: `test_the_sliced_merge_*`, `test_run_scans_a_local_dump_*`.**

---

## Medium

### 4. Range fetch never validates the response (uncommitted code)
`chessme/book/rangescan.py:111` (`HttpRangeFetcher.fetch`), `scan_window`.

- `fetch` never checks `resp.status == 206` or `len(body) == length`. If a CDN node ignores `Range` and answers `200`, the whole
  28 GB dump is read into memory.
- A window whose start and end snap to the same frame has `true_end == true_start`. That can happen with a large `--parts`, once
  windows get smaller than a ~4.7 MB frame. Then `fetch(start, 0)` sends `Range: bytes=S-(S-1)`. A range whose last byte is
  before its first is invalid, and RFC 7233 tells servers to ignore an invalid `Range` header and send the full `200` body.
- Each window is one 140 MB `resp.read()` with no retry. Any transient failure aborts the whole `run_pool`. Reruns resume, but
  this is the failure mode the module exists to avoid.

**Fix:** skip empty windows, assert a `206` status, a `Content-Range` that matches the request and the body length, and retry a
window a few times before failing.

**Fixed: `HttpRangeFetcher` requires `206`, a `Content-Range` starting at the requested byte and a body of the promised length, retries with back-off, and never sends an empty range; a window smaller than one frame is empty and harmless. Also fixed along the way: a window starting inside the file's last frame used to raise "no frame start found". Tests: `test_fetcher_*`, `test_a_window_*`, `test_every_game_is_counted_exactly_once_*`.**

### 5. Packed counters overflow silently past 16.7M games per entry
`chessme/book/explorer.py:43, 78` (`MASK24`, `pack`), `merge_counts` in `rangescan.py`.

Each table entry packs games, White wins and draws into 24-bit fields of one integer. Overflowing the games field carries into the
wins field, with no error. `explorer-build` stays safe only because `--max-per-band` defaults to 1M, and nothing stops a user
from setting it above 2^24. The range scan removes the per-band cap ("counts every qualifying game in every window") and
adds packed integers across windows. With the default bands, a full month puts the busiest entries at about 7-10M games, a factor of
2 under the limit. With coarser `--bands` (for example `1200 2000`), the start position's `e4` entry overflows.

**Fix:** widen the fields (for example 40 bits each; Python integers are unbounded), or assert `g < 2**24` when packing and merging.

**Fixed: fields are 32 bits wide (`FIELD_BITS`); checkpoints carry a `layout` number and old 24-bit ones are converted on load. Tests: `test_packed_counts_do_not_overflow_*`, `test_a_checkpoint_of_the_old_24_bit_layout_*`.**

### 6. Range-scan pruning understates what was dropped (uncommitted code)
`chessme/book/rangescan.py:177`.

Each window prunes its own rare entries (count at most *t* in that window). After the merge, an entry can be missing up to
*t* × (number of windows) games: one game in each of 200 windows is 200 games, all dropped. The report still says "entries with at
most `pruned_below` games may be missing", because `pruned_below` is merged with `max`. Rare moves are also biased downward
systematically. **Fix:** report the summed bound, or skip pruning inside windows and prune once after merging.

**Fixed: the per-window bounds are summed when merging (and the merge-level prune adds its own). Superseded: windows are no longer pruned at all (they stop the scan past `--max-entries`); the merge records what it drops in `pruned_below`. Tests: `test_a_window_over_max_entries_*`, `test_a_move_seen_once_in_every_window_survives_the_merge`.**

### 7. Engine: inconsistent FENs corrupt the board
`engine/src/board/position.cpp:149-165` (`set_fen`), `engine/src/movegen/movegen.cpp:62, 75-87`.

Castling rights are never checked against the king and rook squares, and the en-passant square is never checked (rank, empty
square, enemy pawn behind it). **Reproduced:**
- `position fen 4k3/8/8/8/8/8/8/4K3 w K - 0 1`: `perft 1` gives 6 (correct is 5), and `moves e1g1` is accepted. `make_move` then
  "moves" `NO_PIECE` from h1, which XORs phantom bits into `by_color_[WHITE]`.
- `position fen 4k3/8/8/8/8/8/3P4/4K3 w - e3 0 1`: `perft 1` gives 7 (correct is 6), with an en-passant "capture" `d2e3` of a
  pawn that does not exist.

Real GUIs and lichess-bot send `startpos moves ...`, so the main path is safe, but any FEN-taking path is not: the Python
`go(fen, ...)` callers, `explorer-query`, and test positions. **Fix:** in `set_fen`, drop castling rights whose king or rook is not on
its home square, and clear the ep square unless it is on rank 3/6, empty, with an enemy pawn in front of it.

**Fixed: `set_fen` drops castling rights the king/rook squares do not back up and an en-passant square without a pawn that just double-stepped. Tests: `Position.CastlingRightsWithoutKingOrRookAreDropped`, `Position.ImpossibleEnPassantSquareIsDropped`.**

### 8. Engine: pawns on the first or last rank are accepted
Same function. **Reproduced:** `position fen P3k3/8/8/8/8/8/8/4K3 w - - 0 1`, `perft 1` gives 6 (5 king moves plus one bogus pawn
move). For a white pawn on rank 8, `one = from + 8` is ≥ 64, so `bit(one)` shifts a 64-bit value by 64 or more, which is undefined
behaviour. **Fix:** reject pawns on rank 1/8 in `set_fen` (python-chess treats such a FEN as invalid too).

**Fixed: such a FEN is rejected (position unchanged). Test: `Position.RejectsMalformedFenAndKeepsState`.**

### 9. Engine: the 50-move rule is applied before checkmate
`engine/src/search/search.cpp:113, 177`.

`halfmove_clock() >= 100` returns 0 before mate is detected, but checkmate on the move that reaches 100 half-moves counts as a mate.
**Reproduced:** `position fen 7k/5Q2/6K1/8/8/8/8/8 w - - 99 80`, then `go depth 4`, gives `score cp 0, bestmove f7f1`. `Qg7#` is
missed. **Fix:** when the clock is ≥ 100 and the side to move is in check, return 0 only if it has a legal move.

**Fixed in `negamax` and `qsearch`: at 100 half-moves the position is a draw unless the side to move is checkmated. Tests: `Search.MateOnTheFiftyMoveClockIsStillMate`, `Search.FiftyMoveClockStillDrawsWithoutMate`.**

### 10. Analysis: game keys depend on file order, so reports double-count games
`chessme/analysis/runner.py:145` (`game_key`), `chessme/analysis/select.py:30`, `chessme/cli.py:789-791`.

The key is `f"{index:05d}-{gid}"`. `report-select` writes games **newest first**, so each re-run with new games shifts every
older game's index. `analyse` then finds no JSON under the new key, re-analyses every game, and keeps the old JSON files.
`render_report` and `report-leaks` read every `games/*.json`, so each game is counted twice. The `split_halves` docstring
("oldest-looking first") is also wrong: index 0 is the newest game. **Fix:** key by the site or game id alone, and fall back to a
hash of the movetext.

**Fixed: keys are the Lichess game id, else a hash of players/date/moves; the report covers only the games of the PGN given; the leaks split-half orders by game date; `analyse` warns about old position-named files. **Existing `data/analysis*/games/` folders made by older versions still hold position-named files: delete them (or use a new `--out`) before re-running, or those games are counted twice.** Tests: `test_game_keys_do_not_depend_on_the_position_in_the_file`, `test_the_halves_alternate_through_time_*`.**

### 11. Analysis: a dead engine poisons the rest of a worker's games
`chessme/analysis/pool.py:31-39`.

`_STATE` caches the engine and is rebuilt only when `nodes` changes. If Stockfish crashes, or `UciEngine._readline` kills it on a
timeout, every later `new_game()`/`go()` raises "engine is not running". That error is caught and reported as a failure for **every
remaining game** of that worker. **Fix:** check `proc.poll()`, as `match._engine_for` already does, and on an `EngineError` drop
the cached state so the next task restarts the engine.

**Fixed: the worker checks the engine is alive before each game and drops it when a game fails with it dead. Tests: `tests/unit/test_analysis_pool.py`.**

### 12. chess.com: partially fetched months are never refreshed
`chessme/ingest/chesscom.py:23-35`.

Only the current and previous months are re-downloaded. If you fetched on Aug 15 and next fetch on Oct 11, `2026-08.json` holds
only half of August and is never fetched again, so those games are lost silently. **Fix:** store the fetch time in each month's file
(or `state.json`) and re-fetch any month that was last fetched before it ended.

**Fixed: an archive is final only if its file was written after its month ended (file modification time); older files are re-fetched once. Test: `test_chesscom_refetches_a_month_that_was_saved_before_it_ended`.**

### 13. Packaging: `pip install .` gives a broken CLI
`pyproject.toml:17`, `chessme/config.py:5`.

- `packages = [...]` leaves out `chessme.analysis` and `chessme.books`, so `chessme analyse`, `report-*` and all `books-*` commands
  fail with `ModuleNotFoundError` from an installed copy. The `[project.scripts] chessme` entry point says installing is a supported
  path.
- `chessme/books/sources.json` is not declared as package data.
- `config.ROOT` is the parent of the package directory. Installed, that is `site-packages/`, so profiles and `ENGINE_BIN` resolve
  to the wrong place.

**Fix:** `[tool.setuptools.packages.find]` plus `package-data`, and resolve the project root from the working directory or an
environment variable instead of from `__file__`.

**Fixed: `packages.find` with `chessme*`, `package-data` for `sources.json`, and `config.find_root()` (`$CHESSME_ROOT`, else the checkout, else the current folder). Tests in `test_config.py`.**

### 14. Lichess arena and team-battle games are stored as unrated
`chessme/ingest/normalize.py:140` (`rated="rated" in event`).

Arena and team-battle events such as `Hourly SuperBlitz Arena` or `... Team Battle` are rated but contain no "rated".
**Reproduced on local data:** about half of the Lichess games marked unrated come from such events. The audit's "casual games"
line is inflated by this, and so is anything that filters on `rated`. **Fix:** use the API's rated flag, or treat any event other
than `casual ...` as rated.

**Fixed: a game is rated unless its event starts with "casual". **Re-run `chessme ingest` to correct `rated` in an existing `games.jsonl`.** Test: `test_arena_and_team_battle_games_count_as_rated`.**

### 15. Fallback time class uses the wrong bullet threshold
`chessme/ingest/normalize.py:29`.

The limit is `(120, "bullet")`. Lichess (and `mechess/clock.py:26`, `book/explorer.py:speed_of`) uses bullet below 180 s.
**Reproduced:** `120+0`, `120+1` and `60+2` come out as blitz. This only runs when the Event header names no class (some team
battles), and none of the local data hits it, so it is latent. **Fix:** use 180, and share one `time_class` function.

**Fixed: one `normalize.time_class_of` (bullet below 180 s) used by ingest and the clock model. Tests: `test_time_class_rule`, `test_time_classes_agree_with_ingest_at_the_bullet_boundary`.**

### 16. `--freeze-body` does not freeze the body
`chessme/model/train.py:135-137, 161`.

Only `requires_grad` is cleared. `model.train()` still runs the body's BatchNorm layers in training mode, so their running mean and
variance drift toward the fine-tuning data, and the exported (BN-folded) network changes. **Fix:** put the body's BN modules in
`eval()` after `model.train()`, or set `momentum=0` on them.

**Fixed: `set_train_mode` keeps the frozen body in eval mode. The old test excluded the running statistics from its "unchanged" check; it now includes them. Tests: `test_fine_tuning_starts_from_a_checkpoint_*`, `test_a_frozen_body_keeps_its_batchnorm_statistics_in_eval_mode`.**

---

## Low

17. **Temperature 0 picks the wrong candidate** (`chessme/mechess/controller.py:177-179`). With `T` floored at 1e-3,
    `exp(log(prior)/T)` underflows to 0 for every candidate once the top prior is below about 0.47. `max` then returns the first
    candidate (the engine's best), not the most likely move. **Reproduced** with priors (0.15, 0.40, 0.15, 0.15, 0.15). No current
    table row uses `T=0`, but a calibration or user table could. Fix: when `T<=0`, pick by `(prior, -loss)` directly, or compute
    the weights in log space.
    **Fixed (weights are computed relative to the best, in log space; `T <= 0` picks by prior). Tests: `test_temperature_zero_*`, `test_a_tiny_positive_temperature_*`.**
18. **`audit` crashes on a kept game without a rating** (`chessme/audit.py:133-135`). `min(v)` over a list containing `None`
    raises `TypeError`. **Reproduced.** A kept game can lack a rating when the profile has no floor for that platform.
    **Fixed (also an empty input). Test: `test_audit_survives_empty_input_and_games_without_a_rating`.**
19. **Colour defaults to black** (`chessme/ingest/normalize.py:62`). If neither `White` nor `Black` matches the account (case
    differences are handled, renamed accounts are not), the game is stored as black with the opponent's name taken from `White`.
    Mark the game unusable instead.
    **Fixed: unusable with reason `account_not_in_game`, colour/ratings/result left empty. Test: `test_a_game_the_account_did_not_play_is_unusable_not_black`.**
20. **`tools/watch.sh` always exits 0**, also after the job fails or after it kills the tree for memory. `after_fetch.sh` and
    `after_calibration.sh` cannot tell. `after_calibration.sh` only checks that `$CAL_OUT` exists, which an older file also
    satisfies. Fix: `wait $root; rc=$?` and `exit $rc` (or 137 after a kill).
    **Fixed: exits with the command's status, 137 when killed for memory; the chain scripts stop at the first failed step, and `after_calibration.sh` also refuses a calibration file older than this run's style model. Tests: `tests/unit/test_tools_scripts.py`.**
21. **`tools/await_log.sh` only works on macOS**: `stat -f %m` means something else on Linux, so stall detection breaks there.
    **Fixed (GNU `stat -c %Y`, then BSD `stat -f %m`).**
22. **`theory.build` records a 0% score as 50%** (`chessme/book/theory.py:188`): `... and score[k][u] else 500` treats a total
    of 0.0 as missing. `render` (line 207) also hard-codes "15 times and 8%" instead of the real `extend_min_*` values.
    **Fixed (scores are averaged over games with a known result; the report prints the real thresholds). Tests in `test_book_theory.py`.**
23. **`games_fetch.run` raises `IndexError`** (`chessme/style/games_fetch.py:123`) when every selected game fails `game_record`
    (an empty `recs`). It also writes a non-short player with fewer than `min_games` records.
    **Fixed (a player with fewer processable games than `min_games` is written as short). Test: `test_games_that_cannot_be_processed_make_a_short_player_not_a_crash`.**
24. **`jobs.run_pool` counts queue time in `task_timeout`** (`chessme/jobs.py:143, 152`). The clock starts at submission, and up
    to 2 × `workers` tasks are queued, so a slow-but-healthy pool can raise `TaskTimeout`.
    **Fixed (the clock starts when a task is among the oldest `workers` pending). Test: `test_time_spent_waiting_in_the_queue_does_not_count_towards_the_timeout`.**
25. **UCI engine:** `go depth N wtime ...` ignores the clock (`make_limits` only budgets time when `depth == 0`), so a depth-limited
    game can lose on time. `MeRating`, `MeOppRating` and `MePlatform` are not clamped to the advertised ranges. `Hash 4096` can
    throw `bad_alloc` and kill the process.
    **Fixed: a depth/node limit no longer switches the clock off; the Me* options are clamped; a failed `Hash` allocation is reported and falls back to 16 MB. Tests: `Uci.DepthLimitedGoStillCarriesTheClock` and others.**
26. **Search: the MultiPV root writes the root TT slot** with the best *non-excluded* move of the last line
    (`search.cpp:305-309`). The next iteration then orders that (worst) move first. This costs speed only, not correctness.
    **Fixed (no table store at the root while moves are excluded). Test: `Search.MultiPvKeepsTheBestMoveFirstAcrossIterations`.**
27. **"Lichess accuracy" differs from Lichess** (`chessme/analysis/classify.py:34-37`). Lichess clamps to ±1000 cp before the
    win% sigmoid; this code clamps to ±10000, so drops in won positions (+3000 to +1000) cost accuracy here but not on Lichess.
    **Fixed for accuracy only (`LICHESS_CP_CAP`); classification keeps its own scale. Test: `test_accuracy_clamps_the_score_like_lichess_but_classification_does_not`.**
28. **`MeNet::load` checks only some tensors for NaN/Inf** (`engine/src/net/menet.cpp:116`): the residual-block weights, biases,
    `qk_b_` and `under_b_` are skipped.
    **Fixed (every tensor). Test: `MeNet.NonFiniteValuesAreRejectedInEveryTensor`.**
29. **`train.train`:** `evaluate(...)["all"]` raises `KeyError` on an empty validation shard, and `history.jsonl` is appended across
    runs into the same folder, so histories of different runs mix.
    **Fixed (an empty validation shard is tolerated; `history.jsonl` starts fresh for each run). Test: `test_training_with_an_empty_validation_shard_and_a_repeated_output_folder`.**
30. **`ingest/http.get`:** the docstring promises retries on "transient errors", but 5xx is returned, not retried. A library
    function also raises `SystemExit`. In `lichess.fetch`, an exception during `iter_content` escapes and leaves `download.part`
    behind (harmless, it is overwritten next time).
    **Fixed: 5xx is retried with back-off; a download cut short is deleted and does not move `since_ms`. The `SystemExit` after exhausted retries is kept (callers rely on it) and now documented. Tests in `test_http.py`, `test_fetchers.py`.**
31. **Explorer movetext parser** (`chessme/book/explorer.py:_SAN`): a move with a suffix glyph (`Qh5?!`) separates its
    `{...}` comment from the move, and the words inside the comment (`eval`, `clk`) are read as moves, which truncates the game.
    **Reproduced** with a synthetic line. The local Lichess exports contain no glyphs, so real dumps are probably unaffected, but
    the parser is fragile. Allow `[?!]*` after the SAN.
    **Fixed (`[!?]*` after the move). Test: `test_movetext_with_move_glyphs_keeps_its_comments_attached`.**
32. **Study export file names** (`chessme/books/studies.py:42`) are an unsalted `sha1(username)[:8]`, which is easy to reverse by
    hashing candidate names. The cohort code uses a salt; do the same here (the files are local, so this is minor).
    **Fixed (salted SHA-256, salt kept in the export folder; existing exports are fetched again once). Test: `test_study_file_names_are_salted_*`.**
33. **`ClockModel._cell`** falls back to an arbitrary first cell when every cell is sparse, not to the largest or the pooled one.
    **Fixed (the largest cell). Test: `test_when_every_cell_is_sparse_the_largest_one_is_used`.**
34. **CLI nit (uncommitted):** the `explorer-range-scan` parser block sits between `explorer-build`'s arguments and
    `eb.set_defaults(...)`. It works, but separates the two halves of one command's definition.
    **Fixed (block moved after `eb.set_defaults`).**
35. **Docs:** the `Makefile`, README and CONTRIBUTING say `make test` takes "a few seconds"; it took about 2.5 minutes here
    (130 s of Python unit tests).
    **Fixed (the docs now say a couple of minutes); the new behaviours are documented in `docs/cli.md`, `docs/operations.md`, `docs/game-analysis.md`, `docs/getting-started.md`.**

---

## Checked and correct
- Move generation: the perft suite passes, including the mirrored positions and the `--verify` incremental hash and unmake checks.
- The Zobrist ep key is included only when an en-passant capture is possible, and stays consistent through null moves.
- The Python/C++ book key (FNV-1a over the first three FEN fields) and the book file format agree. The `MeNet` encoding,
  move index and the BN folding at export agree.
- `uci_client` MultiPV block reassembly, SPRT/pentanomial math, the Elo ladder MLE, isotonic calibration and the `joint_fit`
  damped Newton.
- `zstandard` 0.25 (pinned) reads across frames by default, so `me-data`'s `.zst` reader (`model/data.py:287`, no
  `read_across_frames`) is fine with the pinned version. It depends on that version, though: passing `read_across_frames=True` as
  `explorer.open_dump` does would make it explicit.
