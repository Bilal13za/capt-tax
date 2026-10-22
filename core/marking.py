"""Deterministic marking for question attempts. No streamlit here.

Marking is fully rule-based and inspectable:

- MCQ / True-False: exact normalised match against the stored answer key.
  Full question marks when correct, zero when wrong. Misconception notes
  may be supplied per-option via rubric_json {"misconceptions": {...}}.
- Numerical: compares the submitted value against ``numeric_answer`` within
  ``numeric_tolerance`` (question value, else the marking-rules default),
  after applying a rounding mode. ``alt_answers_json`` lists extra acceptable
  values with notes (each {"value": n, "note": "..."}). Marking is value-only:
  when the student submits just a final number, the feedback always says the
  method was not verified.
- Theory / long / scenario: the app never invents a score. The student
  self-assesses against the rubric and the attempt is stored with
  correct=NULL so no fake score is recorded.

Marking rules are visible and editable via get_marking_rules/set_marking_rules,
persisted under settings key 'marking_rules'.
"""

from __future__ import annotations

import datetime as _dt
import json as _json

DEFAULT_MARKING_RULES = {
    "mcq_full_marks_on_exact": True,
    "numerical_default_tolerance": 1.0,
    "rounding_default": "nearest",
}

_SETTINGS_KEY = "marking_rules"


def _as_dict(row):
    return dict(row) if row is not None else None


def _get_setting(conn, key, default=None):
    try:
        from core import uihelpers as _uh

        if hasattr(_uh, "get_setting"):
            return _uh.get_setting(conn, key, default)
    except Exception:
        pass
    try:
        cur = conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        r = cur.fetchone()
        return r["value"] if r else default
    except Exception:
        return default


def _set_setting(conn, key, value):
    try:
        from core import uihelpers as _uh

        if hasattr(_uh, "set_setting"):
            _uh.set_setting(conn, key, value)
            return
    except Exception:
        pass
    conn.execute(
        "CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


def get_marking_rules(conn):
    """Return the marking rules dict (defaults merged over stored values)."""
    rules = dict(DEFAULT_MARKING_RULES)
    raw = _get_setting(conn, _SETTINGS_KEY, None)
    if raw:
        try:
            stored = _json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(stored, dict):
                rules.update(stored)
        except Exception:
            pass
    return rules


def set_marking_rules(conn, rules):
    """Persist marking rules (dict). Returns the stored dict."""
    merged = dict(DEFAULT_MARKING_RULES)
    merged.update(rules or {})
    _set_setting(conn, _SETTINGS_KEY, _json.dumps(merged))
    return merged


def _norm(s):
    return str(s or "").strip().lower()


def _question_marks(row, rules=None):
    try:
        m = row.get("marks")
    except AttributeError:
        m = None
    if m is None:
        return 1.0
    try:
        return float(m)
    except (TypeError, ValueError):
        return 1.0


def _misconception_note(row, submitted):
    """Look up a per-option misconception note from rubric_json/answer_note."""
    try:
        rubric = _json.loads(row.get("rubric_json") or "{}")
    except Exception:
        rubric = {}
    misc = rubric.get("misconceptions") if isinstance(rubric, dict) else None
    if isinstance(misc, dict):
        for k, v in misc.items():
            if _norm(k) == _norm(submitted):
                return str(v)
    return ""


def mark_mcq(question_row, submitted):
    """Mark an MCQ attempt. Returns (correct_bool, marks, feedback)."""
    row = _as_dict(question_row) or {}
    expected = row.get("mcq_answer")
    rules = {}  # rules hook kept for future partial-credit extensions
    marks_max = _question_marks(row, rules)
    if expected is None or str(expected).strip() == "":
        return (
            False,
            0.0,
            "No answer key stored for this question — cannot be marked. "
            "Ask your teacher or add the key (origin will be recorded).",
        )
    correct = _norm(submitted) == _norm(expected)
    marks = marks_max if correct else 0.0
    if correct:
        feedback = f"Correct — {submitted} matches the key."
    else:
        feedback = f"Incorrect — you chose {submitted!r}; the key says {expected!r}."
        note = _misconception_note(row, submitted)
        if note:
            feedback += f" Common misconception: {note}"
    return correct, marks, feedback


def mark_tf(question_row, submitted):
    """Mark a True/False attempt. Returns (correct_bool, marks, feedback)."""
    row = _as_dict(question_row) or {}
    expected = row.get("mcq_answer")
    if expected is None or str(expected).strip() == "":
        # fall back to alt answers carrying a single boolean value
        try:
            alts = _json.loads(row.get("alt_answers_json") or "[]")
            if isinstance(alts, list) and alts:
                expected = alts[0].get("value")
        except Exception:
            expected = None
    marks_max = _question_marks(row)
    if expected is None or str(expected).strip() == "":
        return (
            False,
            0.0,
            "No answer key stored for this question — cannot be marked.",
        )
    truthy = {"true", "t", "yes", "1"}
    falsy = {"false", "f", "no", "0"}
    s, e = _norm(submitted), _norm(expected)
    if s in truthy:
        s = "true"
    elif s in falsy:
        s = "false"
    if e in truthy:
        e = "true"
    elif e in falsy:
        e = "false"
    correct = s == e
    marks = marks_max if correct else 0.0
    feedback = (
        f"Correct — the statement is {e}."
        if correct
        else f"Incorrect — you said {s}; the key says {e}."
    )
    return correct, marks, feedback


def apply_rounding(value, mode):
    """Round ``value`` per mode: nearest|2dp|integer|none."""
    v = float(value)
    if mode == "2dp":
        return round(v, 2)
    if mode == "integer":
        return float(round(v))
    if mode == "nearest":
        return v
    if mode == "none":
        return v
    raise ValueError(f"unknown rounding mode {mode!r}")


def _alt_answers(row):
    try:
        alts = _json.loads(row.get("alt_answers_json") or "[]")
    except Exception:
        return []
    return alts if isinstance(alts, list) else []


def mark_numerical(question_row, submitted_value, rounding="nearest"):
    """Mark a numerical attempt.

    Returns (correct_bool, marks, first_deviation_note). Compares the
    (rounded) submitted value against numeric_answer within tolerance, and
    against each alt answer. Value-only marking: the note always states the
    method was not verified.
    """
    row = _as_dict(question_row) or {}
    rules = get_marking_rules_from_row(row)
    marks_max = _question_marks(row)

    try:
        submitted = float(submitted_value)
    except (TypeError, ValueError):
        return False, 0.0, (
            f"Could not read {submitted_value!r} as a number. "
            "Enter a numeric value only (method not verified — value only)."
        )

    tol = row.get("numeric_tolerance")
    try:
        tol = float(tol) if tol is not None else None
    except (TypeError, ValueError):
        tol = None
    if tol is None:
        tol = float(rules.get("numerical_default_tolerance", 1.0))

    rounded = apply_rounding(submitted, rounding)

    expected = row.get("numeric_answer")
    candidates = []
    if expected is not None:
        try:
            candidates.append((float(expected), "model answer"))
        except (TypeError, ValueError):
            pass
    for alt in _alt_answers(row):
        try:
            candidates.append((float(alt["value"]), alt.get("note") or "accepted alternative"))
        except (TypeError, ValueError, KeyError):
            continue

    if not candidates:
        return (
            False,
            0.0,
            "No numeric answer stored for this question — cannot be marked. "
            "Method not verified.",
        )

    best = None
    for val, label in candidates:
        diff = abs(rounded - val)
        if best is None or diff < best[0]:
            best = (diff, val, label)
    diff, val, label = best
    correct = diff <= tol
    marks = marks_max if correct else 0.0

    method_note = "Marked on final value only — method not verified."
    if correct:
        note = (
            f"Accepted ({label}): {rounded} is within tolerance {tol} of {val}. "
            + method_note
        )
    else:
        note = (
            f"Outside tolerance: you entered {rounded} (rounding: {rounding}); "
            f"expected {val} ± {tol} (difference {diff}). "
            + method_note
            + " Check this step — a wrong method can still give a near answer."
        )
    return correct, marks, note


def get_marking_rules_from_row(row):
    """Best-effort rules lookup when only a row (no conn) is available."""
    return dict(DEFAULT_MARKING_RULES)


def theory_rubric(question_row):
    """Return the rubric list for self-assessment: [{point, marks}, ...].

    Parsed from rubric_json. Falls back to splitting the solution text into
    bullet-like lines when no structured rubric exists.
    """
    row = _as_dict(question_row) or {}
    try:
        rubric = _json.loads(row.get("rubric_json") or "")
    except Exception:
        rubric = None
    if isinstance(rubric, dict) and isinstance(rubric.get("points"), list):
        return [
            {"point": str(p.get("point", "")), "marks": float(p.get("marks", 0))}
            for p in rubric["points"]
        ]
    if isinstance(rubric, list):
        return [
            {"point": str(p.get("point", "")), "marks": float(p.get("marks", 0))}
            if isinstance(p, dict)
            else {"point": str(p), "marks": 0.0}
            for p in rubric
        ]
    # Fallback: derive candidate points from solution lines.
    solution = row.get("solution") or ""
    lines = [ln.strip(" -•\t") for ln in str(solution).splitlines()]
    lines = [ln for ln in lines if ln]
    return [{"point": ln, "marks": 0.0} for ln in lines]


def record_self_assessment(conn, question_id, points_claimed_json):
    """Store a theory self-assessment attempt.

    ``points_claimed_json``: JSON list of {"point": str, "marks_claimed": float}
    (or a dict). The attempt stores correct=NULL — the app never invents a
    score; marks_obtained holds the student's own claimed total.
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS attempts(
            id INTEGER PRIMARY KEY, question_id TEXT, variant_id INTEGER,
            flashcard_id INTEGER, kind TEXT, qtype TEXT, correct INT,
            marks_obtained REAL, marks_max REAL, time_seconds INT,
            confidence INT, mistakes_json TEXT, exam_session_id TEXT,
            created_at TEXT)"""
    )
    q = conn.execute(
        "SELECT qtype, marks FROM questions WHERE id = ?", (question_id,)
    ).fetchone()
    qtype = q["qtype"] if q and q["qtype"] else "theory"
    try:
        marks_max = float(q["marks"]) if q and q["marks"] is not None else None
    except (TypeError, ValueError):
        marks_max = None

    claimed = 0.0
    try:
        data = _json.loads(points_claimed_json) if isinstance(points_claimed_json, str) else points_claimed_json
        items = data if isinstance(data, list) else data.get("points", [])
        for p in items:
            claimed += float(p.get("marks_claimed", 0) or 0)
    except Exception:
        pass

    conn.execute(
        """INSERT INTO attempts(question_id, kind, qtype, correct,
                                marks_obtained, marks_max, mistakes_json,
                                created_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            question_id,
            "theory",
            qtype,
            None,  # correct=NULL: self-assessed, never auto-scored
            claimed,
            marks_max,
            points_claimed_json if isinstance(points_claimed_json, str)
            else _json.dumps(points_claimed_json),
            _dt.datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()


def record_attempt(conn, question_id=None, variant_id=None, flashcard_id=None,
                   kind=None, qtype=None, correct=None, marks_obtained=None,
                   marks_max=None, time_seconds=None, confidence=None,
                   mistakes_json=None, exam_session_id=None):
    """Central writer for the attempts table. Returns the new row id."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS attempts(
            id INTEGER PRIMARY KEY, question_id TEXT, variant_id INTEGER,
            flashcard_id INTEGER, kind TEXT, qtype TEXT, correct INT,
            marks_obtained REAL, marks_max REAL, time_seconds INT,
            confidence INT, mistakes_json TEXT, exam_session_id TEXT,
            created_at TEXT)"""
    )
    if isinstance(mistakes_json, (dict, list)):
        mistakes_json = _json.dumps(mistakes_json)
    cur = conn.execute(
        """INSERT INTO attempts(question_id, variant_id, flashcard_id, kind,
                                qtype, correct, marks_obtained, marks_max,
                                time_seconds, confidence, mistakes_json,
                                exam_session_id, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            question_id, variant_id, flashcard_id, kind, qtype,
            None if correct is None else int(bool(correct)),
            marks_obtained, marks_max, time_seconds, confidence,
            mistakes_json, exam_session_id,
            _dt.datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return cur.lastrowid
