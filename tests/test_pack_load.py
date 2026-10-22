"""Foundation tests: content-pack import against data/sample_pack.json."""

import json

import pytest

from core.content_pack import get_active_book, load_pack
from core.db import get_conn, init_db, integrity_check, rebuild_fts


def _count(conn, table, where="", params=()):
    row = conn.execute(f"SELECT COUNT(*) AS c FROM {table} {where}", params).fetchone()
    return row["c"]


def test_pack_loads(conn):
    book = get_active_book(conn)
    assert book is not None
    assert book["is_demo"] == 1
    assert "SAMPLE" in book["title"]


def test_pack_format_validated(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"pack_format": 99, "book": {"source_file": "x"}}))
    c = get_conn(tmp_path / "v.db")
    init_db(c)
    with pytest.raises(ValueError, match="pack_format"):
        load_pack(c, bad)
    c.close()


def test_chapter_count_matches_pack(conn, pack_path):
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    assert _count(conn, "chapters") == len(pack["chapters"])
    assert _count(conn, "pages") == len(pack["pages"])
    n_slides = sum(len(p.get("slides", [])) for p in pack["pages"])
    assert _count(conn, "slides") == n_slides
    assert _count(conn, "questions") == len(pack["questions"])
    # definitions land in items(kind='definition')
    assert _count(conn, "items", "WHERE kind='definition'") == len(pack["definitions"])
    # slides land in items(kind='note')
    assert _count(conn, "items", "WHERE kind='note'") == n_slides


def test_page_traceability(conn, pack_path):
    """question → page_start/page_end stored exactly as the pack gives."""
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    for q in pack["questions"]:
        row = conn.execute(
            "SELECT page_start, page_end, qtype FROM questions WHERE id=?",
            (q["id"],),
        ).fetchone()
        assert row is not None
        assert row["page_start"] == q["page_start"]
        assert row["page_end"] == q["page_end"]
        assert row["qtype"] == q["question_type"]
    for d in pack["definitions"]:
        row = conn.execute(
            "SELECT page_start, page_end, source_ref FROM items "
            "WHERE kind='definition' AND title=?",
            (d["term"],),
        ).fetchone()
        assert row is not None
        assert row["page_start"] == d["page"]
        assert row["page_end"] == d["page"]
        assert row["source_ref"] == d["section_ref"]


def test_reload_is_idempotent(conn, pack_path):
    before = {t: _count(conn, t) for t in
              ("books", "chapters", "topics", "pages", "slides", "items",
               "questions", "question_variants", "tax_rules", "flashcards")}
    load_pack(conn, pack_path, is_demo=True)
    after = {t: _count(conn, t) for t in before}
    assert before == after
    # and the active book is still the demo book
    book = get_active_book(conn)
    assert book is not None and book["is_demo"] == 1


def test_student_data_survives_reload(conn, pack_path):
    """Student-authored rows are preserved across a pack re-import."""
    qid = conn.execute("SELECT id FROM questions LIMIT 1").fetchone()["id"]
    conn.execute(
        "INSERT INTO questions(id, book_id, chapter_id, topic_id, number, section,"
        " statement, solution, has_solution, origin, qtype)"
        " VALUES ('student-q1', 1, NULL, NULL, 'S1', 'MINE', 'my question', '',"
        " 0, 'student', 'short')"
    )
    conn.execute(
        "INSERT INTO notes(target_kind, target_id, body, created_at, updated_at)"
        " VALUES ('question', ?, 'my note', 't', 't')",
        (qid,),
    )
    conn.commit()
    load_pack(conn, pack_path, is_demo=True)
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM questions WHERE id='student-q1'"
    ).fetchone()["c"] == 1
    assert conn.execute(
        "SELECT COUNT(*) AS c FROM notes WHERE target_id=?", (qid,)
    ).fetchone()["c"] == 1


def test_integrity_check_passes(conn):
    assert integrity_check(conn) is True


def test_wal_mode(conn):
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


def test_fts_rebuild_indexes_content(conn):
    n = rebuild_fts(conn)
    assert n > 0
    hits = conn.execute(
        "SELECT kind, ref_id FROM fts_content WHERE fts_content MATCH 'salary'"
    ).fetchall()
    assert len(hits) > 0
    kinds = {h["kind"] for h in hits}
    assert kinds & {"slide", "question", "item"}


def test_migrations_row(conn):
    row = conn.execute(
        "SELECT MAX(schema_version) AS v FROM migrations"
    ).fetchone()
    assert row["v"] >= 1
