# Running on Kaggle

Two notebooks, on purpose. Collecting text is CPU work and does **not** use the weekly GPU quota; only training does.

| Notebook | Accelerator | What it does | Typical cost |
|---|---|---|---|
| `notebooks/1_collect_data_cpu.ipynb` | **None** | preflight, then `chessme books-learn`: 100+ books, all annotated-game sources, Stack Exchange, Wikipedia, opening names | CPU only; expect roughly 1 to 2 hours for the full run (the archive downloads are about 300 MB) |
| `notebooks/2_train_language_model_gpu.ipynb` | **GPU** | preflight (GPU, dependencies, model download), a dry-run of the whole training path, then the real run with a time budget | GPU; the budget (`BUDGET_MIN`, default 600 min) caps it |

## How to run (both notebooks)
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

## After the run
- Notebook 1 output: `report.md` (what was extracted), `annotated/annotated_moves.jsonl.gz`, `prose/`, `books/`, `concept_line_pairs.jsonl`.
- Notebook 2 output: `nlp/` (the trained model, `metrics.json`, `thresholds.json`), `nlp.log`.
- The same commands run on a laptop: `python -m chessme books-learn --out data/books_learn`, then `python -m chessme books-nlp-train --data data/books_learn --backend bow` (or `--backend transformer` with a GPU).

## Terms
Public-domain books only. Annotated games keep the terms of their sources; Stack Exchange and Wikipedia text is CC BY-SA. Use the outputs for research and learning; do not redistribute the text.
