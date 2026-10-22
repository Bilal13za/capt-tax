"""Tests for core/search.py. No streamlit, no network.

Loads data/sample_pack.json where usable; otherwise inserts minimal rows
directly into the FTS5 table (core.content_pack may not exist yet).
"""

import json
import os
import sqlite3

import pytest

from core import search as search_core

FTS_DDL = "CREATE VIRTUAL TABLE fts_content USING fts5(kind, ref_id, title, body, chapter_id, topic_id);"

PACK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "sample_pack.json")


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.execute(FTS_DDL)
    yield c
    c.close()


def _load_pack_via_content_pack(c):
    """Try the real loader; return True when it worked."""
    try:
        from core import content_pack as cp  # type: ignore
        load = getattr(cp, "load_pack", None)
        if load is None:
            return False
        load(c, PACK)
        return True
    except Exception:
        return False


def _load_minimal_rows(c):
    """Fallback: insert representative rows directly (demo-flavoured text)."""
    rows = [
        ("definition", "d0001", "Salary (demo)",
         "Salary means any amount received by an employee from any employment. [Sec. 12(2)]",
         "ch01", None),
        ("slide", "s0001", "What is Salary? [Sec. 12(2)] (DEMO)",
         "Employee means any individual engaged in employment.",
         "ch01", None),
        ("question", "q0001", "Practice Q1 (DEMO)",
         "Salary is defined in which section of the Income Tax Ordinance, 2001?",
         "ch01", None),
        ("definition", "d0002", "Business income (demo)",
         "Profits and gains of business include income from trade and manufacture.",
         "ch02", None),
    ]
    c.executemany(
        "INSERT INTO fts_content (kind, ref_id, title, body, chapter_id, topic_id)"
        " VALUES (?, ?, ?, ?, ?, ?)", rows)
    c.commit()


@pytest.fixture()
def seeded(conn):
    if not _load_pack_via_content_pack(conn):
        _load_minimal_rows(conn)
    return conn


def test_search_basic(seeded):
    rows = search_core.search(seeded, "salary")
    assert rows, "expected results for 'salary'"
    assert any(r["ref_id"] == "d0001" for r in rows)
    r0 = rows[0]
    assert set(r0) >= {"kind", "ref_id", "title", "snippet", "chapter_id",
                       "topic_id", "rank"}


def test_search_snippet_highlight(seeded):
    rows = search_core.search(seeded, "salary")
    assert any("<mark>" in r["snippet"].lower() or "<mark>" in r["snippet"]
               for r in rows), "snippet should highlight matches"


def test_search_chapter_filter(seeded):
    rows = search_core.search(seeded, "salary", chapter_id="ch01")
    assert rows
    assert all(r["chapter_id"] == "ch01" for r in rows)
    assert search_core.search(seeded, "salary", chapter_id="ch02") == []


def test_search_kind_filter(seeded):
    rows = search_core.search(seeded, "salary", kinds=["definition"])
    assert rows
    assert all(r["kind"] == "definition" for r in rows)


def test_search_topic_filter(seeded):
    # no rows carry a topic_id in the fixture → filtered search is empty
    assert search_core.search(seeded, "salary", topic_id="t1") == []


def test_search_empty_query(seeded):
    assert search_core.search(seeded, "") == []
    assert search_core.search(seeded, "   ") == []


def test_search_no_match(seeded):
    assert search_core.search(seeded, "xyznonexistentword") == []


def test_search_limit(seeded):
    rows = search_core.search(seeded, "salary", limit=1)
    assert len(rows) == 1


def test_rebuild_index_returns_bool(seeded):
    # core.db may not exist yet → False is acceptable; must not raise
    assert search_core.rebuild_index(seeded) in (True, False)
