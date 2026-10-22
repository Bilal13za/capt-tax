"""Tests for core/exams.py. No streamlit at module level."""

import json
import sqlite3

import pytest

from core.exams import (build_exam, save_answer, submit_exam, exam_summary,
                        list_sessions)

DDL = """
CREATE TABLE questions(id TEXT PRIMARY KEY, book_id INT, chapter_id TEXT,
  topic_id TEXT, number TEXT, section TEXT, statement TEXT, solution TEXT,
  has_solution INT, page_start INT, page_end INT, origin TEXT,
  verified_answer INT, answer_note TEXT, qtype TEXT, difficulty TEXT,
  marks REAL, suggested_minutes INT, rubric_json TEXT, numeric_answer REAL,
  numeric_tolerance REAL, rounding TEXT, mcq_options_json TEXT, mcq_answer TEXT,
  alt_answers_json TEXT);
CREATE TABLE exam_sessions(id INTEGER PRIMARY KEY, title TEXT, mode TEXT,
  blueprint_json TEXT, starts_at TEXT, ends_at TEXT, submitted_at TEXT,
  total_marks REAL, obtained REAL, status TEXT);
CREATE TABLE exam_answers(id INTEGER PRIMARY KEY, session_id INT,
  question_id TEXT, variant_id TEXT, answer_json TEXT, correct INT,
  marks_obtained REAL, time_seconds INT, created_at TEXT);
CREATE TABLE attempts(id INTEGER PRIMARY KEY, question_id TEXT, variant_id TEXT,
  flashcard_id INT, kind TEXT, qtype TEXT, correct INT, marks_obtained REAL,
  marks_max REAL, time_seconds INT, confidence INT, mistakes_json TEXT,
  exam_session_id INT, created_at TEXT);
"""


def make_conn():
    # Lazy core.db attempt with sqlite3 fallback (foundation may not exist).
    try:
        from core import db as _db  # noqa
        connect = getattr(_db, "connect_memory", None)
        if callable(connect):
            return connect()
    except Exception:
        pass
    conn = sqlite3.connect(":memory:")
    conn.executescript(DDL)
    return conn


def seed_questions(conn):
    qs = [
        # id, chapter, topic, qtype, difficulty, marks, mcq_answer
        ("q1", "ch01", "t1", "mcq", "easy", 2, "A"),
        ("q2", "ch01", "t1", "mcq", "hard", 3, "B"),
        ("q3", "ch01", "t2", "numerical", "easy", 5, None),
        ("q4", "ch01", "t2", "theory", "hard", 10, None),
        ("q5", "ch01", "t1", "short", "easy", 2, None),
        ("q6", "ch02", "t3", "mcq", "easy", 2, "C"),
        ("q7", "ch02", "t3", "mcq", "hard", 3, "D"),
        ("q8", "ch02", "t4", "numerical", "hard", 5, None),
        ("q9", "ch02", "t4", "scenario", "hard", 8, None),
        ("q10", "ch02", "t3", "tf", "easy", 1, "True"),
        ("q11", "ch01", "t2", "mcq", "easy", 2, "A"),
        ("q12", "ch02", "t4", "mcq", "easy", 2, "B"),
    ]
    for qid, ch, tp, qt, diff, marks, ans in qs:
        conn.execute(
            "INSERT INTO questions (id, chapter_id, topic_id, qtype, "
            "difficulty, marks, statement, mcq_answer, mcq_options_json, "
            "numeric_answer, numeric_tolerance) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (qid, ch, tp, qt, diff, marks, "statement " + qid, ans,
             json.dumps(["A", "B", "C", "D"]), 42.0, 0.01))
    conn.commit()


@pytest.fixture
def conn():
    c = make_conn()
    seed_questions(c)
    return c


def base_blueprint(**over):
    bp = {"chapters": "all", "qtypes": [], "difficulty": [], "count": 4,
          "marks_limit": None, "include_incorrect": True,
          "include_unattempted": True, "time_minutes": 60}
    bp.update(over)
    return bp


def test_build_exam_honors_filters(conn):
    sid, qids = build_exam(conn, "T1", "timed",
                           base_blueprint(chapters=["ch01"], qtypes=["mcq"],
                                          count=3))
    assert len(qids) == 3
    rows = conn.execute("SELECT chapter_id, qtype FROM questions WHERE id IN "
                        "(%s)" % ",".join("?" * len(qids)), qids).fetchall()
    assert all(r[0] == "ch01" and r[1] == "mcq" for r in rows)
    row = conn.execute("SELECT status, mode FROM exam_sessions WHERE id=?",
                       (sid,)).fetchone()
    assert row[0] == "in_progress" and row[1] == "timed"


def test_build_exam_deterministic(conn):
    _, qids1 = build_exam(conn, "Same", "untimed", base_blueprint(count=5))
    _, qids2 = build_exam(conn, "Same", "untimed", base_blueprint(count=5))
    assert qids1 == qids2
    _, qids3 = build_exam(conn, "Different", "untimed", base_blueprint(count=5))
    # different title -> (almost surely) different order; count still honored
    assert len(qids3) == 5


def test_build_exam_too_small_bank_raises(conn):
    with pytest.raises(ValueError, match="too small"):
        build_exam(conn, "T", "untimed",
                   base_blueprint(chapters=["ch01"], qtypes=["mcq"],
                                  difficulty=["impossible"], count=2))
    with pytest.raises(ValueError, match="too small"):
        build_exam(conn, "T", "untimed", base_blueprint(count=999))


def test_build_exam_marks_limit(conn):
    sid, qids = build_exam(conn, "T", "untimed",
                           base_blueprint(count=4, marks_limit=8))
    total = conn.execute("SELECT SUM(marks) FROM questions WHERE id IN (%s)" %
                         ",".join("?" * len(qids)), qids).fetchone()[0]
    assert total <= 8
    assert len(qids) == 4


def test_build_exam_attempt_filters(conn):
    # q1 attempted+correct, q2 attempted+incorrect, q3+ never attempted
    conn.execute("INSERT INTO attempts (question_id, kind, qtype, correct) "
                 "VALUES ('q1','practice','mcq',1)")
    conn.execute("INSERT INTO attempts (question_id, kind, qtype, correct) "
                 "VALUES ('q2','practice','mcq',0)")
    conn.commit()
    _, qids = build_exam(conn, "T", "untimed",
                         base_blueprint(count=2, include_unattempted=False))
    assert set(qids) <= {"q1", "q2"}
    _, qids = build_exam(conn, "T", "untimed",
                         base_blueprint(count=11, include_incorrect=False))
    assert "q2" not in qids


def test_save_answer_upserts(conn):
    sid, qids = build_exam(conn, "T", "untimed", base_blueprint(count=2))
    save_answer(conn, sid, qids[0], {"answer": "A"}, 30)
    save_answer(conn, sid, qids[0], {"answer": "B"}, 45)
    rows = conn.execute("SELECT answer_json, time_seconds FROM exam_answers "
                        "WHERE session_id=? AND question_id=?",
                        (sid, qids[0])).fetchall()
    assert len(rows) == 1
    assert json.loads(rows[0][0]) == {"answer": "B"}
    assert rows[0][1] == 45


def stub_mark_fn(question_row, answer):
    marks = float(question_row.get("marks") or 0)
    return 1, marks  # everything correct


def test_submit_exam_scores_and_mirrors(conn):
    sid, qids = build_exam(conn, "T", "timed", base_blueprint(count=3))
    save_answer(conn, sid, qids[0], {"answer": "A"}, 60)
    save_answer(conn, sid, qids[1], {"answer": "B"}, 90)
    summary = submit_exam(conn, sid, stub_mark_fn)

    assert summary["status"] == "submitted"
    assert summary["answered"] == 2
    assert summary["count"] == 3
    expected_total = conn.execute(
        "SELECT SUM(marks) FROM questions WHERE id IN (%s)" %
        ",".join("?" * len(qids)), qids).fetchone()[0]
    assert summary["total"] == pytest.approx(expected_total)
    answered_marks = conn.execute(
        "SELECT SUM(marks) FROM questions WHERE id IN (?,?)",
        (qids[0], qids[1])).fetchone()[0]
    assert summary["obtained"] == pytest.approx(answered_marks)
    assert summary["time"]["total_seconds"] == 150
    assert summary["time"]["unanswered"] == 1
    for key in ("by_chapter", "by_topic", "by_qtype", "missed",
                "pending_review"):
        assert key in summary

    # mirrored attempts
    rows = conn.execute("SELECT kind, exam_session_id, correct, marks_max, "
                        "question_id FROM attempts WHERE exam_session_id=?",
                        (sid,)).fetchall()
    assert len(rows) == 3
    by_qid = {r[4]: r for r in rows}
    assert all(r[0] == "exam" and r[1] == sid for r in rows)
    # answered questions marked correct by the stub...
    assert by_qid[qids[0]][2] == 1 and by_qid[qids[1]][2] == 1
    # ...unanswered question mirrored with correct NULL
    assert by_qid[qids[2]][2] is None

    # session row closed
    s = conn.execute("SELECT status, submitted_at, ends_at FROM exam_sessions "
                     "WHERE id=?", (sid,)).fetchone()
    assert s[0] == "submitted" and s[1] and s[2]


def test_submit_exam_missed_and_timing(conn):
    sid, qids = build_exam(conn, "T", "untimed", base_blueprint(count=2))
    save_answer(conn, sid, qids[0], {"answer": "X"}, 40)
    save_answer(conn, sid, qids[1], {"answer": "Y"}, 50)

    def mark_wrong(q, a):
        return 0, 0.0

    summary = submit_exam(conn, sid, mark_wrong)
    assert set(summary["missed"]) == {qids[0], qids[1]}
    assert summary["obtained"] == 0
    assert summary["time"]["total_seconds"] == 90


def test_in_progress_session_recoverable(conn):
    # simulate app closed mid-session: build + answer, never submit
    sid, qids = build_exam(conn, "T", "timed", base_blueprint(count=3))
    save_answer(conn, sid, qids[0], {"answer": "A"}, 25)
    summary = exam_summary(conn, sid)
    assert summary["status"] == "in_progress"
    assert summary["answered"] == 1
    assert summary["count"] == 3
    assert summary["obtained"] is None  # not marked yet
    # past-session listing shows it as recoverable
    sessions = list_sessions(conn)
    assert any(s["id"] == sid and s["status"] == "in_progress"
               for s in sessions)
