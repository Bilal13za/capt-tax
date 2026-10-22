"""Tests for core/sr.py — SM-2 spaced repetition. No streamlit."""

import datetime as _dt
import sqlite3

import pytest

from core import sr


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute(
        """CREATE TABLE items(id INTEGER PRIMARY KEY, kind TEXT, topic_id TEXT,
           chapter_id TEXT, title TEXT, body TEXT, page_start INT, page_end INT,
           source_ref TEXT, origin TEXT, status TEXT, extra_json TEXT)"""
    )
    c.execute(
        """CREATE TABLE topics(id TEXT PRIMARY KEY, chapter_id TEXT, name TEXT,
           sort_order INT, objectives_json TEXT, source_ref TEXT)"""
    )
    c.execute(
        """CREATE TABLE flashcards(id INTEGER PRIMARY KEY, item_id INTEGER,
           question_text TEXT, answer_text TEXT, chapter_id TEXT, topic_id TEXT,
           source_ref TEXT, origin TEXT, deck_tag TEXT, created_at TEXT)"""
    )
    c.execute(
        """CREATE TABLE sr_reviews(id INTEGER PRIMARY KEY, card_id INTEGER,
           ease REAL, interval INT, reps INT, lapses INT, next_due TEXT,
           last_reviewed TEXT, last_rating TEXT)"""
    )
    return c


def _mkcard(conn, **kw):
    cur = conn.execute(
        """INSERT INTO flashcards(item_id, question_text, answer_text,
           chapter_id, topic_id, source_ref, origin, deck_tag, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            kw.get("item_id"), kw.get("question_text", "Q"),
            kw.get("answer_text", "A"), kw.get("chapter_id", "ch01"),
            kw.get("topic_id", "t01"), kw.get("source_ref", "p.1"),
            kw.get("origin", "imported"), kw.get("deck_tag", "auto"),
            "2026-10-21T00:00:00",
        ),
    )
    conn.commit()
    return cur.lastrowid


def test_first_good_review_sets_interval_1(conn):
    cid = _mkcard(conn)
    st = sr.review_card(conn, cid, "good")
    assert st["interval"] == 1
    assert st["reps"] == 1
    assert st["lapses"] == 0
    assert st["ease"] == pytest.approx(2.5)
    assert st["next_due"] == (_dt.date.today() + _dt.timedelta(days=1)).isoformat()
    assert st["last_rating"] == "good"


def test_good_increases_interval(conn):
    cid = _mkcard(conn)
    sr.review_card(conn, cid, "good")  # interval 1
    st = sr.review_card(conn, cid, "good")  # interval 6
    assert st["interval"] == 6
    st = sr.review_card(conn, cid, "good")  # 6 * ease
    assert st["interval"] == round(6 * st["ease"])
    assert st["interval"] > 6


def test_again_resets_interval_and_counts_lapse(conn):
    cid = _mkcard(conn)
    sr.review_card(conn, cid, "good")
    sr.review_card(conn, cid, "good")
    st = sr.review_card(conn, cid, "again")
    assert st["interval"] == 1
    assert st["reps"] == 0
    assert st["lapses"] == 1
    assert st["next_due"] == (_dt.date.today() + _dt.timedelta(days=1)).isoformat()


def test_ease_floor_1_3(conn):
    cid = _mkcard(conn)
    st = None
    for _ in range(30):
        st = sr.review_card(conn, cid, "hard")
    assert st["ease"] >= 1.3
    for _ in range(30):
        st = sr.review_card(conn, cid, "again")
    assert st["ease"] == pytest.approx(1.3)


def test_easy_raises_ease(conn):
    cid = _mkcard(conn)
    st = sr.review_card(conn, cid, "easy")
    assert st["ease"] > 2.5  # q=5 -> EF + 0.1


def test_invalid_rating_rejected(conn):
    cid = _mkcard(conn)
    with pytest.raises(ValueError):
        sr.review_card(conn, cid, "meh")


def test_review_writes_flashcard_attempt(conn):
    cid = _mkcard(conn)
    sr.review_card(conn, cid, "again")
    sr.review_card(conn, cid, "good")
    rows = conn.execute(
        "SELECT kind, correct FROM attempts ORDER BY id"
    ).fetchall()
    assert [(r["kind"], r["correct"]) for r in rows] == [
        ("flashcard", 0),
        ("flashcard", 1),
    ]


def test_due_cards_ordering(conn):
    c_new = _mkcard(conn)  # never reviewed -> due first
    c_old = _mkcard(conn)
    c_today = _mkcard(conn)
    yesterday = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
    conn.execute(
        "INSERT INTO sr_reviews(card_id, ease, interval, reps, lapses,"
        " next_due, last_reviewed, last_rating)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (c_old, 2.5, 6, 2, 0, yesterday, yesterday, "good"),
    )
    sr.review_card(conn, c_today, "good")  # due tomorrow -> not due
    conn.commit()
    due = sr.due_cards(conn)
    ids = [d["id"] for d in due]
    assert ids == [c_new, c_old]


def test_due_cards_filters(conn):
    a = _mkcard(conn, chapter_id="ch01", topic_id="t01", deck_tag="d1")
    b = _mkcard(conn, chapter_id="ch02", topic_id="t02", deck_tag="d2")
    assert [d["id"] for d in sr.due_cards(conn, chapter_id="ch01")] == [a]
    assert [d["id"] for d in sr.due_cards(conn, topic_id="t02")] == [b]
    assert [d["id"] for d in sr.due_cards(conn, deck_tag="d1")] == [a]
    assert sr.due_cards(conn, limit=1)[0]["id"] == a


def test_ensure_cards_for_topic_creates_from_definitions(conn):
    conn.execute("INSERT INTO topics(id, chapter_id, name) VALUES ('t01','ch01','Salary')")
    conn.executemany(
        """INSERT INTO items(kind, topic_id, chapter_id, title, body, origin,
                             status, source_ref)
           VALUES (?,?,?,?,?,?,?,?)""",
        [
            ("definition", "t01", "ch01", "Salary", "Consideration for employment.",
             "imported", "verified", "s.12(2) p.5"),
            ("formula", "t01", "ch01", "Annual tax", "Monthly x 12",
             "imported", "verified", "p.6"),
            ("note", "t01", "ch01", "A note", "Not a card kind",
             "imported", "verified", "p.7"),
        ],
    )
    conn.commit()
    created = sr.ensure_cards_for_topic(conn, "t01")
    assert created == 2
    cards = conn.execute("SELECT * FROM flashcards").fetchall()
    assert len(cards) == 2
    assert cards[0]["question_text"] == "Salary"
    assert cards[0]["answer_text"] == "Consideration for employment."
    assert cards[0]["origin"] == "imported"
    # rerun creates no duplicates
    assert sr.ensure_cards_for_topic(conn, "t01") == 0


def test_ensure_cards_for_chapter(conn):
    conn.executemany(
        "INSERT INTO topics(id, chapter_id, name) VALUES (?,?,?)",
        [("t01", "ch01", "A"), ("t02", "ch01", "B")],
    )
    conn.executemany(
        "INSERT INTO items(kind, topic_id, chapter_id, title, body, origin, status)"
        " VALUES (?,?,?,?,?,?,?)",
        [
            ("definition", "t01", "ch01", "T1", "B1", "imported", "verified"),
            ("definition", "t02", "ch01", "T2", "B2", "sample", "auto_detected_unverified"),
            ("definition", None, "ch01", "T3", "B3", "imported", "verified"),
        ],
    )
    conn.commit()
    assert sr.ensure_cards_for_chapter(conn, "ch01") == 3
