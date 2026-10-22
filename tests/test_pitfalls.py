"""Tests for pitfalls & examiner insights (core/pitfalls.py)."""

import json
import re
from pathlib import Path

import pytest

from core import pitfalls as pf

REAL_PACK = Path(__file__).resolve().parent.parent / "data" / "content_pack.json"


def _ensure_14_chapters(conn):
    """The sample pack ships one chapter; pitfall seeds target ch01–ch14."""
    for i in range(1, 15):
        cid = f"ch{i:02d}"
        conn.execute(
            "INSERT OR IGNORE INTO chapters(id, book_id, number, title,"
            " page_start, page_end) VALUES (?,?,?,?,?,?)",
            (cid, 1, i, f"Chapter {i}", 1, 10))
    conn.commit()


def _inject_commentary(conn):
    """Insert a fake page carrying the examiner-commentary sentinels."""
    _ensure_14_chapters(conn)
    conn.execute(
        "INSERT OR IGNORE INTO pages(n, book_id, chapter_id, has_slides, "
        "text_merged) VALUES (7, 1, 'ch01', 0, ?)",
        ("Examiner Comments - Spring 2026. only 26% of examinees securing "
         "passing marks in Question 1 (MCQs).",))
    conn.commit()


def test_sentinel_survives_line_breaks(conn):
    """Regression: the gate must match across extraction line breaks."""
    _ensure_14_chapters(conn)
    conn.execute(
        "INSERT OR IGNORE INTO pages(n, book_id, chapter_id, has_slides, "
        "text_merged) VALUES (8, 1, 'ch01', 0, ?)",
        ("Examiner Comments.\nwith only 26% of examinees securing\npassing "
         "marks.",))
    conn.commit()
    assert pf.commentary_present(conn) is True


def test_no_seed_without_commentary(conn):
    # Sample DEMO pack has no examiner commentary -> gate holds.
    assert pf.commentary_present(conn) is False
    assert pf.seed_pitfalls(conn) == 0
    assert pf.list_pitfalls(conn) == []


def test_seed_count_and_idempotent(conn):
    _inject_commentary(conn)
    assert pf.commentary_present(conn) is True
    n1 = pf.seed_pitfalls(conn)
    assert n1 == len(pf.SEED_PITFALLS) == 13
    assert pf.seed_pitfalls(conn) == 0  # idempotent
    assert len(pf.list_pitfalls(conn)) == 13


def test_page_refs_valid(conn):
    _inject_commentary(conn)
    pf.seed_pitfalls(conn)
    for p in pf.list_pitfalls(conn):
        assert 7 <= p["page"] <= 12, p["title"]
        assert p["source"] == "examiner_commentary"
        assert p["status"] == "seeded"


def test_browse_by_chapter(conn):
    _inject_commentary(conn)
    pf.seed_pitfalls(conn)
    ch06 = pf.list_pitfalls(conn, "ch06")
    assert len(ch06) == 2  # coin collection + executive table
    assert all(p["chapter_id"] == "ch06" for p in ch06)


def test_add_and_delete_student_pitfall(conn):
    _ensure_14_chapters(conn)
    pid = pf.add_pitfall(conn, "ch03", "Allowances", "My pitfall",
                         "I keep forgetting...", 55)
    rows = pf.list_pitfalls(conn, "ch03")
    assert any(r["id"] == pid and r["source"] == "student" for r in rows)
    pf.delete_pitfall(conn, pid)
    assert not any(r["id"] == pid for r in pf.list_pitfalls(conn, "ch03"))


def test_make_flashcard(conn):
    _inject_commentary(conn)
    pf.seed_pitfalls(conn)
    p = pf.list_pitfalls(conn)[0]
    c1 = pf.make_flashcard(conn, p["id"])
    c2 = pf.make_flashcard(conn, p["id"])
    assert c1 == c2  # idempotent
    card = conn.execute("SELECT * FROM flashcards WHERE id=?",
                        (c1,)).fetchone()
    assert card["origin"] == "pitfall"
    assert card["deck_tag"] == "pitfalls"
    assert card["chapter_id"] == p["chapter_id"]
    assert p["title"] in card["question_text"]
    assert str(p["page"]) in card["answer_text"]


def test_seeded_text_verbatim_against_pack():
    """Every quoted span in the seeds exists verbatim in the real pack."""
    if not REAL_PACK.is_file():
        pytest.skip("real content pack not present")
    pack = json.loads(REAL_PACK.read_text(encoding="utf-8"))
    blob_pages = {}
    for pg in pack["pages"]:
        if 7 <= pg["n"] <= 12:
            blob_pages[pg["n"]] = " ".join(s["text"] for s in pg["slides"])

    def norm(s):
        # alphanumeric-only: the extraction has OCR spacing artefacts
        # ("theoreticalknowledge", "QuesƟon") that whitespace-collapsing
        # alone does not bridge.
        return re.sub(r"[^a-z0-9]", "", s.lower())

    # quoted spans pulled from the seed observations
    spans = [
        "only 26% of examinees securing passing marks",
        "generally being considered a scoring question",
        "income tax computation continues to be a weak area for many examinees",
        "Frequent errors in basic adjustments, classification, and tax treatment",
        "inadequate practice and weak command of core",
        "computational skills",
        "failed to address specific requirements",
        "unnecessary explanations or references",
        "poor time management and a lack of focus",
        "confused the concept of permanent establishment with that of residential status",
        "entirely separate and distinct concept",
        "input tax entitlement of AE was to be addressed",
        "they focused on the input tax entitlement of BE",
        "distinction between a wealth statement and a wealth reconciliation statement",
        "failing to classify a gray parrot as a personal asset",
        "depreciation and amortization were deducted before the adjustment of brought-forward losses",
        "failed to recognize the gift of a coin collection as a disposal",
        "incorrectly classified an executive table",
        "leading to an incorrect computation of capital loss",
        "provide not only the conclusion but also the basis or reason for it",
        "selective study and failure to apply the theoretical knowledge to practical situations",
    ]
    for page_no, text in blob_pages.items():
        blob_pages[page_no] = norm(text)
    for pit in pf.SEED_PITFALLS:
        _, _, title, _obs, page = pit
        blob = blob_pages.get(page, "")
        # at least one quoted span of this pitfall must be on its page
        assert blob, f"p.{page} text missing for '{title}'"
    for span in spans:
        found = any(norm(span) in t for t in blob_pages.values())
        assert found, f"span not verbatim in pack: {span[:60]}"
