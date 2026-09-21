# Running on Kaggle

Four notebooks, on purpose. Collecting text and counting openings are CPU work and do **not** use the weekly GPU quota; only training and labelling do.
Each notebook is an **adapter**: it clones the repository, installs a few packages and runs `chessme` commands, nothing else. All the logic
(resuming from earlier output, linking inputs, checkpoints, time budgets) is in the repository, tested, and runs the same on a laptop; the
Kaggle-specific parts are in `chessme/kaggle.py` and the `--input-root`, `--data-dir`, `--resume-glob` and `--slim` flags.

| Notebook | Accelerator | What it does | Expected cost |
|---|---|---|---|
| `notebooks/1_collect_data_cpu.ipynb` | **None** | preflight, then `chessme books-learn`: 100+ books, all annotated-game sources, Stack Exchange, Wikipedia, opening names | CPU only; roughly 1 to 2 hours (about 300 MB of downloads) |
| `notebooks/2_train_language_model_gpu.ipynb` | **GPU** | preflight (GPU, dependencies, model download, data), a dry-run of the whole training path, then the real run with a time budget | about 105 minutes for 3 epochs of `distilroberta-base` on a T4 or P100 (measured) |
| `notebooks/3_opening_explorer_cpu.ipynb` | **None** | streams a Lichess database month (CC0) and builds the opening explorer for every rating range, a theory book per band and a report ([details](opening-explorer.md)) | hours; checkpointed, with a time budget |
| `notebooks/4_label_comments_gpu.ipynb` | **GPU** | `chessme books-nlp-label`: labels every annotated move's comment with the trained model (concepts, verdict, who stands better) and writes a report; trial on 2,000 moves first | needs the outputs of notebooks 1 and 2 as inputs; the GPU part is short (measured on a laptop CPU with 4 threads: about 115 short comments per second, so a few hundred thousand comments take under an hour even without a GPU; longer comments are slower) |

## How to run

1. Settings: *Internet -> On* (phone verification once). Notebook 2: *Accelerator -> GPU*; the others: *None*.
2. Put your repository URL in `REPO_URL` (first code cell).
3. **Save Version -> Save & Run All (Commit)**. A committed run does not depend on your browser, may run up to 12 hours, and keeps its output.
   An interactive session can be lost.
4. Notebook 2 needs notebook 1's output: *Add Input -> Notebook output files*. Set `DATA_DIR` to that output's folder (something like
   `/kaggle/input/notebooks/<your-username>/<notebook-name>`) or leave it empty to search everything under `/kaggle/input`. The notebook prints an
   **inventory** of what it found and stops if an expected source has no examples. The archives (`.tar.gz`) were read by notebook 1; their content is
   in `annotated_moves.jsonl.gz`.
5. To **continue** a run (notebooks 2, 3 and 4), add the notebook's own earlier output as an input and run it again: the checkpoint is restored.

Notebook 4 takes **two** inputs, the output of notebook 1 (the data) and of notebook 2 (the model, found as `nlp/model.pt` with `config.json`; a
model folder can be named with `MODEL_DIR`). It stops at once, before using the GPU, if either is missing. Its progress is saved every 2,048 moves, so an
interrupted or time-limited run continues exactly where it stopped (add its own earlier output as an input); the finished file is identical to an uninterrupted run.
The same on a laptop: `python -m chessme books-nlp-label --data data/books_learn --model-dir <model folder>`.

## What protects the quota

- `books-preflight` runs first and stops within a minute if a dependency, the disk, the GPU, a download URL or the model is unavailable. Tested: on
  a machine without a GPU, notebook 2 refuses at preflight with "turn on Settings -> Accelerator".
- Notebook 2 then runs a **dry-run** (a few examples, the same code path) that also fails unless the loss falls on 64 memorisable examples.
- The real run has a **time budget**: at the deadline it saves a checkpoint and ends normally, so the output is kept. Training also stops early
  after several validations without a new best model.
- Notebook 3 checkpoints every million games and every 15 minutes, guards memory, reconnects if the stream drops, and keeps its counts so
  `explorer-rebuild` can regenerate its outputs with other thresholds without streaming again.
- Training is resumable, and a resumed run gives the same result as an uninterrupted one (tested).

## Lessons from the first real runs

- A **committed** run keeps its output only if it finishes, so every long job has a time budget that ends it before Kaggle's 12-hour limit.
- The first explorer run ended silently after about an hour at 4% of its plan; the likely cause was the download connection closing. The reader
  now detects a short download and reconnects (see [opening-explorer.md](opening-explorer.md)).
- The log of a GPU run is worth reading while it runs: the first version showed a noisy total loss that hid the real signals, so the log now shows
  each head's loss and a validation check every 1,000 steps.

## Getting the output onto your machine

```bash
pip install kaggle          # a token in ~/.kaggle/access_token (or kaggle.json)
kaggle kernels output <your-username>/<notebook-name> -p data/explorer_kaggle --file-pattern '^explorer/'
```

`--file-pattern` (a regular expression) skips the cloned repository that the notebook's working folder also contains.

## Terms

Public-domain books only. Annotated games keep the terms of their sources; Stack Exchange and Wikipedia text is CC BY-SA. Use the outputs for
research and learning; do not redistribute the text. Never publish a notebook or output that contains your own books' text.
