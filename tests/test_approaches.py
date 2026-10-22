"""Tests for answer approaches (core/approaches.py)."""

import json
from pathlib import Path

import pytest

from core import approaches as ap
from core.content_pack import load_pack
from core.db import get_conn, init_db

REAL_PACK = Path(__file__).resolve().parent.parent / "data" / "content_pack.json"

# chapter-specific keywords that must appear in that chapter's seeded steps
# (all taken from real slide titles / sections in the book).
CHAPTER_KEYWORDS = {
    "ch01": ["verb", "marks"],
    "ch02": ["head of income", "definition"],
    "ch03": ["12(1)", "Salary"],
    "ch04": ["15", "Property"],
    "ch05": ["75", "disposal"],
    "ch06": ["37(1)", "capital asset"],
    "ch07": ["method", "pre-commencement"],
    "ch08": ["18", "brought-forward losses"],
    "ch09": ["dividend", "other heads"],
    "ch10": ["Second Schedule", "tax credits"],
    "ch11": ["carry", "set off"],
    "ch12": ["taxable income", "rate schedule"],
    "ch13": ["AOP", "members"],
    "ch14": ["grab-bag", "concept"],
}


@pytest.fixture()
def real_conn(tmp_path):
    """Scratch DB loaded with the REAL content pack (skipped if absent)."""
    if not REAL_PACK.is_file():
        pytest.skip("real content pack not present")
    db_path = tmp_path / "real.db"
    c = get_conn(db_path)
    init_db(c)
    load_pack(c, REAL_PACK, is_demo=False)
    yield c
    c.close()


def test_seed_demo_book_generic(conn):
    # conn fixture = sample DEMO pack: generic (parts-driven) workflow.
    out = ap.seed_approaches(conn)
    assert out == {"ch01": out["ch01"]}
    steps = ap.get_steps(conn, out["ch01"])
    assert len(steps) >= 4
    blob = " ".join(s["title"] + " " + s["detail"] for s in steps).lower()
    assert "suggested workflow" in ap.get_approach(conn, "ch01")["intro"].lower()
    assert "requirement" in blob


def test_all_14_chapters_seeded_real(real_conn):
    out = ap.seed_approaches(real_conn)
    assert len(out) == 14
    for cid in [f"ch{i:02d}" for i in range(1, 15)]:
        assert cid in out
        steps = ap.get_steps(real_conn, out[cid])
        assert len(steps) >= 5, cid


def test_steps_reference_real_chapter_content(real_conn):
    ap.seed_approaches(real_conn)
    for cid, keywords in CHAPTER_KEYWORDS.items():
        aid = ap.get_approach(real_conn, cid)["id"]
        blob = " ".join(
            s["title"] + " " + s["detail"]
            for s in ap.get_steps(real_conn, aid)).lower()
        hits = [k for k in keywords if k.lower() in blob]
        assert hits, f"{cid}: no chapter-specific keyword in steps"


def test_steps_start_and_end_with_requirement(real_conn):
    ap.seed_approaches(real_conn)
    for cid in [f"ch{i:02d}" for i in range(1, 15)]:
        steps = ap.get_steps(real_conn, ap.get_approach(real_conn, cid)["id"])
        assert "requirement" in steps[0]["title"].lower()
        assert "requirement" in steps[-1]["title"].lower()


def test_edits_persist_and_are_logged(conn):
    aid = ap.seed_approaches(conn)["ch01"]
    steps = ap.get_steps(conn, aid)
    sid = steps[0]["id"]
    ap.update_step(conn, aid, sid, "title", "Edited title")
    row = conn.execute("SELECT title FROM approach_steps WHERE id=?",
                       (sid,)).fetchone()
    assert row["title"] == "Edited title"
    log = conn.execute(
        "SELECT * FROM approach_edits WHERE step_id=? AND field='title'",
        (sid,)).fetchone()
    assert log is not None and log["new_value"] == "Edited title"


def test_add_delete_step(conn):
    aid = ap.seed_approaches(conn)["ch01"]
    before = len(ap.get_steps(conn, aid))
    sid = ap.add_step(conn, aid, "My extra step", "detail here")
    assert len(ap.get_steps(conn, aid)) == before + 1
    ap.delete_step(conn, aid, sid)
    assert len(ap.get_steps(conn, aid)) == before


def test_checklist_session_roundtrip(conn):
    aid = ap.seed_approaches(conn)["ch01"]
    steps = ap.get_steps(conn, aid)
    sess = ap.start_session(conn, aid, "Q1 attempt")
    assert ap.session_progress(conn, sess) == {"done": 0, "total": len(steps)}
    ap.set_check(conn, sess, steps[0]["id"], True)
    ap.set_check(conn, sess, steps[1]["id"], True)
    assert ap.session_progress(conn, sess) == {"done": 2, "total": len(steps)}
    ap.set_check(conn, sess, steps[0]["id"], False)
    assert ap.session_progress(conn, sess)["done"] == 1
    ap.close_session(conn, sess)
    assert conn.execute(
        "SELECT status FROM approach_sessions WHERE id=?",
        (sess,)).fetchone()["status"] == "done"


def test_seed_idempotent(real_conn):
    first = ap.seed_approaches(real_conn)
    second = ap.seed_approaches(real_conn)
    assert first == second
    n = real_conn.execute("SELECT COUNT(*) c FROM approach_steps").fetchone()["c"]
    assert n == real_conn.execute(
        "SELECT COUNT(*) c FROM approach_steps").fetchone()["c"]
