"""Tests for ui/syllabus.py — pure logic only (no streamlit at module level).

Streamlit is stubbed in sys.modules before the UI module is imported, so the
real streamlit package is never needed. The tests build their own throwaway
SQLite DB from the schema contract DDL, trying core.db first with a plain
sqlite3 fallback.
"""

import json
import sqlite3
import sys
import types
from pathlib import Path

import pytest

# --- stub streamlit (no `import streamlit` at module level here) ---
if "streamlit" not in sys.modules:
    sys.modules["streamlit"] = types.ModuleType("streamlit")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ui import syllabus  # noqa: E402  (streamlit resolves to the stub above)


DDL = """
CREATE TABLE books(id INTEGER PRIMARY KEY, title, volume, edition, author,
    publisher, source_file, page_count, tax_context_note, solutions_note,
    is_demo, created_at);
CREATE TABLE chapters(id TEXT PRIMARY KEY, book_id, number INT, title,
    page_start INT, page_end INT, parts_json);
CREATE TABLE topics(id TEXT PRIMARY KEY, chapter_id, name, sort_order INT,
    objectives_json, source_ref);
CREATE TABLE items(id INTEGER PRIMARY KEY, kind, topic_id, chapter_id, title,
    body, page_start INT, page_end INT, source_ref, origin, status, extra_json);
CREATE TABLE questions(id TEXT PRIMARY KEY, book_id INT, chapter_id, topic_id,
    number, section, statement, solution, has_solution INT, page_start INT,
    page_end INT, origin, verified_answer INT, answer_note, qtype, difficulty,
    marks, suggested_minutes, rubric_json, numeric_answer, numeric_tolerance,
    rounding, mcq_options_json, mcq_answer, alt_answers_json);
CREATE TABLE import_corrections(id INTEGER PRIMARY KEY, target_kind, target_id,
    field, old_value, new_value, created_at);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);
"""


def _open_test_db():
    """Lazy-import core.db with plain-sqlite3 fallback (repo convention)."""
    try:
        from core import db as _db  # noqa
        if hasattr(_db, "connect"):
            return _db.connect(":memory:")
    except Exception:
        pass
    conn = sqlite3.connect(":memory:")
    return conn


@pytest.fixture
def conn():
    c = _open_test_db()
    c.executescript(DDL)
    c.execute(
        "INSERT INTO books(id, title, volume, edition, is_demo) VALUES "
        "(1, 'SAMPLE: Taxation (DEMO)', 'VOLUME 1', 'Spring 2027', 1)")
    c.execute(
        "INSERT INTO chapters(id, book_id, number, title, page_start, page_end, "
        "parts_json) VALUES ('ch01', 1, 1, 'SAMPLE: SALARY BASICS (DEMO)', 1, 2, ?)",
        (json.dumps(["What is salary", "Allowances"]),))
    c.execute(
        "INSERT INTO chapters(id, book_id, number, title, page_start, page_end, "
        "parts_json) VALUES ('ch02', 1, 2, 'SAMPLE: BUSINESS INCOME (DEMO)', 3, 4, ?)",
        (json.dumps([]),))
    c.commit()
    yield c
    c.close()


def _corrections(c, **kw):
    where = " AND ".join(f"{k} = ?" for k in kw)
    return c.execute(
        f"SELECT target_kind, target_id, field, old_value, new_value "
        f"FROM import_corrections WHERE {where} ORDER BY id",
        tuple(kw.values())).fetchall()


# --- derive topics from chapter parts ---------------------------------------

def test_derive_topics_from_parts_creates_ordered_topics(conn):
    new_ids = syllabus.derive_topics_from_parts(conn, "ch01")
    assert len(new_ids) == 2
    rows = conn.execute(
        "SELECT id, name, sort_order FROM topics WHERE chapter_id = 'ch01' "
        "ORDER BY sort_order").fetchall()
    assert [r[2] for r in rows] == [0, 1]
    assert [r[1] for r in rows] == ["What is salary", "Allowances"]
    assert [r[0] for r in rows] == new_ids


def test_derive_topics_is_idempotent_and_logs_origin(conn):
    syllabus.derive_topics_from_parts(conn, "ch01")
    assert syllabus.derive_topics_from_parts(conn, "ch01") == []  # no dupes
    created = _corrections(conn, target_kind="topic", field="__created__")
    assert len(created) == 2
    origins = _corrections(conn, target_kind="topic", field="origin")
    assert len(origins) == 2
    assert all(r[4] == "import" for r in origins)  # logged as origin import


def test_derive_topics_empty_parts_returns_nothing(conn):
    assert syllabus.derive_topics_from_parts(conn, "ch02") == []
    assert conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0] == 0


# --- rename logs import_corrections ------------------------------------------

def test_rename_topic_logs_old_and_new_values(conn):
    tid = syllabus.create_topic(conn, "ch01", "Old Name")
    assert syllabus.rename_topic(conn, tid, "New Name") is True
    assert conn.execute(
        "SELECT name FROM topics WHERE id = ?", (tid,)).fetchone()[0] == "New Name"
    (kind, target, field, old, new), = _corrections(conn, field="name")
    assert (kind, target, field, old, new) == (
        "topic", tid, "name", "Old Name", "New Name")


def test_rename_chapter_logs_old_and_new_values(conn):
    assert syllabus.rename_chapter(conn, "ch01", "Renamed Chapter") is True
    (kind, target, field, old, new), = _corrections(conn, field="title")
    assert (kind, target, field, old, new) == (
        "chapter", "ch01", "title",
        "SAMPLE: SALARY BASICS (DEMO)", "Renamed Chapter")


def test_rename_to_same_value_is_noop(conn):
    tid = syllabus.create_topic(conn, "ch01", "Same")
    assert syllabus.rename_topic(conn, tid, "Same") is False
    assert _corrections(conn, field="name") == []


# --- move topic ----------------------------------------------------------------

def test_move_topic_updates_chapter_id(conn):
    tid = syllabus.create_topic(conn, "ch01", "Movable")
    assert syllabus.move_topic(conn, tid, "ch02") is True
    assert conn.execute(
        "SELECT chapter_id FROM topics WHERE id = ?", (tid,)).fetchone()[0] == "ch02"
    (kind, target, field, old, new), = _corrections(
        conn, target_id=tid, field="chapter_id")
    assert (old, new) == ("ch01", "ch02")


def test_move_topic_same_chapter_is_noop(conn):
    tid = syllabus.create_topic(conn, "ch01", "Stays")
    assert syllabus.move_topic(conn, tid, "ch01") is False


def test_move_topic_unknown_chapter_raises(conn):
    tid = syllabus.create_topic(conn, "ch01", "Stays")
    with pytest.raises(ValueError):
        syllabus.move_topic(conn, tid, "chXX")


# --- reorder -------------------------------------------------------------------

def test_reorder_topics_updates_sort_order_and_logs(conn):
    ids = [syllabus.create_topic(conn, "ch01", n) for n in ("A", "B", "C")]
    changed = syllabus.reorder_topics(conn, "ch01", [ids[2], ids[0], ids[1]])
    assert changed == 3
    rows = conn.execute(
        "SELECT id FROM topics WHERE chapter_id = 'ch01' ORDER BY sort_order"
    ).fetchall()
    assert [r[0] for r in rows] == [ids[2], ids[0], ids[1]]
    assert len(_corrections(conn, field="sort_order")) == 3


# --- merge ---------------------------------------------------------------------

def test_merge_topics_moves_links_and_logs(conn):
    primary = syllabus.create_topic(conn, "ch01", "Primary")
    sec = syllabus.create_topic(conn, "ch01", "Secondary")
    conn.execute(
        "INSERT INTO items(kind, topic_id, chapter_id, title, origin, status) "
        "VALUES ('definition', ?, 'ch01', 'Term', 'imported', "
        "'auto_detected_unverified')", (sec,))
    conn.execute(
        "INSERT INTO questions(id, book_id, chapter_id, topic_id, number, section, "
        "statement, solution, has_solution, origin) VALUES ('q1', 1, 'ch01', ?, "
        "'1', 'SEC', 'stmt', '', 0, 'imported')", (sec,))
    conn.commit()
    syllabus.merge_topics(conn, primary, [sec])
    assert conn.execute(
        "SELECT COUNT(*) FROM topics WHERE id = ?", (sec,)).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM items WHERE topic_id = ?",
        (primary,)).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM questions WHERE topic_id = ?",
        (primary,)).fetchone()[0] == 1
    (kind, target, field, old, new), = _corrections(conn, field="__merged_into__")
    assert (target, old, new) == (sec, "Secondary", primary)


# --- revision bookmark -----------------------------------------------------------

def test_revision_bookmark_toggle(conn):
    tid = syllabus.create_topic(conn, "ch01", "T")
    assert syllabus.is_revision_bookmarked(conn, tid) is False
    assert syllabus.toggle_revision_bookmark(conn, tid) is True
    assert syllabus.is_revision_bookmarked(conn, tid) is True
    assert syllabus.toggle_revision_bookmark(conn, tid) is False
    assert syllabus.is_revision_bookmarked(conn, tid) is False


# --- syllabus keyword matching ---------------------------------------------------

def _entries():
    return [
        {"kind": "chapter", "id": "ch01",
         "label": "Ch 1: SAMPLE: SALARY BASICS (DEMO)"},
        {"kind": "topic", "id": "ch01-t01", "label": "Allowances (Ch 1)"},
        {"kind": "topic", "id": "ch01-t02", "label": "What is salary (Ch 1)"},
        {"kind": "chapter", "id": "ch02",
         "label": "Ch 2: SAMPLE: BUSINESS INCOME (DEMO)"},
    ]


def test_syllabus_keyword_matching_returns_sane_matches():
    lines = [
        "Computation of salary and allowances",
        "Deductions against business income",
        "xyzzy unrelated line",
    ]
    matches = syllabus.match_syllabus_lines(lines, _entries())
    first = [e["id"] for e, _ in matches["Computation of salary and allowances"]]
    assert "ch01" in first  # salary chapter matched
    assert any(eid.startswith("ch01-t") for eid in first)  # its topics matched
    second = [e["id"] for e, _ in matches["Deductions against business income"]]
    assert "ch02" in second  # business chapter matched
    assert matches["xyzzy unrelated line"] == []  # no spurious match


def test_syllabus_matching_is_deterministic():
    lines = ["salary allowances computation", "business income deductions"]
    a = syllabus.match_syllabus_lines(lines, _entries())
    b = syllabus.match_syllabus_lines(lines, _entries())
    assert a == b


def test_mastery_band_uses_core_mastery_when_present(conn):
    # core/mastery.py exists in the repo: no evidence -> "weak (0%)".
    # If a future checkout lacks core.mastery, mastery_band must still
    # degrade gracefully to "—" instead of raising.
    try:
        from core import mastery  # noqa
        assert syllabus.mastery_band(conn, "ch01-t01") == "weak (0%)"
    except ImportError:
        assert syllabus.mastery_band(conn, "ch01-t01") == "—"
