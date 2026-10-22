"""Mock-exam engine for the CAPT Taxation Exam Preparation System.

No streamlit here — pure logic over a sqlite3 connection. Works with any
connection whose schema matches the project schema contract.

Auto-marking helpers (mark_mcq / mark_tf / mark_numerical / mark_short /
auto_mark_question) are LOCAL equivalents of the learning-engine team's
core/marking.py. They exist so the exam UI works even if core/marking.py is
not present yet. If core/marking.py IS present, the UI should prefer it;
submit_exam() takes any mark_fn(question_row, answer) -> (correct, marks_obtained).
"""

import hashlib
import json
import random
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row_to_dict(row):
    return dict(row) if row is not None else None


def _q(conn, sql, params=()):
    # Side-effect free: never mutates conn.row_factory, so a connection
    # shared with other teams' code is left untouched.
    cur = conn.execute(sql, params)
    cols = [c[0] for c in (cur.description or [])]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _parse_json(value, default=None):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def _seed_from(title, blueprint):
    raw = json.dumps({"title": title, "blueprint": blueprint}, sort_keys=True,
                     default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return int(digest, 16) % (2 ** 32)


def _question_marks(q):
    """Marks a question is worth; NULL marks count as 1 (documented default)."""
    try:
        m = float(q.get("marks")) if q.get("marks") is not None else 1.0
    except (TypeError, ValueError):
        m = 1.0
    return m


# ---------------------------------------------------------------------------
# local auto-marking (equivalent of core/marking.py — see module docstring)
# ---------------------------------------------------------------------------

def mark_mcq(question, answer):
    expected = (question.get("mcq_answer") or "").strip()
    given = "" if answer is None else str(answer).strip()
    if not expected:
        return None  # no answer key -> cannot auto-mark
    return 1 if given.lower() == expected.lower() else 0


def mark_tf(question, answer):
    # mcq_answer holds 'True'/'False' for tf questions in this app.
    expected = (question.get("mcq_answer") or "").strip().lower()
    given = "" if answer is None else str(answer).strip().lower()
    if expected not in ("true", "false"):
        return None
    norm = {"t": "true", "f": "false"}.get(given, given)
    return 1 if norm == expected else 0


def mark_numerical(question, answer):
    try:
        expected = float(question.get("numeric_answer"))
    except (TypeError, ValueError):
        return None
    try:
        given = float(str(answer).strip())
    except (TypeError, ValueError, AttributeError):
        return 0
    try:
        tol = float(question.get("numeric_tolerance") or 0)
    except (TypeError, ValueError):
        tol = 0
    return 1 if abs(given - expected) <= tol else 0


def mark_short(question, answer):
    given = "" if answer is None else str(answer).strip().lower()
    if not given:
        return 0
    alts = _parse_json(question.get("alt_answers_json"), []) or []
    for alt in alts:
        if given == str(alt).strip().lower():
            return 1
    # also accept the stored numeric answer wording if present
    key = (question.get("mcq_answer") or "").strip().lower()
    if key and given == key:
        return 1
    return None  # free text with no key -> needs human review


def auto_mark_question(question, answer):
    """Return (correct, marks_obtained).

    correct is 1 / 0 / None (None = needs manual review).
    theory / scenario / long answers are never auto-marked.
    """
    qtype = (question.get("qtype") or "").strip().lower()
    marks = _question_marks(question)
    if qtype == "mcq":
        c = mark_mcq(question, answer)
    elif qtype == "tf":
        c = mark_tf(question, answer)
    elif qtype == "numerical":
        c = mark_numerical(question, answer)
    elif qtype == "short":
        c = mark_short(question, answer)
    else:  # theory, scenario, long -> human review
        c = None
    if c is None:
        return None, 0.0
    return c, (marks if c else 0.0)


# ---------------------------------------------------------------------------
# exam building
# ---------------------------------------------------------------------------

def _attempt_sets(conn):
    """Return (attempted_ids, incorrect_ids) based on the latest attempt."""
    attempted = set()
    incorrect = set()
    try:
        rows = _q(conn, "SELECT question_id, correct, id FROM attempts "
                        "WHERE question_id IS NOT NULL")
    except Exception:
        return attempted, incorrect
    latest = {}
    for r in rows:
        qid = r["question_id"]
        if qid not in latest or r["id"] > latest[qid]["id"]:
            latest[qid] = r
    for qid, r in latest.items():
        attempted.add(qid)
        if r["correct"] == 0:
            incorrect.add(qid)
    return attempted, incorrect


def build_exam(conn, title, mode, blueprint):
    """Build a mock exam session.

    blueprint = {"chapters": [... ] | "all", "qtypes": [...], "difficulty": [...],
                 "count": N, "marks_limit": M, "include_incorrect": bool,
                 "include_unattempted": bool, "time_minutes": T}

    Deterministic: the same title + blueprint always selects the same
    questions (seeded shuffle). Raises ValueError when the question bank
    cannot satisfy the blueprint. Returns (session_id, question_ids).
    """
    if mode not in ("timed", "untimed"):
        raise ValueError("mode must be 'timed' or 'untimed'")
    bp = dict(blueprint or {})
    count = int(bp.get("count") or 0)
    if count <= 0:
        raise ValueError("blueprint 'count' must be a positive integer")
    marks_limit = bp.get("marks_limit")
    marks_limit = float(marks_limit) if marks_limit not in (None, "") else None

    chapters = bp.get("chapters") or "all"
    qtypes = [t for t in (bp.get("qtypes") or []) if t]
    difficulties = [d for d in (bp.get("difficulty") or []) if d]
    include_incorrect = bool(bp.get("include_incorrect", True))
    include_unattempted = bool(bp.get("include_unattempted", True))

    sql = ("SELECT * FROM questions WHERE 1=1")
    params = []
    if chapters != "all" and chapters:
        sql += " AND chapter_id IN (%s)" % ",".join("?" * len(chapters))
        params.extend(chapters)
    if qtypes:
        sql += " AND qtype IN (%s)" % ",".join("?" * len(qtypes))
        params.extend(qtypes)
    if difficulties:
        sql += " AND difficulty IN (%s)" % ",".join("?" * len(difficulties))
        params.extend(difficulties)
    pool = _q(conn, sql, params)

    attempted, incorrect = _attempt_sets(conn)
    if not include_unattempted:
        pool = [q for q in pool if q["id"] in attempted]
    if not include_incorrect:
        pool = [q for q in pool if q["id"] not in incorrect]

    if len(pool) < count:
        raise ValueError(
            "Question bank too small: blueprint needs %d questions but only "
            "%d match the filters (chapters=%s, qtypes=%s, difficulty=%s, "
            "include_incorrect=%s, include_unattempted=%s)." % (
                count, len(pool), chapters, qtypes or "any",
                difficulties or "any", include_incorrect, include_unattempted))

    rng = random.Random(_seed_from(title, bp))
    order = list(pool)
    rng.shuffle(order)

    selected = []
    total_marks = 0.0
    for q in order:
        if len(selected) >= count:
            break
        m = _question_marks(q)
        if marks_limit is not None and total_marks + m > marks_limit:
            continue  # skip questions that would bust the marks budget
        selected.append(q)
        total_marks += m
    if len(selected) < count:
        raise ValueError(
            "Question bank too small: could only fit %d of %d requested "
            "questions within marks_limit=%s." % (len(selected), count,
                                                  marks_limit))

    question_ids = [q["id"] for q in selected]
    stored_bp = dict(bp)
    stored_bp["question_ids"] = question_ids
    now = _now_iso()
    cur = conn.execute(
        "INSERT INTO exam_sessions (title, mode, blueprint_json, starts_at, "
        "status, total_marks) VALUES (?, ?, ?, ?, 'in_progress', ?)",
        (title, mode, json.dumps(stored_bp), now, total_marks))
    conn.commit()
    return cur.lastrowid, question_ids


# ---------------------------------------------------------------------------
# answering / submitting
# ---------------------------------------------------------------------------

def save_answer(conn, session_id, question_id, answer_json, time_seconds,
                variant_id=None):
    """Autosave one answer (upsert on session_id + question_id)."""
    payload = answer_json if isinstance(answer_json, str) else json.dumps(answer_json)
    now = _now_iso()
    existing = _q(conn, "SELECT id FROM exam_answers WHERE session_id=? AND "
                        "question_id=?", (session_id, question_id))
    if existing:
        conn.execute("UPDATE exam_answers SET answer_json=?, time_seconds=?, "
                     "variant_id=?, created_at=? WHERE id=?",
                     (payload, time_seconds, variant_id, now, existing[0]["id"]))
    else:
        conn.execute("INSERT INTO exam_answers (session_id, question_id, "
                     "variant_id, answer_json, time_seconds, created_at) "
                     "VALUES (?, ?, ?, ?, ?, ?)",
                     (session_id, question_id, variant_id, payload,
                      time_seconds, now))
    conn.commit()


def _session_question_ids(conn, session):
    stored = _parse_json(session.get("blueprint_json"), {}) or {}
    ids = stored.get("question_ids") or []
    return stored, ids


def submit_exam(conn, session_id, mark_fn):
    """Mark, close and mirror an exam session.

    mark_fn(question_row_dict, answer) -> (correct, marks_obtained);
    correct may be None (needs manual review).
    Returns the summary dict (same shape as exam_summary()).
    """
    sessions = _q(conn, "SELECT * FROM exam_sessions WHERE id=?", (session_id,))
    if not sessions:
        raise ValueError("No exam session with id %r" % (session_id,))
    session = sessions[0]
    if session.get("status") == "submitted":
        return exam_summary(conn, session_id)

    stored, question_ids = _session_question_ids(conn, session)
    questions = {q["id"]: q for q in
                 _q(conn, "SELECT * FROM questions WHERE id IN (%s)" %
                    ",".join("?" * len(question_ids)), question_ids)} \
        if question_ids else {}
    answers = {a["question_id"]: a for a in
               _q(conn, "SELECT * FROM exam_answers WHERE session_id=?",
                  (session_id,))}

    total = 0.0
    obtained = 0.0
    now = _now_iso()
    for qid in question_ids:
        q = questions.get(qid)
        if q is None:
            continue
        marks = _question_marks(q)
        total += marks
        ans = answers.get(qid)
        if ans is None or ans.get("answer_json") in (None, ""):
            correct, got = None, 0.0
            answer_val = None
        else:
            answer_val = _parse_json(ans["answer_json"], ans["answer_json"])
            correct, got = mark_fn(q, answer_val)
            got = float(got or 0.0)
        obtained += got
        if ans is None:
            conn.execute("INSERT INTO exam_answers (session_id, question_id, "
                         "answer_json, correct, marks_obtained, time_seconds, "
                         "created_at) VALUES (?, ?, NULL, ?, ?, 0, ?)",
                         (session_id, qid, correct, got, now))
        else:
            conn.execute("UPDATE exam_answers SET correct=?, marks_obtained=? "
                         "WHERE id=?", (correct, got, ans["id"]))
        # mirror into attempts(kind='exam')
        conn.execute("INSERT INTO attempts (question_id, variant_id, kind, "
                     "qtype, correct, marks_obtained, marks_max, time_seconds, "
                     "exam_session_id, created_at) VALUES (?, ?, 'exam', ?, "
                     "?, ?, ?, ?, ?, ?)",
                     (qid, ans.get("variant_id") if ans else None,
                      q.get("qtype"), correct, got, marks,
                      ans.get("time_seconds") if ans else 0, session_id, now))

    conn.execute("UPDATE exam_sessions SET submitted_at=?, ends_at=?, "
                 "status='submitted', total_marks=?, obtained=? WHERE id=?",
                 (now, now, total, obtained, session_id))
    conn.commit()
    return exam_summary(conn, session_id)


def exam_summary(conn, session_id):
    """Summary dict for a session — submitted or still in_progress.

    Shape: {"session_id", "title", "mode", "status", "total", "obtained",
            "answered", "count", "pending_review": [...],
            "by_chapter": {cid: {"total","obtained","count"}},
            "by_topic": {tid: {...}}, "by_qtype": {qt: {"total","obtained",
            "count","accuracy"}}, "time": {"total_seconds","avg_seconds",
            "unanswered"}, "missed": [question_ids]}
    """
    sessions = _q(conn, "SELECT * FROM exam_sessions WHERE id=?", (session_id,))
    if not sessions:
        raise ValueError("No exam session with id %r" % (session_id,))
    session = sessions[0]
    stored, question_ids = _session_question_ids(conn, session)
    questions = {q["id"]: q for q in
                 _q(conn, "SELECT * FROM questions WHERE id IN (%s)" %
                    ",".join("?" * len(question_ids)), question_ids)} \
        if question_ids else {}
    answers = {a["question_id"]: a for a in
               _q(conn, "SELECT * FROM exam_answers WHERE session_id=?",
                  (session_id,))}

    total = 0.0
    obtained = 0.0
    answered = 0
    missed = []
    pending_review = []
    by_chapter, by_topic, by_qtype = {}, {}, {}
    time_total = 0

    for qid in question_ids:
        q = questions.get(qid)
        if q is None:
            continue
        marks = _question_marks(q)
        total += marks
        ans = answers.get(qid)
        has_answer = ans is not None and ans.get("answer_json") not in (None, "")
        if has_answer:
            answered += 1
        time_total += int(ans.get("time_seconds") or 0) if ans else 0
        got = float(ans.get("marks_obtained") or 0.0) if ans else 0.0
        if session.get("status") == "submitted":
            obtained += got
        correct = ans.get("correct") if ans else None
        if session.get("status") == "submitted":
            if has_answer and correct == 0:
                missed.append(qid)
            if has_answer and correct is None:
                pending_review.append(qid)

        for bucket, key in ((by_chapter, q.get("chapter_id") or "uncategorized"),
                            (by_topic, q.get("topic_id") or "uncategorized"),
                            (by_qtype, q.get("qtype") or "unknown")):
            b = bucket.setdefault(key, {"total": 0.0, "obtained": 0.0,
                                        "count": 0})
            b["total"] += marks
            b["obtained"] += got
            b["count"] += 1

    for b in by_qtype.values():
        b["accuracy"] = round(100.0 * b["obtained"] / b["total"], 1) \
            if b["total"] else 0.0

    return {
        "session_id": session_id,
        "title": session.get("title"),
        "mode": session.get("mode"),
        "status": session.get("status"),
        "total": round(total, 2),
        "obtained": round(obtained, 2) if session.get("status") == "submitted" else None,
        "answered": answered,
        "count": len(question_ids),
        "pending_review": pending_review,
        "by_chapter": by_chapter,
        "by_topic": by_topic,
        "by_qtype": by_qtype,
        "time": {"total_seconds": time_total,
                 "avg_seconds": round(time_total / answered, 1) if answered else 0.0,
                 "unanswered": len(question_ids) - answered},
        "missed": missed,
    }


def list_sessions(conn, status=None, limit=50):
    """Past sessions, newest first (for the review list)."""
    sql = "SELECT * FROM exam_sessions"
    params = []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return _q(conn, sql, params)
