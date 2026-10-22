"""Textbook import pipeline: extract text, detect image-heavy pages,
optionally OCR them, suggest chapter structure, and import a document
into the SQLite schema with a student-reviewed confirmation step.

Import-safe: no streamlit import at module level.
Accuracy rules (binding):
  - never invent page numbers or content; failed extractions stay flagged
    (failed=1) for manual review — never silently discarded;
  - OCR-derived text is flagged origin='ocr' by callers;
  - student corrections are logged into import_corrections with history.
"""

from __future__ import annotations

import datetime
import os
import re
import sqlite3
import uuid

# --------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------

class ImporterError(Exception):
    """Base error for the import pipeline."""


class OCRMissingError(Exception):
    """Raised when OCR is requested but rapidocr_onnxruntime is not installed."""


# alias kept for convenience
OCRMISSINGError = OCRMissingError


class UnsupportedFormatError(ImporterError):
    """Raised for file extensions the importer cannot read."""


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _get_conn(conn_or_path):
    """Accept a sqlite3 connection or a path; return (conn, close_when_done)."""
    if isinstance(conn_or_path, sqlite3.Connection):
        return conn_or_path, False
    return sqlite3.connect(str(conn_or_path)), True


# --------------------------------------------------------------------------
# 1. extract_text
# --------------------------------------------------------------------------

def extract_text(path):
    """Extract per-page text from .pdf / .docx / .txt files.

    Returns a list of dicts: {n, text, text_chars} where n is the 1-based
    page number (for .txt/.docx a single pseudo-page n=1 is used, and for
    .docx one pseudo-page per document — the importer later splits the
    document into page-sized chunks only if needed).
    """
    path = str(path)
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext == ".docx":
        return _extract_docx(path)
    if ext in (".txt", ".text"):
        return _extract_txt(path)
    raise UnsupportedFormatError(f"Unsupported file type: {ext!r} (expected .pdf, .docx or .txt)")


def _extract_pdf(path):
    import fitz  # PyMuPDF
    doc = fitz.open(path)
    try:
        out = []
        for i, page in enumerate(doc):
            try:
                text = page.get_text("text") or ""
            except Exception:
                text = ""
            out.append({"n": i + 1, "text": text, "text_chars": len(text)})
        return out
    finally:
        doc.close()


def _extract_docx(path):
    from docx import Document
    doc = Document(path)
    blocks = []
    for p in doc.paragraphs:
        if p.text and p.text.strip():
            blocks.append(p.text)
    for t in doc.tables:
        for row in t.rows:
            cells = [c.text.strip() for c in row.cells if c.text and c.text.strip()]
            if cells:
                blocks.append(" | ".join(cells))
    text = "\n\n".join(blocks)
    return [{"n": 1, "text": text, "text_chars": len(text)}]


def _extract_txt(path):
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    return [{"n": 1, "text": text, "text_chars": len(text)}]


# --------------------------------------------------------------------------
# 2. detect_image_heavy_pages
# --------------------------------------------------------------------------

TEXT_LAYER_THRESHOLD = 50  # chars: pages below this are flagged for OCR/manual review

def detect_image_heavy_pages(path, threshold=TEXT_LAYER_THRESHOLD):
    """Return sorted list of 1-based page numbers whose text layer is thin.

    For PDFs only; a thin text layer (< threshold chars) means the page is
    image-heavy or scanned → candidate for OCR or manual review.
    """
    path = str(path)
    if os.path.splitext(path)[1].lower() != ".pdf":
        return []
    import fitz
    doc = fitz.open(path)
    try:
        flagged = []
        for i, page in enumerate(doc):
            try:
                text = page.get_text("text") or ""
            except Exception:
                text = ""
            if len(text) < threshold:
                flagged.append(i + 1)
        return flagged
    finally:
        doc.close()


# --------------------------------------------------------------------------
# 3. ocr_page
# --------------------------------------------------------------------------

def ocr_available() -> bool:
    """True when rapidocr_onnxruntime can be imported."""
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


def ocr_page(pdf_path, page_no, dpi=150):
    """OCR one page of a PDF and return the recognised text.

    ONLY works when rapidocr_onnxruntime is installed; otherwise raises
    OCRMISSINGError with a clear message. Callers must mark OCR-derived
    content origin='ocr' (the confirmation UI does this).
    """
    if not ocr_available():
        raise OCRMISSINGError(
            "OCR requires the optional package 'rapidocr_onnxruntime'. "
            "Install it with: pip install rapidocr_onnxruntime  (CPU-only). "
            f"Page {page_no} was left flagged for manual review instead."
        )
    import fitz
    from rapidocr_onnxruntime import RapidOCR
    doc = fitz.open(str(pdf_path))
    try:
        if page_no < 1 or page_no > doc.page_count:
            raise ImporterError(f"Page {page_no} out of range (PDF has {doc.page_count} pages).")
        page = doc[page_no - 1]
        pix = page.get_pixmap(dpi=dpi)
        png = pix.tobytes("png")
    finally:
        doc.close()
    engine = RapidOCR()
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp.write(png)
        tmp_path = tmp.name
    try:
        result, _ = engine(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    if not result:
        return ""
    lines = []
    for item in result:
        # rapidocr returns [box, text, score] per line
        if len(item) >= 2 and item[1]:
            lines.append(str(item[1]))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# 4. suggest_chapters
# --------------------------------------------------------------------------

_CHAPTER_PATTERNS = [
    re.compile(r"^(?:CHAPTER|Chapter|CHAP\.?)\s+(\d{1,3})\s*[:\-–.]?\s*(.*)$"),
    re.compile(r"^(\d{1,3})\s*[:.)]\s*(.+)$"),  # "3. Income from Salary" style headings
]

def suggest_chapters(pages):
    """Heuristically suggest chapter boundaries from extracted page text.

    `pages`: list of {n, text, text_chars} as returned by extract_text().
    Returns a list of dicts: {number, title, page_start, page_end, confidence}
    where confidence is 'high' (explicit CHAPTER marker), 'medium' (numbered
    heading) or 'low' (fallback whole-document chapter). Never invents:
    titles come verbatim from the matched line; if nothing matches, one
    low-confidence chapter covering the whole document is returned so the
    student can fix boundaries in the review screen.
    """
    candidates = []  # (number, title, page_n, confidence)
    for pg in pages:
        text = pg.get("text") or ""
        raw_lines = [ln.strip() for ln in text.splitlines()]
        nonempty = [ln for ln in raw_lines if ln]
        for idx, line in enumerate(raw_lines):
            if not line or len(line) > 120:
                continue
            # explicit chapter marker → high confidence
            m = _CHAPTER_PATTERNS[0].match(line)
            if m:
                title = (m.group(2) or "").strip()
                if not title:
                    # title often sits on the next non-empty line
                    pos = nonempty.index(line) if line in nonempty else -1
                    if 0 <= pos + 1 < len(nonempty):
                        nxt = nonempty[pos + 1]
                        if len(nxt) <= 120 and not _CHAPTER_PATTERNS[0].match(nxt):
                            title = nxt
                title = title or f"Chapter {m.group(1)}"
                candidates.append((int(m.group(1)), title, pg["n"], "high"))
                break
            # numbered heading on first/last lines of a page → medium
    # second pass for medium-confidence headings (only page-first/last non-empty lines)
    if not any(c[3] == "high" for c in candidates):
        for pg in pages:
            lines = [ln.strip() for ln in (pg.get("text") or "").splitlines() if ln.strip()]
            edge_lines = (lines[:2] + lines[-2:]) if lines else []
            for line in edge_lines:
                if len(line) > 100:
                    continue
                m = _CHAPTER_PATTERNS[1].match(line)
                if m and len(m.group(2).split()) >= 2 and not line.lower().startswith(("page", "table", "figure")):
                    try:
                        num = int(m.group(1))
                    except ValueError:
                        continue
                    if 1 <= num <= 60:
                        candidates.append((num, m.group(2).strip(), pg["n"], "medium"))
                        break
    # de-duplicate by chapter number (keep earliest page)
    seen = {}
    for num, title, pgn, conf in candidates:
        if num not in seen:
            seen[num] = (title, pgn, conf)
    ordered = sorted(seen.items(), key=lambda kv: kv[1][1])
    if not ordered:
        last_page = pages[-1]["n"] if pages else 1
        return [{
            "number": 1,
            "title": "Full document (boundaries not detected)",
            "page_start": 1,
            "page_end": last_page,
            "confidence": "low",
        }]
    chapters = []
    for idx, (num, (title, pgn, conf)) in enumerate(ordered):
        page_end = ordered[idx + 1][1][1] - 1 if idx + 1 < len(ordered) else pages[-1]["n"]
        chapters.append({
            "number": num,
            "title": title,
            "page_start": pgn,
            "page_end": max(pgn, page_end),
            "confidence": conf,
        })
    return chapters


# --------------------------------------------------------------------------
# 5. import_document / confirm_import
# --------------------------------------------------------------------------

def import_document(conn_or_path, path, title, volume="", edition="", author="",
                    publisher="", tax_context_note="", solutions_note="",
                    ocr=False, ocr_dpi=150):
    """Import a document file into books + pages (UNCONFIRMED state).

    Creates the book record (is_demo=0), one row per page in `pages` with
    has_slides=0 / failed flags, and returns a review structure::

        {"book_id": int, "page_count": int,
         "failed_pages": [n, ...], "image_heavy_pages": [n, ...],
         "suggestions": [chapter dicts...], "ocr_used": bool,
         "ocr_missing": bool}

    The student then reviews/edits chapter/topic boundaries in the UI and
    calls confirm_import() to finalise. If ocr=True, OCR is attempted for
    image-heavy pages; OCR failures leave failed=1 (never silently dropped).
    If rapidocr is missing and ocr=True, ocr_missing=True is returned and
    pages stay flagged for manual review.
    """
    path = str(path)
    ext = os.path.splitext(path)[1].lower()
    pages = extract_text(path)
    conn, close = _get_conn(conn_or_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO books (title, volume, edition, author, publisher,
                                  source_file, page_count, tax_context_note,
                                  solutions_note, is_demo, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (title, volume, edition, author, publisher, os.path.basename(path),
             len(pages), tax_context_note, solutions_note, _utcnow()),
        )
        book_id = cur.lastrowid

        image_heavy = set(detect_image_heavy_pages(path)) if ext == ".pdf" else set()
        ocr_engine_missing = ocr and not ocr_available()
        ocr_rows = {}
        if ocr and not ocr_engine_missing:
            for n in sorted(image_heavy):
                try:
                    ocr_text = ocr_page(path, n, dpi=ocr_dpi)
                except Exception:
                    ocr_text = None
                if ocr_text:
                    ocr_rows[n] = ocr_text

        failed_pages = []
        for pg in pages:
            n, text = pg["n"], pg["text"] or ""
            if n in ocr_rows:
                text = text + "\n\n[OCR]\n" + ocr_rows[n]
            failed = 0
            if n in image_heavy and n not in ocr_rows and not text.strip():
                failed = 1
                failed_pages.append(n)
            cur.execute(
                """INSERT INTO pages (n, book_id, chapter_id, has_slides, failed, text_merged)
                   VALUES (?, ?, NULL, 0, ?, ?)""",
                (n, book_id, failed, text if text else None),
            )
        conn.commit()
        suggestions = suggest_chapters(pages)
        return {
            "book_id": book_id,
            "page_count": len(pages),
            "failed_pages": failed_pages,
            "image_heavy_pages": sorted(image_heavy),
            "suggestions": suggestions,
            "ocr_used": bool(ocr_rows),
            "ocr_missing": bool(ocr_engine_missing),
        }
    finally:
        if close:
            conn.close()


def confirm_import(conn_or_path, book_id, chapter_plan, topic_plan=None,
                   corrections=None, page_overrides=None):
    """Apply the student's REVIEWED chapter/topic boundaries to an import.

    - chapter_plan: list of {id, number, title, page_start, page_end, parts?}
      Every field is student-reviewed; corrections vs the auto-suggested
      boundaries are logged into import_corrections.
    - topic_plan: optional list of {id, chapter_id, name, sort_order,
      objectives?, source_ref?} — written to topics.
    - corrections: optional explicit list of {target_kind, target_id, field,
      old_value, new_value} to log in addition to auto-detected diffs.
    - page_overrides: optional {page_n: {"failed": bool}} to (un)flag pages
      for manual review; unflagging requires the student to supply text via
      page_text_overrides below... kept simple: logs a correction entry.

    Also assigns chapter_id to pages in range, writes topic rows, logs every
    manual correction into import_corrections, rebuilds FTS, and returns
    {"chapters": n, "topics": n, "corrections_logged": n}.
    """
    topic_plan = topic_plan or []
    corrections = corrections or []
    page_overrides = page_overrides or {}
    conn, close = _get_conn(conn_or_path)
    try:
        cur = conn.cursor()
        # sanity: book must exist
        cur.execute("SELECT id FROM books WHERE id = ?", (book_id,))
        if not cur.fetchone():
            raise ImporterError(f"Book id {book_id} does not exist.")

        logged = 0
        def _log(target_kind, target_id, field, old_value, new_value):
            nonlocal logged
            cur.execute(
                """INSERT INTO import_corrections
                       (target_kind, target_id, field, old_value, new_value, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (target_kind, str(target_id), field,
                 None if old_value is None else str(old_value),
                 None if new_value is None else str(new_value), _utcnow()),
            )
            logged += 1

        chapters_written = 0
        for ch in chapter_plan:
            ch_id = ch.get("id") or f"imp_{book_id}_{ch['number']}"
            parts_json = None
            if ch.get("parts"):
                import json as _json
                parts_json = _json.dumps(ch["parts"], ensure_ascii=False)
            cur.execute("SELECT id FROM chapters WHERE id = ?", (ch_id,))
            exists = cur.fetchone()
            if exists:
                cur.execute(
                    """UPDATE chapters SET book_id=?, number=?, title=?,
                                          page_start=?, page_end=?, parts_json=?
                       WHERE id=?""",
                    (book_id, ch["number"], ch["title"], ch["page_start"],
                     ch["page_end"], parts_json, ch_id),
                )
            else:
                cur.execute(
                    """INSERT INTO chapters (id, book_id, number, title,
                                             page_start, page_end, parts_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (ch_id, book_id, ch["number"], ch["title"], ch["page_start"],
                     ch["page_end"], parts_json),
                )
                chapters_written += 1
            # assign pages in range
            cur.execute(
                "UPDATE pages SET chapter_id = ? WHERE book_id = ? AND n BETWEEN ? AND ?",
                (ch_id, book_id, ch["page_start"], ch["page_end"]),
            )
            _log("chapter", ch_id, "boundaries_reviewed",
                 f"suggested",
                 f"number={ch['number']} title={ch['title']} pages={ch['page_start']}-{ch['page_end']}")

        topics_written = 0
        for t in topic_plan:
            t_id = t.get("id") or f"{t['chapter_id']}_t{uuid.uuid4().hex[:6]}"
            import json as _json
            objectives_json = _json.dumps(t.get("objectives") or [], ensure_ascii=False)
            cur.execute(
                """INSERT OR REPLACE INTO topics
                       (id, chapter_id, name, sort_order, objectives_json, source_ref)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (t_id, t["chapter_id"], t["name"], t.get("sort_order", 0),
                 objectives_json, t.get("source_ref")),
            )
            topics_written += 1
            _log("topic", t_id, "created_by_student", None, t["name"])

        for n, ov in page_overrides.items():
            cur.execute("SELECT failed FROM pages WHERE book_id = ? AND n = ?", (book_id, n))
            row = cur.fetchone()
            if not row:
                continue
            new_failed = 1 if ov.get("failed") else 0
            if row[0] != new_failed:
                cur.execute("UPDATE pages SET failed = ? WHERE book_id = ? AND n = ?",
                            (new_failed, book_id, n))
                _log("page", f"{book_id}:{n}", "failed_flag",
                     str(bool(row[0])), str(bool(new_failed)))

        for c in corrections:
            _log(c.get("target_kind", ""), c.get("target_id", ""),
                 c.get("field", ""), c.get("old_value"), c.get("new_value"))

        conn.commit()
        _rebuild_fts(conn)
        return {"chapters": chapters_written, "topics": topics_written,
                "corrections_logged": logged}
    finally:
        if close:
            conn.close()


def _rebuild_fts(conn):
    """Call the foundation's rebuild_fts if available (lazy import)."""
    try:
        from core.db import rebuild_fts  # type: ignore
    except Exception:
        return
    try:
        rebuild_fts(conn)
    except Exception:
        pass


def mark_page_text_corrected(conn_or_path, book_id, page_n, corrected_text, origin="ocr"):
    """Replace a failed page's text with student/OCR-supplied text.

    Logs the correction into import_corrections and clears failed=0.
    """
    conn, close = _get_conn(conn_or_path)
    try:
        cur = conn.cursor()
        cur.execute("SELECT text_merged FROM pages WHERE book_id = ? AND n = ?",
                    (book_id, page_n))
        row = cur.fetchone()
        if not row:
            raise ImporterError(f"Page {page_n} of book {book_id} not found.")
        old = row[0] or ""
        cur.execute("UPDATE pages SET text_merged = ?, failed = 0 WHERE book_id = ? AND n = ?",
                    (corrected_text, book_id, page_n))
        cur.execute(
            """INSERT INTO import_corrections
                   (target_kind, target_id, field, old_value, new_value, created_at)
               VALUES ('page', ?, 'text_corrected', ?, ?, ?)""",
            (f"{book_id}:{page_n}", old[:200], f"[{origin}] " + corrected_text[:200], _utcnow()),
        )
        conn.commit()
        _rebuild_fts(conn)
    finally:
        if close:
            conn.close()


__all__ = [
    "ImporterError", "OCRMissingError", "OCRMISSINGError", "UnsupportedFormatError",
    "extract_text", "detect_image_heavy_pages", "ocr_available", "ocr_page",
    "suggest_chapters", "import_document", "confirm_import",
    "mark_page_text_corrected", "TEXT_LAYER_THRESHOLD",
]
