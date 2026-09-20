# Running on Kaggle

Three notebooks, on purpose. Collecting text and counting openings are CPU work and do **not** use the weekly GPU quota; only training does.

| Notebook | Accelerator | What it does | Typical cost |
|---|---|---|---|
| `notebooks/1_collect_data_cpu.ipynb` | **None** | preflight, then `chessme books-learn`: 100+ books, all annotated-game sources, Stack Exchange, Wikipedia, opening names | CPU only; expect roughly 1 to 2 hours for the full run (the archive downloads are about 300 MB) |
| `notebooks/3_opening_explorer_cpu.ipynb` | **None** | streams a Lichess database month (CC0) and builds an opening explorer for **every rating range** (`explorer.db`: games, White/draw/Black, average rating, engine evaluation, opening names, clock use), a playable theory book per band (`theory_LO_HI.bin`) and a report | CPU only; roughly 4 to 8 hours with the defaults (about 100 M games scanned, about 10 M counted, exact counts); checkpointed, with a time budget |
| `notebooks/2_train_language_model_gpu.ipynb` | **GPU** | preflight (GPU, dependencies, model download), a dry-run of the whole training path, then the real run with a time budget | GPU; the budget (`BUDGET_MIN`, default 600 min) caps it |

## The notebooks are adapters

Each notebook only clones the repository, installs a few packages and runs `chessme` commands; nothing else. All the logic (resuming from earlier output, linking inputs, cleaning up, checkpoints, time budgets) is in the repository, tested, and runs the same on a laptop. The Kaggle-specific parts are in `chessme/kaggle.py` and the `--input-root`, `--resume-glob` and `--slim` flags.

## How to run (all notebooks)
1. Settings: *Internet -> On* (phone verification once). Notebook 1: accelerator *None*. Notebook 2: *GPU*.
2. Put your repository URL in `REPO_URL` (first code cell).
3. **Save Version -> Save & Run All (Commit)**. A committed run does not depend on your browser, may run up to 12 hours, and keeps its output. An interactive session can be lost.
4. Notebook 2 needs notebook 1's output: *Add Input -> Notebook output files -> notebook 1*.

## What protects the quota
- `books-preflight` runs first in both notebooks and stops within a minute if a dependency, the disk, the GPU, a download URL or the model is unavailable. Tested: on a machine without a GPU, notebook 2 refuses at preflight with "turn on Settings -> Accelerator".
- Notebook 2 then runs `books-nlp-train --dry-run` (a few hundred examples, 20 steps, the same code path, writes nothing): about a minute.
- The real run has `--deadline-minutes`: at the deadline it saves a checkpoint and finishes normally, so nothing is lost when the 12 h limit approaches.
- Training is resumable: add the notebook's own earlier output as an input and rerun; it resumes from the checkpoint (tested: 0 -> 154 -> 756 steps across three sessions).
- Everything in notebook 1 is resumable and skips finished work.
- Notebook 3 checkpoints every million games and every 15 minutes (atomic, refused if the settings changed), guards memory, stops cleanly at its time budget and keeps its counts so `chessme explorer-rebuild` can regenerate the outputs with other thresholds without streaming again. Adding its own earlier output as an input resumes it.

## After the run
- Notebook 3 output: `explorer.db` (query with `python -m chessme explorer-query explorer.db --rating 1500 --fen "..."`), `theory_*.bin` (put them in `data/book/`; `mechess --book data/book --elo 1500` picks the band), `report.md`.
- Notebook 1 output: `report.md` (what was extracted), `annotated/annotated_moves.jsonl.gz`, `prose/`, `books/`, `concept_line_pairs.jsonl`.
- Notebook 2 output: `nlp/` (the trained model, `metrics.json`, `thresholds.json`), `nlp.log`.
- The same commands run on a laptop: `python -m chessme books-learn --out data/books_learn`, then `python -m chessme books-nlp-train --data data/books_learn --backend bow` (or `--backend transformer` with a GPU).

## Terms
Public-domain books only. Annotated games keep the terms of their sources; Stack Exchange and Wikipedia text is CC BY-SA. Use the outputs for research and learning; do not redistribute the text.
