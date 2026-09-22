# Third-party software and data

MeChess uses the following. **None of it is bundled, copied or redistributed by this repository.**

| Software / data | Licence (as we understand it) | How MeChess uses it |
|---|---|---|
| [Stockfish](https://stockfishchess.org/) | GPL-3.0 | run as a **separate program** via UCI, as the judge of good moves; you install it yourself ([details](stockfish.md)) |
| [Maia-2](https://github.com/CSSLab/maia2) and Maia-3 (CSSLab) | code and weights under the authors' terms (AGPL-3.0 / research releases) | **optional external baselines and priors**: you download the checkouts and weights yourself; `me-compare` scores them, `me-maia3-ft` personalises a local copy. We do not copy their code; fine-tuned checkpoints are derivatives of their weights and must not be redistributed |
| [python-chess](https://python-chess.readthedocs.io/) | GPL-3.0 (library) | board logic and PGN parsing on the Python side; imported as a library |
| [PyTorch](https://pytorch.org/), NumPy, PyYAML, requests, zstandard | BSD-style / MIT / Apache-style | Python dependencies, pinned in `requirements.txt` |
| Lichess open database | CC0 per its download page | streamed pretraining and population data; the opening explorer and theory books |
| [Hugging Face Transformers](https://huggingface.co/docs/transformers) and encoder models (default `distilroberta-base`) | Apache-2.0 (library); each model has its own licence | the transformer backend of the chess-text model; downloaded at run time, not bundled |
| [Kaggle CLI](https://github.com/Kaggle/kaggle-cli) | Apache-2.0 | optional: downloading a notebook's output |
| ChessGPT data (`Waterhorse/chess_data`), `Icannos/chess_studies` | annotated PGNs: each source's terms; `chess_studies`: CC0; Stack Exchange and Wikipedia parts: CC BY-SA | annotated games and prose for the language model; downloaded at run time, not bundled |
| Public-domain chess books (Project Gutenberg, Internet Archive) | public domain (per country) | game lines and concept counts; downloaded at run time |
| Lichess chess-openings | CC0 | opening names |
| Lichess and chess.com APIs | their terms and rate limits | your games and the cohort |
| PGN Mentor player archives | copyright notice, no licence text | local analysis of anchor players' games; archives are deleted after sampling; never redistribute |

Notes:

- python-chess is GPL-3.0 and the Python code here imports it as a library. This repository's own code is MIT, which
  is GPL-compatible, but a combined work you *redistribute* that includes python-chess still has to honour the GPL
  (source availability, same licence on the combination). Using the code on your own machine is unaffected. The C++
  engine does not use python-chess.
- If you use Maia weights, respect their licence for anything you publish or host.
- The pretrained and fine-tuned models produced from your own data are not in the repository (`*.pt` is git-ignored).
