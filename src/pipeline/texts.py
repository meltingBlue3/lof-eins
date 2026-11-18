"""
Local text cache for announcement PDFs (table `pdf_texts`).

公告正文的本地缓存。按 sha256 去重：家族公告复制到多只基金目录下，只提取一次。

Each row keeps the raw pdfplumber text (pages separated by form feed, so the
evidence check in phase C can match against exactly what the model saw), the
tables found by `extract_tables()` as a second view of the "公告基本信息" grid,
and `is_empty` for scans with no text layer -- those are reported, never skipped.
"""

import json
import re
import sqlite3
import statistics
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Callable, Iterable, Optional, Union

import pdfplumber

EXTRACTOR = f"pdfplumber@{pdfplumber.__version__}+fonttol"
PAGE_SEP = "\f"
MIN_CHARS = 30      # fewer non-space characters than this means "no text layer"
MAX_PAGES = 60      # relevant notices are short; longer files are cut and flagged
DEFAULT_TOL = 3.0   # pdfplumber's default x/y tolerance, in points
TOL_PER_PT = 0.4    # tolerance as a share of the page's median font size
MIN_TOL = 0.5


def is_empty_text(text: str) -> bool:
    return len(re.sub(r"\s", "", text or "")) < MIN_CHARS


def page_tolerance(page) -> float:
    """
    x/y tolerance for grouping characters into words and lines on this page.

    pdfplumber's fixed 3pt default is wider than a whole character on pages printed in a
    2-4pt font (some managers put the entire notice, tables included, on one A4 page), so
    neighbouring columns get merged into one-character soup. Scaling with the median font
    size keeps 3pt for ordinary 9pt+ text and tightens it only where the font is small.
    """
    sizes = [c["size"] for c in page.chars]
    if not sizes:
        return DEFAULT_TOL
    return min(DEFAULT_TOL, max(MIN_TOL, TOL_PER_PT * statistics.median(sizes)))


def extract(path: Union[str, Path], max_pages: int = MAX_PAGES) -> dict:
    """Extract text and tables from one PDF. Never raises: failures come back in `error`."""
    try:
        with pdfplumber.open(str(path)) as pdf:
            n = len(pdf.pages)
            pages, tables = [], []
            for i, page in enumerate(pdf.pages[:max_pages]):
                tol = page_tolerance(page)
                pages.append(page.extract_text(x_tolerance=tol, y_tolerance=tol) or "")
                settings = {"text_x_tolerance": tol, "text_y_tolerance": tol}
                for tb in page.extract_tables(table_settings=settings) or []:
                    rows = [[(c or "").strip() for c in row] for row in tb]
                    if any(any(c for c in row) for row in rows):
                        tables.append({"page": i + 1, "rows": rows})
        text = PAGE_SEP.join(pages)
        error = f"truncated at {max_pages} of {n} pages" if n > max_pages else None
        return {"text": text, "tables": tables, "n_pages": n, "is_empty": is_empty_text(text), "error": error}
    except Exception as e:
        return {"text": "", "tables": [], "n_pages": None, "is_empty": True, "error": f"{type(e).__name__}: {e}"}


def _job(args):
    sha, path = args
    return sha, extract(path)


def pending(conn: sqlite3.Connection, labels: Iterable[str], stale: bool = False) -> list:
    """
    (sha256, rel_path) of announcements with a triage label in `labels` and no cached text --
    or, with `stale`, a text cached by another EXTRACTOR version.
    """
    labels = list(labels)
    missing = "t.sha256 IS NULL OR t.extractor != ?" if stale else "t.sha256 IS NULL"
    q = (f"SELECT a.sha256, MIN(a.rel_path) AS rel_path FROM announcements a "
         f"LEFT JOIN pdf_texts t ON t.sha256 = a.sha256 "
         f"WHERE ({missing}) AND a.triage IN ({','.join('?' * len(labels))}) GROUP BY a.sha256")
    return [(r["sha256"], r["rel_path"]) for r in conn.execute(q, ([EXTRACTOR] if stale else []) + labels)]


def build_cache(conn: sqlite3.Connection, root: Union[str, Path], labels=("relevant", "unsure"),
                workers: int = 4, extract_fn: Optional[Callable] = None,
                log: Callable[[str], None] = print, refresh: bool = False) -> dict:
    """
    Extract every pending document and store it. With `refresh`, also re-extract texts cached
    by an older EXTRACTOR (phase C re-extracts a document whose model input changed as a result).
    With `extract_fn` given (tests), runs in-process. Returns counts: done, empty, errors.
    """
    root = Path(root)
    todo = pending(conn, labels, stale=refresh)
    jobs = [(sha, str(root / rel)) for sha, rel in todo]
    counts = {"done": 0, "empty": 0, "errors": 0}
    if extract_fn is not None:
        results = ((sha, extract_fn(p)) for sha, p in jobs)
        pool = None
    else:
        pool = ProcessPoolExecutor(max_workers=workers)
        results = pool.map(_job, jobs, chunksize=8)
    try:
        for i, (sha, r) in enumerate(results, 1):
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO pdf_texts (sha256, extractor, text, tables, n_pages, is_empty, error) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (sha, EXTRACTOR, r["text"], json.dumps(r["tables"], ensure_ascii=False), r["n_pages"],
                     int(r["is_empty"]), r["error"]))
            counts["done"] += 1
            counts["empty"] += int(r["is_empty"])
            counts["errors"] += int(bool(r["error"]) and r["n_pages"] is None)
            if i % 200 == 0:
                log(f"  texts {i}/{len(jobs)}")
    finally:
        if pool is not None:
            pool.shutdown()
    return counts
