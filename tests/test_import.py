"""Tests for core/importer.py. No streamlit, no network."""

import json
import os
import sqlite3

import pytest

from core import importer

DDL = """
CREATE TABLE books(id INTEGER PRIMARY KEY, title TEXT, volume TEXT, edition TEXT,
  author TEXT, publisher TEXT, source_file TEXT, page_count INTEGER,
  tax_context_note TEXT, solutions_note TEXT, is_demo INTEGER, created_at TEXT);
CREATE TABLE chapters(id TEXT PRIMARY KEY, book_id INTEGER, number INTEGER,
  title TEXT, page_start INTEGER, page_end INTEGER, parts_json TEXT);
CREATE TABLE topics(id TEXT PRIMARY KEY, chapter_id TEXT, name TEXT,
  sort_order INTEGER, objectives_json TEXT, source_ref TEXT);
CREATE TABLE pages(n INTEGER PRIMARY KEY, book_id INTEGER, chapter_id TEXT,
  has_slides INTEGER, failed INTEGER, text_merged TEXT);
CREATE TABLE import_corrections(id INTEGER PRIMARY KEY, target_kind TEXT,
  target_id TEXT, field TEXT, old_value TEXT, new_value TEXT, created_at TEXT);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);
"""


@pytest.fixture()
def conn(tmp_path):
    db = tmp_path / "test.db"
    c = sqlite3.connect(str(db))
    c.executescript(DDL)
    yield c
    c.close()


def _make_pdf(path, page_texts):
    """Create a synthetic PDF with pymupdf; '' = blank (image-heavy) page."""
    import fitz
    doc = fitz.open()
    for t in page_texts:
        page = doc.new_page()
        if t:
            page.insert_text((72, 72), t)
    doc.save(str(path))
    doc.close()


# --------------------------------------------------------------------------

def test_extract_text_pdf(tmp_path):
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, ["CHAPTER 1\nIntroduction to Tax", "plain body text here"])
    pages = importer.extract_text(str(pdf))
    assert len(pages) == 2
    assert pages[0]["n"] == 1
    assert "CHAPTER 1" in pages[0]["text"]
    assert pages[0]["text_chars"] == len(pages[0]["text"])
    assert pages[1]["text_chars"] > 0


def test_extract_text_txt(tmp_path):
    f = tmp_path / "doc.txt"
    f.write_text("CHAPTER 2\nSalary income", encoding="utf-8")
    pages = importer.extract_text(str(f))
    assert len(pages) == 1 and pages[0]["n"] == 1
    assert "Salary income" in pages[0]["text"]


def test_extract_text_unsupported(tmp_path):
    f = tmp_path / "doc.xlsx"
    f.write_bytes(b"junk")
    with pytest.raises(importer.UnsupportedFormatError):
        importer.extract_text(str(f))


def test_detect_image_heavy_pages(tmp_path):
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, ["enough text on this page to pass the threshold comfortably",
                    ""])  # page 2 is blank
    flagged = importer.detect_image_heavy_pages(str(pdf))
    assert flagged == [2]


def test_ocr_page_missing_engine(tmp_path):
    pytest.importorskip("fitz")
    try:
        import rapidocr_onnxruntime  # noqa: F401
        pytest.skip("rapidocr is installed; cannot test the missing-engine path")
    except ImportError:
        pass
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, ["hello"])
    with pytest.raises(importer.OCRMissingError):
        importer.ocr_page(str(pdf), 1)


def test_suggest_chapters_high_confidence(tmp_path):
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, ["CHAPTER 1\nIntroduction to Tax",
                    "CHAPTER 2\nIncome from Salary",
                    "more salary content"])
    pages = importer.extract_text(str(pdf))
    chs = importer.suggest_chapters(pages)
    assert len(chs) == 2
    assert chs[0]["number"] == 1 and chs[0]["page_start"] == 1
    assert chs[0]["page_end"] == 1 and chs[0]["confidence"] == "high"
    assert chs[1]["number"] == 2 and chs[1]["page_end"] == 3
    assert "Salary" in chs[1]["title"]


def test_suggest_chapters_low_confidence_fallback():
    pages = [{"n": 1, "text": "just some prose\nwith no headings", "text_chars": 30}]
    chs = importer.suggest_chapters(pages)
    assert len(chs) == 1
    assert chs[0]["confidence"] == "low"
    assert chs[0]["page_start"] == 1 and chs[0]["page_end"] == 1


def test_import_document_and_confirm(conn, tmp_path):
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, ["CHAPTER 1\nIntroduction to Tax — scope and charge of income "
                    "tax under the Ordinance", ""])  # page 2 blank → failed
    res = importer.import_document(conn, str(pdf), title="Test Book",
                                   edition="2027", ocr=False)
    assert res["page_count"] == 2
    assert res["failed_pages"] == [2]
    assert res["image_heavy_pages"] == [2]
    book_id = res["book_id"]

    book = conn.execute("SELECT title, is_demo, page_count FROM books WHERE id=?",
                        (book_id,)).fetchone()
    assert book == ("Test Book", 0, 2)
    failed = conn.execute(
        "SELECT n FROM pages WHERE book_id=? AND failed=1", (book_id,)).fetchall()
    assert [r[0] for r in failed] == [2]
    # chapters not yet applied before confirm
    assert conn.execute("SELECT COUNT(*) FROM chapters").fetchone()[0] == 0

    chapter_plan = [{"id": "imp_ch1", "number": 1, "title": "Intro to Tax",
                     "page_start": 1, "page_end": 2}]
    topic_plan = [{"id": "imp_ch1_t0", "chapter_id": "imp_ch1",
                   "name": "What is tax", "sort_order": 0}]
    stats = importer.confirm_import(conn, book_id, chapter_plan,
                                    topic_plan=topic_plan,
                                    page_overrides={2: {"failed": True}})
    assert stats["chapters"] == 1 and stats["topics"] == 1
    assert stats["corrections_logged"] >= 2

    ch = conn.execute(
        "SELECT number, title, page_start, page_end FROM chapters WHERE id='imp_ch1'"
    ).fetchone()
    assert ch == (1, "Intro to Tax", 1, 2)
    t = conn.execute(
        "SELECT name FROM topics WHERE chapter_id='imp_ch1'").fetchone()
    assert t[0] == "What is tax"
    # pages got their chapter_id
    assert conn.execute(
        "SELECT COUNT(*) FROM pages WHERE book_id=? AND chapter_id='imp_ch1'",
        (book_id,)).fetchone()[0] == 2
    # corrections logged with history
    corr = conn.execute(
        "SELECT target_kind, field FROM import_corrections").fetchall()
    kinds = {(r[0], r[1]) for r in corr}
    assert ("chapter", "boundaries_reviewed") in kinds
    assert ("topic", "created_by_student") in kinds


def test_mark_page_text_corrected(conn, tmp_path):
    pdf = tmp_path / "doc.pdf"
    _make_pdf(pdf, [""])
    res = importer.import_document(conn, str(pdf), title="B2")
    book_id = res["book_id"]
    importer.mark_page_text_corrected(conn, book_id, 1, "fixed text", origin="ocr")
    row = conn.execute("SELECT failed, text_merged FROM pages WHERE book_id=? AND n=1",
                       (book_id,)).fetchone()
    assert row[0] == 0 and row[1] == "fixed text"
    logged = conn.execute(
        "SELECT COUNT(*) FROM import_corrections WHERE target_kind='page'").fetchone()[0]
    assert logged == 1


def test_confirm_import_unknown_book(conn):
    with pytest.raises(importer.ImporterError):
        importer.confirm_import(conn, 9999, [])
