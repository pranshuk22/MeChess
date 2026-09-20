"""Your own PDFs (books you own): text layer through pypdf, then the same book reader. A scan without a text layer is reported, not
guessed: it needs OCR (Tesseract, e.g. through ocrmypdf) first. Keep the outputs local and never publish them."""
import json
from pathlib import Path

from . import text as T


def page_texts(path, reader=None):
    """The text of each page of a PDF ('' for a page without a text layer)."""
    if reader is None:
        from pypdf import PdfReader
        reader = PdfReader
    return [(p.extract_text() or "") for p in reader(str(path)).pages]


def has_text_layer(pages, min_chars_per_page=200):
    return sum(len(p) for p in pages) >= min_chars_per_page * max(len(pages), 1)


def run(in_dir, out_dir, *, reader=None, log=print):
    """Read every PDF under `in_dir`: writes `<name>.txt` and `<name>.json` (the analysis) to `out_dir`. Returns {"read", "needs_ocr"}."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stats = {"read": [], "needs_ocr": []}
    for pdf in sorted(Path(in_dir).rglob("*.pdf")):
        pages = page_texts(pdf, reader)
        if not has_text_layer(pages):
            stats["needs_ocr"].append(pdf.name)
            log(f"  {pdf.name}: no text layer ({len(pages)} pages); OCR it first")
            continue
        body = "\n\n".join(pages)
        res = T.analyse_book(body)
        (out / f"{pdf.stem}.txt").write_text(body)
        (out / f"{pdf.stem}.json").write_text(json.dumps({"id": pdf.stem, "pages": len(pages), **res}))
        stats["read"].append(pdf.name)
        log(f"  {pdf.name}: {len(pages)} pages, {len(res['lines'])} lines, {res['notation']}")
    return stats
