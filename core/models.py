"""CAPT Taxation — thin dataclasses for the main DB entities.

These are convenience wrappers; the DB contract in core/db.py (and
docs/DB_CONTRACT.md) is authoritative. Each dataclass maps 1:1 to a table
row and offers a `from_row` constructor for sqlite3.Row results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


def _row_get(row, key, default=None):
    try:
        v = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if v is None else v


@dataclass
class Book:
    id: Optional[int] = None
    title: str = ""
    volume: str = ""
    edition: str = ""
    author: str = ""
    publisher: str = ""
    source_file: str = ""
    page_count: Optional[int] = None
    tax_context_note: str = ""
    solutions_note: str = ""
    is_demo: int = 0
    created_at: str = ""

    @classmethod
    def from_row(cls, row) -> "Book":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class Chapter:
    id: str = ""
    book_id: Optional[int] = None
    number: Optional[int] = None
    title: str = ""
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    parts_json: str = "[]"

    @classmethod
    def from_row(cls, row) -> "Chapter":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class Topic:
    id: str = ""
    chapter_id: str = ""
    name: str = ""
    sort_order: Optional[int] = None
    objectives_json: str = "[]"
    source_ref: str = ""

    @classmethod
    def from_row(cls, row) -> "Topic":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class Page:
    n: int = 0
    book_id: Optional[int] = None
    chapter_id: Optional[str] = None
    has_slides: int = 0
    failed: int = 0
    text_merged: str = ""

    @classmethod
    def from_row(cls, row) -> "Page":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class Slide:
    id: Optional[int] = None
    page_n: Optional[int] = None
    title: str = ""
    topic: str = ""
    text: str = ""
    sort_order: int = 0

    @classmethod
    def from_row(cls, row) -> "Slide":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class Item:
    id: Optional[int] = None
    kind: str = ""
    topic_id: Optional[str] = None
    chapter_id: Optional[str] = None
    title: str = ""
    body: str = ""
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    source_ref: str = ""
    origin: str = ""
    status: str = ""
    extra_json: str = "{}"

    @classmethod
    def from_row(cls, row) -> "Item":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class TaxRule:
    id: Optional[int] = None
    rule_code: str = ""
    title: str = ""
    category: str = ""
    explanation: str = ""
    conditions_json: str = "[]"
    tax_year: str = ""
    taxpayer_category: str = ""
    rate_or_threshold: str = ""
    calc_method: str = ""
    exceptions_json: str = "[]"
    exclusions_json: str = "[]"
    evidence_required: str = ""
    source_ref: str = ""
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    verification_status: str = ""
    student_notes: str = ""
    origin: str = ""
    chapter_id: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "TaxRule":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class Question:
    id: str = ""
    book_id: Optional[int] = None
    chapter_id: Optional[str] = None
    topic_id: Optional[str] = None
    number: str = ""
    section: str = ""
    statement: str = ""
    solution: str = ""
    has_solution: int = 0
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    origin: str = ""
    verified_answer: int = 0
    answer_note: str = ""
    qtype: str = "theory"
    difficulty: Optional[str] = None
    marks: Optional[float] = None
    suggested_minutes: Optional[float] = None
    rubric_json: str = "[]"
    numeric_answer: Optional[float] = None
    numeric_tolerance: Optional[float] = None
    rounding: Optional[str] = None
    mcq_options_json: str = "[]"
    mcq_answer: Optional[str] = None
    alt_answers_json: str = "[]"

    @classmethod
    def from_row(cls, row) -> "Question":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class QuestionVariant:
    id: Optional[int] = None
    question_id: str = ""
    variant_json: str = "{}"
    answer_json: str = "{}"
    label: str = ""
    created_at: str = ""

    @classmethod
    def from_row(cls, row) -> "QuestionVariant":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class Flashcard:
    id: Optional[int] = None
    item_id: Optional[int] = None
    question_text: str = ""
    answer_text: str = ""
    chapter_id: Optional[str] = None
    topic_id: Optional[str] = None
    source_ref: str = ""
    origin: str = ""
    deck_tag: str = ""
    created_at: str = ""

    @classmethod
    def from_row(cls, row) -> "Flashcard":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class SRReview:
    id: Optional[int] = None
    card_id: Optional[int] = None
    ease: float = 2.5
    interval: int = 0
    reps: int = 0
    lapses: int = 0
    next_due: Optional[str] = None
    last_reviewed: Optional[str] = None
    last_rating: Optional[str] = None

    @classmethod
    def from_row(cls, row) -> "SRReview":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class Attempt:
    id: Optional[int] = None
    question_id: Optional[str] = None
    variant_id: Optional[int] = None
    flashcard_id: Optional[int] = None
    kind: str = ""
    qtype: str = ""
    correct: Optional[int] = None
    marks_obtained: Optional[float] = None
    marks_max: Optional[float] = None
    time_seconds: Optional[int] = None
    confidence: Optional[int] = None
    mistakes_json: str = "[]"
    exam_session_id: Optional[int] = None
    created_at: str = ""

    @classmethod
    def from_row(cls, row) -> "Attempt":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class ExamSession:
    id: Optional[int] = None
    title: str = ""
    mode: str = ""
    blueprint_json: str = "{}"
    starts_at: Optional[str] = None
    ends_at: Optional[str] = None
    submitted_at: Optional[str] = None
    total_marks: Optional[float] = None
    obtained: Optional[float] = None
    status: str = ""

    @classmethod
    def from_row(cls, row) -> "ExamSession":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class ExamAnswer:
    id: Optional[int] = None
    session_id: Optional[int] = None
    question_id: Optional[str] = None
    variant_id: Optional[int] = None
    answer_json: str = "{}"
    correct: Optional[int] = None
    marks_obtained: Optional[float] = None
    time_seconds: Optional[int] = None
    created_at: str = ""

    @classmethod
    def from_row(cls, row) -> "ExamAnswer":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class StudyPlan:
    id: Optional[int] = None
    name: str = ""
    exam_date: Optional[str] = None
    hours_per_day: Optional[float] = None
    study_days_json: str = "[]"
    priorities_json: str = "{}"
    created_at: str = ""
    active: int = 1

    @classmethod
    def from_row(cls, row) -> "StudyPlan":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class PlanItem:
    id: Optional[int] = None
    plan_id: Optional[int] = None
    day_date: Optional[str] = None
    activity: str = ""
    detail_json: str = "{}"
    status: str = "pending"
    created_at: str = ""

    @classmethod
    def from_row(cls, row) -> "PlanItem":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class StudySession:
    id: Optional[int] = None
    plan_item_id: Optional[int] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    activity: str = ""
    notes: str = ""

    @classmethod
    def from_row(cls, row) -> "StudySession":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class Note:
    id: Optional[int] = None
    target_kind: str = ""
    target_id: str = ""
    body: str = ""
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def from_row(cls, row) -> "Note":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class Bookmark:
    id: Optional[int] = None
    target_kind: str = ""
    target_id: str = ""
    created_at: str = ""

    @classmethod
    def from_row(cls, row) -> "Bookmark":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class ImportCorrection:
    id: Optional[int] = None
    target_kind: str = ""
    target_id: str = ""
    field: str = ""
    old_value: str = ""
    new_value: str = ""
    created_at: str = ""

    @classmethod
    def from_row(cls, row) -> "ImportCorrection":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})


@dataclass
class Backup:
    id: Optional[int] = None
    filename: str = ""
    created_at: str = ""
    note: str = ""

    @classmethod
    def from_row(cls, row) -> "Backup":
        return cls(**{f: _row_get(row, f) for f in cls.__dataclass_fields__})
