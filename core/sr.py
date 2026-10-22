"""Spaced repetition (SM-2) for flashcards.

Algorithm implemented (documented SM-2, adapted from SuperMemo SM-2):

Each card carries an *easiness factor* (EF, starts at 2.5), a repetition
counter `reps` (consecutive successful reviews), an `interval` in days, and a
`lapses` counter.

Ratings map to SM-2 quality scores q:
    again -> q = 0   (complete blackout)
    hard  -> q = 3   (correct but with serious difficulty)
    good  -> q = 4   (correct after hesitation)
    easy  -> q = 5   (perfect recall)

Update rules:
    EF' = EF + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02)), floored at 1.3.
    If q < 3 (i.e. rating 'again'): lapses += 1, reps = 0, interval = 1 day.
    Else:
        reps += 1
        if reps == 1: interval = 1
        elif reps == 2: interval = 6
        else: interval = round(previous_interval * EF')
        ('hard' additionally scales the new interval by 1.2x of the
        previous interval instead of EF — a common conservative tweak so
        hard cards come back sooner: interval = max(1, round(prev * 1.2)).)
    next_due = today + interval days (stored as ISO date 'YYYY-MM-DD').

Cards with no sr_reviews row are treated as never reviewed and are always due.
"""

from __future__ import annotations

import datetime as _dt
import json as _json

RATINGS = ("again", "hard", "good", "easy")
_QUALITY = {"again": 0, "hard": 3, "good": 4, "easy": 5}
_EASE_FLOOR = 1.3
_DEFAULT_EASE = 2.5


def _today() -> _dt.date:
    return _dt.date.today()


def _row_to_dict(row):
    return dict(row) if row is not None else None


def _get_db_helpers():
    """Return (get_conn-ish helpers) lazily; sqlite3 fallback if core.db missing."""
    try:
        from core import db as _db  # noqa

        return _db
    except Exception:
        return None


def open_db(path):
    """Open a SQLite connection (tries core.db first, falls back to sqlite3)."""
    dbmod = _get_db_helpers()
    if dbmod is not None and hasattr(dbmod, "connect"):
        return dbmod.connect(path)
    import sqlite3

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sr_reviews(
            id INTEGER PRIMARY KEY,
            card_id INTEGER,
            ease REAL,
            interval INT,
            reps INT,
            lapses INT,
            next_due TEXT,
            last_reviewed TEXT,
            last_rating TEXT)"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS flashcards(
            id INTEGER PRIMARY KEY,
            item_id INTEGER,
            question_text TEXT,
            answer_text TEXT,
            chapter_id TEXT,
            topic_id TEXT,
            source_ref TEXT,
            origin TEXT,
            deck_tag TEXT,
            created_at TEXT)"""
    )


def get_review(conn, card_id):
    """Return the sr_reviews row for a card (dict) or None."""
    cur = conn.execute("SELECT * FROM sr_reviews WHERE card_id = ?", (card_id,))
    return _row_to_dict(cur.fetchone())


def review_card(conn, card_id, rating):
    """Apply an SM-2 review for ``card_id`` with one of again|hard|good|easy.

    Creates the sr_reviews row when absent. Returns the new review state dict.
    Also writes an attempts row (kind='flashcard').
    """
    if rating not in RATINGS:
        raise ValueError(f"rating must be one of {RATINGS}, got {rating!r}")
    _ensure_schema(conn)
    q = _QUALITY[rating]
    today = _today()
    prev = get_review(conn, card_id)

    ease = _DEFAULT_EASE if prev is None else float(prev["ease"] or _DEFAULT_EASE)
    reps = 0 if prev is None else int(prev["reps"] or 0)
    interval = 0 if prev is None else int(prev["interval"] or 0)
    lapses = 0 if prev is None else int(prev["lapses"] or 0)

    # Easiness update (SM-2), floored at 1.3. 'again' still adjusts EF downward.
    ease = ease + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    if ease < _EASE_FLOOR:
        ease = _EASE_FLOOR

    if q < 3:  # again
        lapses += 1
        reps = 0
        interval = 1
    else:
        reps += 1
        if rating == "hard":
            interval = max(1, round(interval * 1.2)) if interval else 1
        elif reps == 1:
            interval = 1
        elif reps == 2:
            interval = 6
        else:
            interval = max(1, round(interval * ease))

    next_due = (today + _dt.timedelta(days=interval)).isoformat()

    if prev is None:
        conn.execute(
            """INSERT INTO sr_reviews(card_id, ease, interval, reps, lapses,
                                      next_due, last_reviewed, last_rating)
               VALUES (?,?,?,?,?,?,?,?)""",
            (card_id, ease, interval, reps, lapses, next_due,
             today.isoformat(), rating),
        )
    else:
        conn.execute(
            """UPDATE sr_reviews SET ease=?, interval=?, reps=?, lapses=?,
                                  next_due=?, last_reviewed=?, last_rating=?
               WHERE card_id=?""",
            (ease, interval, reps, lapses, next_due, today.isoformat(), rating, card_id),
        )
    record_attempt(
        conn,
        flashcard_id=card_id,
        kind="flashcard",
        correct=0 if rating == "again" else 1,
    )
    conn.commit()
    return get_review(conn, card_id)


def due_cards(conn, chapter_id=None, topic_id=None, deck_tag=None, limit=None):
    """Cards due for review: next_due <= today or never reviewed.

    Ordered by due date (never-reviewed first). Returns list of dicts
    (flashcard columns + sr columns when present).
    """
    _ensure_schema(conn)
    clauses = []
    params = []
    if chapter_id is not None:
        clauses.append("f.chapter_id = ?")
        params.append(chapter_id)
    if topic_id is not None:
        clauses.append("f.topic_id = ?")
        params.append(topic_id)
    if deck_tag is not None:
        clauses.append("f.deck_tag = ?")
        params.append(deck_tag)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    today = _today().isoformat()
    due_clause = "(s.next_due IS NULL OR s.next_due <= ?)"
    where = (where + " AND " + due_clause) if where else "WHERE " + due_clause
    sql = f"""
        SELECT f.*, s.ease, s.interval, s.reps, s.lapses, s.next_due,
               s.last_reviewed, s.last_rating
        FROM flashcards f LEFT JOIN sr_reviews s ON s.card_id = f.id
        {where}
        ORDER BY CASE WHEN s.next_due IS NULL THEN 0 ELSE 1 END,
                 s.next_due, f.id
    """
    params.append(today)
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    cur = conn.execute(sql, params)
    return [_row_to_dict(r) for r in cur.fetchall()]


def ensure_cards_for_topic(conn, topic_id):
    """Auto-generate flashcards from definition/formula items of a topic.

    question_text = item title (or term), answer_text = item body.
    origin is carried over from the item. Skips items that already have a
    card (matched on item_id). Returns the number of cards created.
    """
    _ensure_schema(conn)
    cur = conn.execute(
        """SELECT i.id, i.title, i.body, i.origin, i.source_ref, i.chapter_id,
                  i.topic_id, i.kind
           FROM items i
           WHERE i.topic_id = ? AND i.kind IN ('definition','formula')""",
        (topic_id,),
    )
    items = cur.fetchall()
    created = 0
    for it in items:
        exists = conn.execute(
            "SELECT 1 FROM flashcards WHERE item_id = ?", (it["id"],)
        ).fetchone()
        if exists:
            continue
        title = it["title"] or ""
        question = title if title else (it["body"] or "")[:120]
        conn.execute(
            """INSERT INTO flashcards(item_id, question_text, answer_text,
                                      chapter_id, topic_id, source_ref, origin,
                                      deck_tag, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                it["id"],
                question,
                it["body"],
                it["chapter_id"],
                it["topic_id"],
                it["source_ref"],
                it["origin"],
                "auto",
                _dt.datetime.now().isoformat(timespec="seconds"),
            ),
        )
        created += 1
    conn.commit()
    return created


def ensure_cards_for_chapter(conn, chapter_id):
    """Auto-generate flashcards for every topic in a chapter. Returns count."""
    cur = conn.execute(
        "SELECT id FROM topics WHERE chapter_id = ?", (chapter_id,)
    ).fetchall()
    total = 0
    for t in cur:
        total += ensure_cards_for_topic(conn, t["id"])
    # Also cover items attached directly to the chapter with no topic.
    cur = conn.execute(
        """SELECT i.id FROM items i
           WHERE i.chapter_id = ? AND (i.topic_id IS NULL OR i.topic_id = '')
             AND i.kind IN ('definition','formula')
             AND NOT EXISTS (SELECT 1 FROM flashcards f WHERE f.item_id = i.id)""",
        (chapter_id,),
    )
    for it in cur.fetchall():
        row = conn.execute("SELECT * FROM items WHERE id = ?", (it["id"],)).fetchone()
        conn.execute(
            """INSERT INTO flashcards(item_id, question_text, answer_text,
                                      chapter_id, topic_id, source_ref, origin,
                                      deck_tag, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                row["id"],
                row["title"] or (row["body"] or "")[:120],
                row["body"],
                row["chapter_id"],
                row["topic_id"],
                row["source_ref"],
                row["origin"],
                "auto",
                _dt.datetime.now().isoformat(timespec="seconds"),
            ),
        )
        total += 1
    conn.commit()
    return total


def record_attempt(conn, flashcard_id=None, kind="flashcard", correct=None,
                   time_seconds=None, confidence=None):
    """Write an attempts row for a flashcard review."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS attempts(
            id INTEGER PRIMARY KEY, question_id TEXT, variant_id INTEGER,
            flashcard_id INTEGER, kind TEXT, qtype TEXT, correct INT,
            marks_obtained REAL, marks_max REAL, time_seconds INT,
            confidence INT, mistakes_json TEXT, exam_session_id TEXT,
            created_at TEXT)"""
    )
    conn.execute(
        """INSERT INTO attempts(flashcard_id, kind, correct, time_seconds,
                                confidence, created_at)
           VALUES (?,?,?,?,?,?)""",
        (
            flashcard_id,
            kind,
            correct,
            time_seconds,
            confidence,
            _dt.datetime.now().isoformat(timespec="seconds"),
        ),
    )
    # commit left to caller (review_card commits)


def deck_stats(conn, chapter_id=None, topic_id=None, deck_tag=None):
    """Return {total, due, new, lapses} counts for a deck selection."""
    _ensure_schema(conn)
    clauses, params = [], []
    if chapter_id is not None:
        clauses.append("f.chapter_id = ?"); params.append(chapter_id)
    if topic_id is not None:
        clauses.append("f.topic_id = ?"); params.append(topic_id)
    if deck_tag is not None:
        clauses.append("f.deck_tag = ?"); params.append(deck_tag)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    total = conn.execute(f"SELECT COUNT(*) c FROM flashcards f {where}", params).fetchone()["c"]
    today = _today().isoformat()
    due = conn.execute(
        f"""SELECT COUNT(*) c FROM flashcards f
            LEFT JOIN sr_reviews s ON s.card_id = f.id {where}
            {"AND" if where else "WHERE"} (s.next_due IS NULL OR s.next_due <= ?)""",
        params + [today],
    ).fetchone()["c"]
    new = conn.execute(
        f"""SELECT COUNT(*) c FROM flashcards f
            LEFT JOIN sr_reviews s ON s.card_id = f.id {where}
            {"AND" if where else "WHERE"} s.card_id IS NULL""",
        params,
    ).fetchone()["c"]
    lapses = conn.execute(
        f"""SELECT COUNT(*) c FROM flashcards f
            JOIN sr_reviews s ON s.card_id = f.id {where}
            {"AND" if where else "WHERE"} s.lapses > 0""",
        params,
    ).fetchone()["c"]
    return {"total": total, "due": due, "new": new, "lapses": lapses}
