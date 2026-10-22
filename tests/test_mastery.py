"""Tests for core/mastery.py — formula math on synthetic attempts."""

import sqlite3
from datetime import datetime, timedelta

import pytest

from core.mastery import topic_mastery, chapter_mastery, FORMULA_TEXT

DDL = """
CREATE TABLE chapters(id TEXT PRIMARY KEY, book_id INT, number INT, title TEXT,
  page_start INT, page_end INT, parts_json TEXT);
CREATE TABLE topics(id TEXT PRIMARY KEY, chapter_id TEXT, name TEXT,
  sort_order INT, objectives_json TEXT, source_ref TEXT);
CREATE TABLE questions(id TEXT PRIMARY KEY, book_id INT, chapter_id TEXT,
  topic_id TEXT, number TEXT, section TEXT, statement TEXT, solution TEXT,
  has_solution INT, page_start INT, page_end INT, origin TEXT,
  verified_answer INT, answer_note TEXT, qtype TEXT, difficulty TEXT,
  marks REAL, suggested_minutes INT, rubric_json TEXT, numeric_answer REAL,
  numeric_tolerance REAL, rounding TEXT, mcq_options_json TEXT, mcq_answer TEXT,
  alt_answers_json TEXT);
CREATE TABLE attempts(id INTEGER PRIMARY KEY, question_id TEXT, variant_id TEXT,
  flashcard_id INT, kind TEXT, qtype TEXT, correct INT, marks_obtained REAL,
  marks_max REAL, time_seconds INT, confidence INT, mistakes_json TEXT,
  exam_session_id INT, created_at TEXT);
CREATE TABLE flashcards(id INTEGER PRIMARY KEY, item_id INT, question_text TEXT,
  answer_text TEXT, chapter_id TEXT, topic_id TEXT, source_ref TEXT,
  origin TEXT, deck_tag TEXT, created_at TEXT);
CREATE TABLE sr_reviews(id INTEGER PRIMARY KEY, card_id INT, ease REAL,
  interval INT, reps INT, lapses INT, next_due TEXT, last_reviewed TEXT,
  last_rating TEXT);
"""


def make_conn():
    try:
        from core import db as _db  # noqa
        connect = getattr(_db, "connect_memory", None)
        if callable(connect):
            return connect()
    except Exception:
        pass
    conn = sqlite3.connect(":memory:")
    conn.executescript(DDL)
    conn.execute("INSERT INTO chapters (id, number, title) VALUES "
                 "('ch01', 1, 'Salary')")
    conn.execute("INSERT INTO topics (id, chapter_id, name, sort_order) VALUES "
                 "('t_empty', 'ch01', 'Empty topic', 1),"
                 "('t1', 'ch01', 'Allowances', 2),"
                 "('t2', 'ch01', 'Perquisites', 3)")
    conn.execute("INSERT INTO questions (id, chapter_id, topic_id, qtype) VALUES "
                 "('q1','ch01','t1','mcq'),('q2','ch01','t1','numerical'),"
                 "('q3','ch01','t1','theory'),('q4','ch01','t2','mcq')")
    conn.commit()
    return conn


def add_attempt(conn, qid, qtype, correct, days_ago=0):
    ts = (datetime.now() - timedelta(days=days_ago)).isoformat()
    conn.execute("INSERT INTO attempts (question_id, kind, qtype, correct, "
                 "created_at) VALUES (?,?,?,?,?)",
                 (qid, "practice", qtype, correct, ts))
    conn.commit()


def add_card(conn, topic_id, rating):
    cur = conn.execute("INSERT INTO flashcards (topic_id) VALUES (?)",
                       (topic_id,))
    cid = cur.lastrowid
    conn.execute("INSERT INTO sr_reviews (card_id, last_rating, next_due) "
                 "VALUES (?,?,?)", (cid, rating,
                                    datetime.now().isoformat()))
    conn.commit()


def test_empty_topic_no_evidence():
    m = topic_mastery(make_conn(), "t_empty")
    assert m["score"] == 0.0
    assert m["band"] == "weak"
    assert any("no evidence" in r for r in m["reasons"])
    assert set(m["components"]) == {"recent_accuracy", "flashcard_recall",
                                    "calculation_success", "application_success"}


def test_single_attempt_capped_at_40():
    conn = make_conn()
    add_attempt(conn, "q1", "mcq", 1)
    m = topic_mastery(conn, "t1")
    assert m["score"] <= 40
    assert any("insufficient evidence" in r for r in m["reasons"])
    assert m["band"] == "weak"


def test_formula_renormalises_missing_components():
    # 10/10 correct recent, nothing else -> score 100 (weights renormalised)
    conn = make_conn()
    for _ in range(10):
        add_attempt(conn, "q1", "mcq", 1)
    m = topic_mastery(conn, "t1")
    assert m["components"]["recent_accuracy"] == 100.0
    assert m["components"]["flashcard_recall"] is None
    assert m["score"] == 100.0
    assert m["band"] == "strong"
    assert any("renormalised" in r for r in m["reasons"])


def test_formula_mixed_components_math():
    # recent: 2/4 correct -> 50; recall: 3/4 good -> 75; calc: 1/2 -> 50;
    # application: none. weights present: .4+.25+.2=.85
    # score = (50*.4 + 75*.25 + 50*.2)/.85 = 48.75/.85 = 57.35
    conn = make_conn()
    add_attempt(conn, "q1", "mcq", 1)
    add_attempt(conn, "q1", "mcq", 0)
    add_attempt(conn, "q1", "mcq", 1)
    add_attempt(conn, "q1", "mcq", 0)
    add_attempt(conn, "q2", "numerical", 1)
    add_attempt(conn, "q2", "numerical", 0)
    add_card(conn, "t1", "good")
    add_card(conn, "t1", "good")
    add_card(conn, "t1", "easy")
    add_card(conn, "t1", "again")
    m = topic_mastery(conn, "t1")
    assert m["components"]["recent_accuracy"] == 50.0
    assert m["components"]["flashcard_recall"] == 75.0
    assert m["components"]["calculation_success"] == 50.0
    assert m["components"]["application_success"] is None
    assert m["score"] == pytest.approx(57.35, abs=0.05)
    assert m["band"] == "developing"
    assert m["reasons"]  # non-empty


def test_bands_and_application_component():
    conn = make_conn()
    for _ in range(5):  # 3/5 correct -> 60 developing
        add_attempt(conn, "q1", "mcq", 1)
    for _ in range(5):
        add_attempt(conn, "q1", "mcq", 0)
    m = topic_mastery(conn, "t1")
    assert m["band"] == "developing"

    conn2 = make_conn()
    for _ in range(4):
        add_attempt(conn2, "q3", "theory", 0)  # 0% application
    m2 = topic_mastery(conn2, "t1")
    assert m2["components"]["application_success"] == 0.0
    assert m2["band"] == "weak"


def test_chapter_mastery_aggregates_topics():
    conn = make_conn()
    for _ in range(10):
        add_attempt(conn, "q1", "mcq", 1)  # t1 strong
    m = chapter_mastery(conn, "ch01")
    assert "topics" in m and set(m["topics"]) == {"t_empty", "t1", "t2"}
    assert m["score"] == pytest.approx(
        (m["topics"]["t_empty"]["score"] + m["topics"]["t1"]["score"] +
         m["topics"]["t2"]["score"]) / 3, abs=0.06)
    assert any("weak topics" in r for r in m["reasons"])


def test_formula_text_documents_weights():
    assert "0.40" in FORMULA_TEXT and "0.25" in FORMULA_TEXT
    assert "0.20" in FORMULA_TEXT and "0.15" in FORMULA_TEXT
