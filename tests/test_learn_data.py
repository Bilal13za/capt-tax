"""Tests for ui/learn.py data assembly (build_revision_sheet). No streamlit."""

import sqlite3

import pytest

from core import marking
from ui import learn


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute(
        """CREATE TABLE chapters(id TEXT PRIMARY KEY, book_id INT, number INT,
           title TEXT, page_start INT, page_end INT, parts_json TEXT)"""
    )
    c.execute(
        """CREATE TABLE topics(id TEXT PRIMARY KEY, chapter_id TEXT, name TEXT,
           sort_order INT, objectives_json TEXT, source_ref TEXT)"""
    )
    c.execute(
        """CREATE TABLE items(id INTEGER PRIMARY KEY, kind TEXT, topic_id TEXT,
           chapter_id TEXT, title TEXT, body TEXT, page_start INT, page_end INT,
           source_ref TEXT, origin TEXT, status TEXT, extra_json TEXT)"""
    )
    c.execute(
        """CREATE TABLE tax_rules(id INTEGER PRIMARY KEY, rule_code TEXT,
           title TEXT, category TEXT, explanation TEXT, conditions_json TEXT,
           tax_year TEXT, taxpayer_category TEXT, rate_or_threshold TEXT,
           calc_method TEXT, exceptions_json TEXT, exclusions_json TEXT,
           evidence_required TEXT, source_ref TEXT, page_start INT, page_end INT,
           verification_status TEXT, student_notes TEXT, origin TEXT,
           chapter_id TEXT)"""
    )
    c.execute(
        """CREATE TABLE questions(id TEXT PRIMARY KEY, book_id INT, chapter_id TEXT,
           topic_id TEXT, number TEXT, section TEXT, statement TEXT, solution TEXT,
           has_solution INT, page_start INT, page_end INT, origin TEXT,
           verified_answer INT, answer_note TEXT, qtype TEXT, difficulty TEXT,
           marks REAL, suggested_minutes INT, rubric_json TEXT, numeric_answer REAL,
           numeric_tolerance REAL, rounding TEXT, mcq_options_json TEXT,
           mcq_answer TEXT, alt_answers_json TEXT)"""
    )
    c.execute(
        """CREATE TABLE attempts(id INTEGER PRIMARY KEY, question_id TEXT,
           variant_id INTEGER, flashcard_id INTEGER, kind TEXT, qtype TEXT,
           correct INT, marks_obtained REAL, marks_max REAL, time_seconds INT,
           confidence INT, mistakes_json TEXT, exam_session_id TEXT,
           created_at TEXT)"""
    )
    # Sample-pack-like data (synthetic DEMO)
    c.execute(
        "INSERT INTO chapters(id, book_id, number, title, page_start, page_end)"
        " VALUES ('ch01', 1, 1, 'SAMPLE: SALARY BASICS (DEMO)', 1, 2)"
    )
    c.execute(
        "INSERT INTO topics(id, chapter_id, name, sort_order)"
        " VALUES ('t01', 'ch01', 'What is salary', 1)"
    )
    c.execute(
        """INSERT INTO items(kind, topic_id, chapter_id, title, body, page_start,
                             source_ref, origin, status)
           VALUES ('definition','t01','ch01','Salary (demo)',
                   'Any amount received by an employee from an employer as consideration for employment.',
                   1, 's.12(2)', 'sample', 'auto_detected_unverified')"""
    )
    c.execute(
        """INSERT INTO items(kind, topic_id, chapter_id, title, body, page_start,
                             source_ref, origin, status)
           VALUES ('formula','t01','ch01','Annual allowance','Monthly x 12', 1,
                   NULL, 'sample', 'auto_detected_unverified')"""
    )
    c.execute(
        """INSERT INTO tax_rules(rule_code, title, category, rate_or_threshold,
                                 exceptions_json, source_ref, page_start,
                                 verification_status, origin, chapter_id)
           VALUES ('S12','Salary charge','income','s.12(1)',
                   '["perquisites"]','s.12',1,'verified','sample','ch01')"""
    )
    c.execute(
        """INSERT INTO questions(id, chapter_id, topic_id, number, statement,
                                 qtype, origin, has_solution, page_start)
           VALUES ('q0001','ch01','t01','1','(DEMO) Salary defined where?',
                   'mcq','sample',1,1)"""
    )
    c.commit()
    return c


def test_revision_sheet_has_definitions_and_rules(conn):
    sheet = learn.build_revision_sheet(conn, topic_id="t01", chapter_id="ch01")
    assert len(sheet["definitions"]) == 1
    assert sheet["definitions"][0]["title"] == "Salary (demo)"
    assert len(sheet["formulas"]) == 1
    assert len(sheet["rules"]) == 1
    assert sheet["rules"][0]["rule_code"] == "S12"
    assert sheet["missed_questions"] == []


def test_revision_sheet_lists_missed_questions(conn):
    marking.record_attempt(conn, question_id="q0001", kind="question",
                           qtype="mcq", correct=False, marks_obtained=0.0,
                           marks_max=1.0)
    sheet = learn.build_revision_sheet(conn, topic_id="t01", chapter_id="ch01")
    assert len(sheet["missed_questions"]) == 1
    assert sheet["missed_questions"][0]["id"] == "q0001"
    # a later correct attempt does not remove the miss record (history kept)
    marking.record_attempt(conn, question_id="q0001", kind="question",
                           qtype="mcq", correct=True, marks_obtained=1.0,
                           marks_max=1.0)
    sheet = learn.build_revision_sheet(conn, topic_id="t01")
    assert len(sheet["missed_questions"]) == 1


def test_revision_sheet_empty_states(conn):
    sheet = learn.build_revision_sheet(conn, topic_id="nope")
    assert sheet["definitions"] == []
    assert sheet["rules"] == []
    assert sheet["missed_questions"] == []
