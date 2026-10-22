"""Tests for core/planner.py. No streamlit at module level."""

import sqlite3
from datetime import date, timedelta

import pytest

from core.planner import (generate_plan, mark_item, today_items, active_plan,
                          next_pending_item)

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
CREATE TABLE sr_reviews(id INTEGER PRIMARY KEY, card_id INT, ease REAL,
  interval INT, reps INT, lapses INT, next_due TEXT, last_reviewed TEXT,
  last_rating TEXT);
CREATE TABLE study_plans(id INTEGER PRIMARY KEY, name TEXT, exam_date TEXT,
  hours_per_day REAL, study_days_json TEXT, priorities_json TEXT,
  created_at TEXT, active INT);
CREATE TABLE plan_items(id INTEGER PRIMARY KEY, plan_id INT, day_date TEXT,
  activity TEXT, detail_json TEXT, status TEXT, created_at TEXT);
"""


def make_conn(with_performance=False):
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
                 "('ch01', 1, 'Salary'), ('ch02', 2, 'Income from property')")
    conn.execute("INSERT INTO topics (id, chapter_id, name, sort_order) VALUES "
                 "('tA', 'ch01', 'Topic A weak', 1),"
                 "('tB', 'ch02', 'Topic B strong', 1)")
    conn.execute("INSERT INTO questions (id, chapter_id, topic_id, qtype) "
                 "VALUES ('qA1','ch01','tA','numerical'),"
                 "('qB1','ch02','tB','numerical')")
    if with_performance:
        # tA: 4 incorrect -> weak; tB: 4 correct -> strong
        for _ in range(4):
            conn.execute("INSERT INTO attempts (question_id, kind, qtype, "
                         "correct) VALUES ('qA1','practice','numerical',0)")
            conn.execute("INSERT INTO attempts (question_id, kind, qtype, "
                         "correct) VALUES ('qB1','practice','numerical',1)")
    conn.commit()
    return conn


def exam_in(days):
    return (date.today() + timedelta(days=days)).isoformat()


def test_generate_plan_covers_range_and_study_days():
    conn = make_conn()
    pid = generate_plan(conn, exam_date=exam_in(14), hours_per_day=2.0,
                        study_days=["Mon", "Wed", "Fri"])
    plan = active_plan(conn)
    assert plan["id"] == pid and plan["active"] == 1
    rows = conn.execute("SELECT day_date FROM plan_items WHERE plan_id=?",
                        (pid,)).fetchall()
    assert rows, "plan should contain items"
    weekdays = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5,
                "Sun": 6}
    allowed = {weekdays[d] for d in ["Mon", "Wed", "Fri"]}
    start = date.today() + timedelta(days=1)
    end = date.today() + timedelta(days=14)
    for (d,) in rows:
        dd = date.fromisoformat(d)
        assert start <= dd <= end
        assert dd.weekday() in allowed, "item on non-study day: %s" % d


def test_generate_plan_weak_first():
    conn = make_conn(with_performance=True)
    pid = generate_plan(conn, exam_date=exam_in(10), hours_per_day=1.0,
                        study_days=["Mon", "Tue", "Wed", "Thu", "Fri",
                                    "Sat", "Sun"])
    reads = conn.execute(
        "SELECT activity, detail_json FROM plan_items WHERE plan_id=? AND "
        "activity LIKE 'Read topic%' ORDER BY day_date, id", (pid,)).fetchall()
    assert reads, "expected read activities"
    import json
    first_topic = json.loads(reads[0][1])["topic_id"]
    assert first_topic == "tA", "weakest topic should be scheduled first"


def test_generate_plan_invalid_inputs():
    conn = make_conn()
    with pytest.raises(ValueError):
        generate_plan(conn, exam_date=date.today().isoformat())
    with pytest.raises(ValueError):
        generate_plan(conn, exam_date=exam_in(5), hours_per_day=0)


def test_mark_item_transitions():
    conn = make_conn()
    pid = generate_plan(conn, exam_date=exam_in(7), hours_per_day=1.0)
    item = conn.execute("SELECT id, day_date FROM plan_items WHERE plan_id=? "
                        "LIMIT 1", (pid,)).fetchone()
    iid, old_date = item[0], item[1]

    row = mark_item(conn, iid, "completed")
    assert row["status"] == "completed"
    row = mark_item(conn, iid, "missed")
    assert row["status"] == "missed"

    new_date = (date.fromisoformat(old_date) + timedelta(days=3)).isoformat()
    row = mark_item(conn, iid, "rescheduled", new_date)
    assert row["status"] == "rescheduled"
    assert row["day_date"] == new_date

    # reschedule without explicit date -> next day
    row = mark_item(conn, iid, "rescheduled")
    assert row["day_date"] == (date.fromisoformat(new_date) +
                               timedelta(days=1)).isoformat()

    with pytest.raises(ValueError):
        mark_item(conn, iid, "bogus")
    with pytest.raises(ValueError):
        mark_item(conn, 999999, "completed")


def test_today_items_and_next_pending():
    conn = make_conn()
    pid = generate_plan(conn, exam_date=exam_in(7), hours_per_day=1.0)
    assert today_items(conn) == []  # plan starts tomorrow
    item = conn.execute("SELECT id FROM plan_items WHERE plan_id=? LIMIT 1",
                        (pid,)).fetchone()[0]
    mark_item(conn, item, "rescheduled", date.today().isoformat())
    todays = today_items(conn)
    assert len(todays) == 1 and todays[0]["id"] == item

    nxt = next_pending_item(conn)
    assert nxt is not None and nxt["status"] == "pending"
