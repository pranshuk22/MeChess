"""Checks to run FIRST on a Kaggle (or any) machine, before any long job: everything that would otherwise fail hours in.

  python, dependencies   the imports the commands need (and torch / transformers when the NLP step is wanted)
  disk, write access     free space in the output folder and a real write
  network                every remote source answers (HEAD/GET of one small piece)
  gpu                    a GPU is visible when one is required, with its name and memory

Each check returns (name, ok, detail); `run` prints a table and returns True only if every *required* check passed."""
import importlib
import shutil
import sys
import urllib.request
from pathlib import Path

from . import annotated as A
from . import corpora as C
from . import fetch as F
from . import openings as OP

UA = F.UA


def _head(url, timeout=30):
    """(ok, detail) of a HEAD request (falling back to a 1-byte GET when HEAD is refused)."""
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, method=method, headers={**UA, **({"Range": "bytes=0-0"} if method == "GET" else {})})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return True, f"HTTP {r.status}"
        except Exception as e:
            last = str(e)[:60]
    return False, last


def sources_to_check(with_corpora=True):
    urls = {"gutenberg": "https://www.gutenberg.org/cache/epub/33870/pg33870.txt",
            "internet archive": "https://archive.org/download/chessfundamental00capa/chessfundamental00capa_djvu.txt",
            "annotated archive": A.URL, "lichess openings": OP.BASE + "a.tsv"}
    for src, name in A.CSV_FILES.items():
        urls[src] = A.CSV_BASE + name
    if with_corpora:
        for kind, files in C.FILES.items():
            urls[f"chessgpt {kind}"] = C.BASE + files[0]
    return urls


def check_imports(names):
    out = []
    for n in names:
        try:
            mod = importlib.import_module(n)
            out.append((f"import {n}", True, getattr(mod, "__version__", "ok")))
        except Exception as e:
            out.append((f"import {n}", False, str(e)[:70]))
    return out


def run(out_dir, *, need_gpu=False, need_transformers=False, min_free_gb=3.0, network=True, head=_head, model_name=None, log=print):
    """Run the checks; returns True when every required one passed."""
    rows = [("python", sys.version_info >= (3, 9), sys.version.split()[0])]
    rows += check_imports(["numpy", "chess", "yaml", "requests", "torch"] + (["transformers"] if need_transformers else []))
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(out).free / 1e9
    rows.append(("free disk", free >= min_free_gb, f"{free:.1f} GB (need {min_free_gb})"))
    try:
        (out / ".preflight").write_text("ok")
        (out / ".preflight").unlink()
        rows.append(("write access", True, str(out)))
    except OSError as e:
        rows.append(("write access", False, str(e)[:60]))
    try:
        import torch
        has = torch.cuda.is_available()
        detail = (f"{torch.cuda.get_device_name(0)}, {torch.cuda.get_device_properties(0).total_memory / 1e9:.0f} GB" if has
                  else "no CUDA device")
        rows.append(("gpu", has or not need_gpu, detail + ("" if has or not need_gpu else " -- turn on Settings -> Accelerator")))
    except Exception as e:
        rows.append(("gpu", not need_gpu, str(e)[:60]))
    if network:
        for name, url in sources_to_check().items():
            ok, detail = head(url)
            rows.append((f"network: {name}", ok, detail))
    if need_transformers and model_name:
        try:
            from transformers import AutoConfig, AutoTokenizer
            AutoConfig.from_pretrained(model_name)
            AutoTokenizer.from_pretrained(model_name)
            rows.append((f"model {model_name}", True, "config and tokenizer download"))
        except Exception as e:
            rows.append((f"model {model_name}", False, str(e)[:70]))
    width = max(len(r[0]) for r in rows)
    for name, ok, detail in rows:
        log(f"  {'OK  ' if ok else 'FAIL'} {name:{width}s}  {detail}")
    failed = [r[0] for r in rows if not r[1]]
    log("preflight: all required checks passed" if not failed else f"preflight FAILED: {', '.join(failed)}")
    return not failed
