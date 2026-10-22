"""Tests for core/marking.py — deterministic marking. No streamlit."""

import json
import sqlite3

import pytest

from core import marking


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute(
        """CREATE TABLE questions(id TEXT PRIMARY KEY, book_id INT, chapter_id TEXT,
           topic_id TEXT, number TEXT, section TEXT, statement TEXT, solution TEXT,
           has_solution INT, page_start INT, page_end INT, origin TEXT,
           verified_answer INT, answer_note TEXT, qtype TEXT, difficulty TEXT,
           marks REAL, suggested_minutes INT, rubric_json TEXT, numeric_answer REAL,
           numeric_tolerance REAL, rounding TEXT, mcq_options_json TEXT,
           mcq_answer TEXT, alt_answers_json TEXT)"""
    )
    return c


def _mcq_row(**kw):
    row = {
        "id": "q1", "qtype": "mcq", "marks": 1.0, "mcq_answer": "b",
        "rubric_json": None, "answer_note": None,
    }
    row.update(kw)
    return row


def test_mcq_exact_match():
    correct, marks, fb = marking.mark_mcq(_mcq_row(), "b")
    assert correct is True and marks == 1.0
    assert "Correct" in fb


def test_mcq_case_and_space_insensitive():
    correct, _, _ = marking.mark_mcq(_mcq_row(mcq_answer="B"), "  b ")
    assert correct is True


def test_mcq_wrong_with_misconception_note():
    rubric = json.dumps({"misconceptions": {"a": "Section 12(1) is the charging section, not the definition."}})
    correct, marks, fb = marking.mark_mcq(_mcq_row(rubric_json=rubric), "a")
    assert correct is False and marks == 0.0
    assert "misconception" in fb.lower()
    assert "charging section" in fb


def test_mcq_missing_key_not_marked():
    correct, marks, fb = marking.mark_mcq(_mcq_row(mcq_answer=None), "a")
    assert correct is False and marks == 0.0
    assert "No answer key" in fb


def test_tf_marking():
    row = {"id": "q2", "qtype": "tf", "marks": 1.0, "mcq_answer": "True",
           "rubric_json": None, "alt_answers_json": None}
    correct, marks, fb = marking.mark_tf(row, "true")
    assert correct is True and marks == 1.0
    correct, marks, _ = marking.mark_tf(row, "False")
    assert correct is False and marks == 0.0


def _num_row(**kw):
    row = {
        "id": "q3", "qtype": "numerical", "marks": 5.0,
        "numeric_answer": 120000.0, "numeric_tolerance": 1.0,
        "alt_answers_json": None,
    }
    row.update(kw)
    return row


def test_numerical_inside_tolerance():
    correct, marks, note = marking.mark_numerical(_num_row(), 120000.5)
    assert correct is True and marks == 5.0
    assert "method not verified" in note


def test_numerical_outside_tolerance():
    correct, marks, note = marking.mark_numerical(_num_row(), 120002.0)
    assert correct is False and marks == 0.0
    assert "Outside tolerance" in note


def test_numerical_tolerance_boundary():
    row = _num_row(numeric_tolerance=100.0)
    correct, _, _ = marking.mark_numerical(row, 120100.0)  # diff == tol
    assert correct is True
    correct, _, _ = marking.mark_numerical(row, 120100.01)
    assert correct is False


def test_numerical_default_tolerance_from_rules():
    row = _num_row(numeric_tolerance=None)  # default 1.0
    correct, _, _ = marking.mark_numerical(row, 120000.9)
    assert correct is True
    correct, _, _ = marking.mark_numerical(row, 120001.5)
    assert correct is False


def test_numerical_rounding_modes():
    row = _num_row(numeric_answer=120000.0, numeric_tolerance=0.001)
    correct, _, _ = marking.mark_numerical(row, 120000.004, rounding="2dp")
    assert correct is True  # 120000.00
    correct, _, _ = marking.mark_numerical(row, 119999.6, rounding="integer")
    assert correct is True  # 120000
    with pytest.raises(ValueError):
        marking.mark_numerical(row, 120000.0, rounding="bogus")


def test_numerical_alt_answers_accepted():
    alts = json.dumps([{"value": 119999.0, "note": "rounding variant accepted"}])
    row = _num_row(alt_answers_json=alts, numeric_tolerance=0.5)
    correct, marks, note = marking.mark_numerical(row, 119999.0)
    assert correct is True and marks == 5.0
    assert "rounding variant" in note


def test_numerical_non_numeric_rejected():
    correct, marks, note = marking.mark_numerical(_num_row(), "twelve")
    assert correct is False and marks == 0.0


def test_numerical_no_answer_stored():
    row = _num_row(numeric_answer=None)
    correct, marks, note = marking.mark_numerical(row, 5.0)
    assert correct is False and "cannot be marked" in note


def test_theory_rubric_from_json():
    rubric = json.dumps({"points": [
        {"point": "Define allowance", "marks": 2},
        {"point": "Give example", "marks": 1},
    ]})
    pts = marking.theory_rubric({"rubric_json": rubric, "solution": ""})
    assert pts == [
        {"point": "Define allowance", "marks": 2.0},
        {"point": "Give example", "marks": 1.0},
    ]


def test_theory_rubric_fallback_to_solution_lines():
    pts = marking.theory_rubric(
        {"rubric_json": None, "solution": "- Define allowance (2 marks)\n- Example (1 mark)"}
    )
    assert len(pts) == 2
    assert "Define allowance" in pts[0]["point"]


def test_self_assessment_stores_null_correct(conn):
    conn.execute(
        "INSERT INTO questions(id, qtype, marks) VALUES ('q9','theory',5.0)"
    )
    conn.commit()
    claimed = json.dumps([
        {"point": "Define allowance", "marks_claimed": 2},
        {"point": "Give example", "marks_claimed": 0.5},
    ])
    marking.record_self_assessment(conn, "q9", claimed)
    row = conn.execute("SELECT * FROM attempts").fetchone()
    assert row["kind"] == "theory"
    assert row["correct"] is None  # never auto-scored
    assert row["marks_obtained"] == pytest.approx(2.5)
    assert row["marks_max"] == pytest.approx(5.0)


def test_marking_rules_roundtrip(conn):
    rules = marking.get_marking_rules(conn)
    assert rules["numerical_default_tolerance"] == 1.0
    marking.set_marking_rules(conn, {"numerical_default_tolerance": 0.5})
    rules = marking.get_marking_rules(conn)
    assert rules["numerical_default_tolerance"] == 0.5
    assert rules["rounding_default"] == "nearest"  # defaults preserved


def test_record_attempt_central_writer(conn):
    rid = marking.record_attempt(
        conn, question_id="q1", kind="question", qtype="mcq", correct=True,
        marks_obtained=1.0, marks_max=1.0, time_seconds=42, confidence=4,
        mistakes_json={"note": "x"},
    )
    row = conn.execute("SELECT * FROM attempts WHERE id=?", (rid,)).fetchone()
    assert row["correct"] == 1
    assert row["time_seconds"] == 42
    assert json.loads(row["mistakes_json"]) == {"note": "x"}
