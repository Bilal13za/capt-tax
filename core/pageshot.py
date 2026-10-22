"""Page rendering ("View source page"): render a PDF page to PNG bytes
with a disk cache under data/pagecache/.

Import-safe: no streamlit import at module level.
"""

from __future__ import annotations

import hashlib
import os

DEFAULT_DPI = 110


def _cache_key(pdf_path, page_no, dpi) -> str:
    ident = f"{os.path.abspath(str(pdf_path))}|{page_no}|{dpi}"
    return hashlib.sha256(ident.encode("utf-8")).hexdigest() + ".png"


def _resolve_cache_dir(cache_dir) -> str:
    if cache_dir:
        d = str(cache_dir)
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        d = os.path.join(os.path.dirname(here), "data", "pagecache")
    os.makedirs(d, exist_ok=True)
    return d


def page_exists(pdf_path, page_no) -> bool:
    """True when pdf_path exists and has at least page_no pages."""
    if not os.path.isfile(str(pdf_path)):
        return False
    import fitz
    doc = fitz.open(str(pdf_path))
    try:
        return 1 <= int(page_no) <= doc.page_count
    finally:
        doc.close()


def render_page(pdf_path, page_no, dpi=110, cache_dir=None) -> bytes:
    """Render page_no (1-based) of a PDF to PNG bytes.

    Results are disk-cached in data/pagecache/ (keyed by absolute path,
    page number and dpi) so repeated views are instant. Raises
    FileNotFoundError with a clear message when the PDF is missing and
    ValueError when the page number is out of range.
    """
    pdf_path = str(pdf_path)
    if not os.path.isfile(pdf_path):
        raise FileNotFoundError(
            f"Source PDF not found: {pdf_path}. "
            "The book file may have been moved or renamed; re-link it in the Library."
        )
    page_no = int(page_no)
    cache = _resolve_cache_dir(cache_dir)
    key = _cache_key(pdf_path, page_no, dpi)
    cached = os.path.join(cache, key)
    if os.path.isfile(cached):
        with open(cached, "rb") as fh:
            return fh.read()
    import fitz
    doc = fitz.open(pdf_path)
    try:
        if page_no < 1 or page_no > doc.page_count:
            raise ValueError(f"Page {page_no} out of range (PDF has {doc.page_count} pages).")
        pix = doc[page_no - 1].get_pixmap(dpi=int(dpi))
        png = pix.tobytes("png")
    finally:
        doc.close()
    # write cache atomically-ish; failures to cache must not fail the render
    try:
        tmp = cached + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(png)
        os.replace(tmp, cached)
    except OSError:
        pass
    return bytes(png)


def clear_cache(cache_dir=None, max_age_days=None):
    """Delete cached page renders (all, or older than max_age_days)."""
    import time
    cache = _resolve_cache_dir(cache_dir)
    now = time.time()
    removed = 0
    for name in os.listdir(cache):
        p = os.path.join(cache, name)
        if not os.path.isfile(p):
            continue
        if max_age_days is not None and now - os.path.getmtime(p) < max_age_days * 86400:
            continue
        try:
            os.unlink(p)
            removed += 1
        except OSError:
            pass
    return removed


__all__ = ["render_page", "page_exists", "clear_cache", "DEFAULT_DPI"]
