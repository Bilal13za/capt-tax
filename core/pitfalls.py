"""Pitfalls & examiner insights — pure logic, streamlit-free.

Seeds come ONLY from the real examiner commentary printed in the textbook
(chapter ch01, pages 7–12 of the content pack). Seeding is gated on a
sentinel: if the commentary text is not in the database, nothing is seeded,
so a different book never receives this book's pitfalls. Quoted spans are
verbatim from the extraction; where the extraction is fragmented the gap is
marked with […] — never smoothed into a claim the book didn't make.

Each pitfall records the chapter it is most useful for (chapter_id), the
real page it was observed on, and source='examiner_commentary'.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone

SOURCE_EXAMINER = "examiner_commentary"
SOURCE_STUDENT = "student"

# Sentinel fragments: seeding runs only when the commentary is really there.
_SENTINELS = (
    "only 26% of examinees securing passing marks",
    "Examiner Comments",
)

# (chapter_id, topic, title, observation, page)
# Every quoted span below was verified verbatim against data/content_pack.json.
SEED_PITFALLS = [
    ("ch01", "MCQs — general exam technique",
     "Don't bank on MCQs being 'free marks'",
     "Examiner, Spring 2026: Question 1 (MCQs) is \"generally being "
     "considered a scoring question\", yet performance was \"below "
     "expectations, with only 26% of examinees securing passing marks\".",
     8),
    ("ch12", "Computation discipline",
     "Income-tax computation is the examiners' perennial weak spot",
     "Examiner, Autumn 2025: \"income tax computation continues to be a "
     "weak area for many examinees\".",
     8),
    ("ch12", "Computation discipline",
     "Basic adjustments, classification and tax treatment",
     "Examiner, Autumn 2025: \"Frequent errors in basic adjustments, "
     "classification, and tax treatment reflected inadequate practice and "
     "weak command of core […] computational skills.\"",
     8),
    ("ch01", "Time management — general exam technique",
     "Answer the requirement; nothing more",
     "Examiner, Autumn 2025: in Questions 3 and 4 many \"failed to address "
     "specific requirements and included unnecessary explanations or "
     "references, demonstrating poor time management and a lack of "
     "focus\".",
     8),
    ("ch02", "Key concepts — residence vs PE",
     "Permanent establishment ≠ residential status",
     "Examiner, Spring 2025: \"many examinees confused the concept of "
     "permanent establishment with that of residential status and provided "
     "irrelevant comments related to residency, an entirely separate and "
     "distinct concept.\"",
     9),
    ("ch01", "Reading the question — general exam technique",
     "Answer AE's question, not BE's",
     "Examiner, Spring 2025: \"in question 7(a), many failed to recognize "
     "that the input tax entitlement of AE was to be addressed; instead, "
     "they focused on the input tax entitlement of BE.\"",
     9),
    ("ch14", "Wealth statement concepts",
     "Wealth statement ≠ wealth reconciliation statement",
     "Examiner, Autumn 2024: \"there was confusion regarding the "
     "distinction between a wealth statement and a wealth reconciliation "
     "statement.\"",
     9),
    ("ch05", "Asset classification",
     "Classify the asset before computing anything",
     "Examiner, Autumn 2024: \"many examinees were unable to correctly "
     "identify heads of income and assets, with several failing to classify "
     "a gray parrot as a personal asset.\"",
     9),
    ("ch11", "Loss adjustments — ordering",
     "Brought-forward losses before depreciation",
     "Examiner, Autumn 2024: \"In Q-5, depreciation and amortization were "
     "deducted before the adjustment of brought-forward losses from Tax "
     "Year 2022\" — the wrong order, penalised despite being tested many "
     "times before.",
     9),
    ("ch06", "Capital gains — what is a disposal",
     "A gift can be a disposal",
     "Examiner, Spring 2024: \"many examinees failed to recognize the gift "
     "of a coin collection as a disposal, thereby overlooking the capital "
     "gain associated with this transaction.\"",
     10),
    ("ch06", "Capital gains — what is a capital asset",
     "Personal-use assets are not capital assets",
     "Examiner, Spring 2024: \"many examinees incorrectly classified an "
     "executive table used at Ashfaq's residence as a capital asset, "
     "leading to an incorrect computation of capital loss upon its "
     "disposal.\"",
     10),
    ("ch01", "Answering 'discuss' — general exam technique",
     "'Discuss' means conclusion PLUS basis",
     "Examiner, Autumn 2023: the verb \"discuss\" \"implies the expectation "
     "to provide not only the conclusion but also the basis or reason for "
     "it, rather than directly jumping to the conclusion.\"",
     10),
    ("ch01", "Study coverage — general exam technique",
     "Selective study fails on application questions",
     "Examiner, Spring 2022: poor performance was \"mainly due to selective "
     "study and failure to apply the theoretical knowledge to practical "
     "situations\" — study the entire syllabus.",
     11),
]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _q(conn: sqlite3.Connection, sql: str, params=()):
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _db_text_blob(conn: sqlite3.Connection) -> str:
    """Concatenated searchable text from pages/slides for the sentinel check.

    Whitespace is collapsed because the extraction stores line breaks inside
    sentences ("securing\\npassing marks").
    """
    parts = []
    try:
        for r in conn.execute("SELECT text_merged FROM pages"):
            if r[0]:
                parts.append(r[0])
    except sqlite3.Error:
        pass
    try:
        for r in conn.execute("SELECT text FROM slides"):
            if r[0]:
                parts.append(r[0])
    except sqlite3.Error:
        pass
    return re.sub(r"\s+", " ", "\n".join(parts))


def commentary_present(conn: sqlite3.Connection) -> bool:
    """True when the book's examiner commentary is in this database."""
    blob = _db_text_blob(conn)
    return all(s in blob for s in _SENTINELS)


def seed_pitfalls(conn: sqlite3.Connection) -> int:
    """Seed examiner pitfalls. Idempotent. Returns number created.

    Seeds nothing when the examiner commentary is absent from the DB.
    """
    if not commentary_present(conn):
        return 0
    created = 0
    for chapter_id, topic, title, observation, page in SEED_PITFALLS:
        exists = conn.execute(
            "SELECT 1 FROM pitfalls WHERE source=? AND title=?",
            (SOURCE_EXAMINER, title)).fetchone()
        if exists:
            continue
        # Only attach to chapters that exist in this DB.
        if not conn.execute("SELECT 1 FROM chapters WHERE id=?",
                            (chapter_id,)).fetchone():
            continue
        conn.execute(
            """INSERT INTO pitfalls(chapter_id, topic, title, observation,
                                    page, source, status, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (chapter_id, topic, title, observation, page, SOURCE_EXAMINER,
             "seeded", _utcnow()))
        created += 1
    conn.commit()
    return created


def list_pitfalls(conn: sqlite3.Connection, chapter_id: str | None = None) -> list:
    if chapter_id:
        return _q(conn, "SELECT * FROM pitfalls WHERE chapter_id=? ORDER BY id",
                  (chapter_id,))
    return _q(conn, "SELECT * FROM pitfalls ORDER BY chapter_id, id")


def add_pitfall(conn: sqlite3.Connection, chapter_id: str, topic: str,
                title: str, observation: str, page: int | None = None) -> int:
    cur = conn.execute(
        """INSERT INTO pitfalls(chapter_id, topic, title, observation, page,
                                source, status, created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (chapter_id, topic or "", title, observation, page, SOURCE_STUDENT,
         "student", _utcnow()))
    conn.commit()
    return cur.lastrowid


def delete_pitfall(conn: sqlite3.Connection, pitfall_id: int) -> None:
    conn.execute("DELETE FROM pitfalls WHERE id=?", (pitfall_id,))
    conn.commit()


def make_flashcard(conn: sqlite3.Connection, pitfall_id: int) -> int:
    """One-click flashcard from a pitfall. Idempotent on the card front."""
    p = conn.execute("SELECT * FROM pitfalls WHERE id=?",
                     (pitfall_id,)).fetchone()
    if not p:
        raise ValueError("pitfall not found")
    p = dict(p)
    front = f"⚠ {p['title']}"
    existing = conn.execute(
        "SELECT id FROM flashcards WHERE origin='pitfall' AND question_text=?",
        (front,)).fetchone()
    if existing:
        return existing["id"]
    ch = conn.execute("SELECT number FROM chapters WHERE id=?",
                      (p["chapter_id"],)).fetchone()
    back = p["observation"] + (
        f" (Examiner commentary, p. {p['page']})" if p["page"] else "")
    cur = conn.execute(
        """INSERT INTO flashcards(item_id, question_text, answer_text,
                                  chapter_id, topic_id, source_ref, origin,
                                  deck_tag, created_at)
           VALUES (NULL,?,?,?,?,?,?,?,?)""",
        (front, back, p["chapter_id"], None,
         f"Ch {ch['number']}, p. {p['page']}" if ch and p["page"] else "",
         "pitfall", "pitfalls", _utcnow()))
    conn.commit()
    return cur.lastrowid
