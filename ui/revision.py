"""Revision Planner UI.

render(conn): topics ordered by mastery (weak first) with band + reasons,
due-flashcard counts, missed questions, and a deterministic revision queue
the student can override/dismiss.

Dismissal storage choice (documented): dismissed recommendation ids are kept
in the settings table under key 'dismissed_recs' as a JSON list. A "Restore
dismissed" button clears it. Student notes on rules live on the tax_rules
row itself (see ui/rules.py) — recommendations are ephemeral UI state, so
settings is the right home.
"""

import json
from datetime import datetime

try:
    from core import uihelpers as _uihelpers
except Exception:
    _uihelpers = None
try:
    from core import mastery as _mastery
except Exception:
    _mastery = None

DISMISSED_KEY = "dismissed_recs"


def _get_setting(conn, key, default=None):
    if _uihelpers is not None and hasattr(_uihelpers, "get_setting"):
        return _uihelpers.get_setting(conn, key, default)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?",
                           (key,)).fetchone()
        return row[0] if row else default
    except Exception:
        return default


def _set_setting(conn, key, value):
    if _uihelpers is not None and hasattr(_uihelpers, "set_setting"):
        _uihelpers.set_setting(conn, key, value)
        return
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, value))
    conn.commit()


def _q(conn, sql, params=()):
    cur = conn.execute(sql, params)
    cols = [c[0] for c in (cur.description or [])]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _due_flashcards(conn):
    try:
        rows = _q(conn, "SELECT COUNT(*) AS n FROM sr_reviews "
                        "WHERE date(next_due) <= date('now')")
        return int(rows[0]["n"]) if rows else 0
    except Exception:
        return 0


def _missed_questions(conn):
    """Questions whose latest attempt was incorrect."""
    try:
        rows = _q(conn, "SELECT a.question_id, a.id FROM attempts a "
                        "WHERE a.question_id IS NOT NULL")
    except Exception:
        return []
    latest = {}
    for r in rows:
        qid = r["question_id"]
        if qid not in latest or r["id"] > latest[qid]["id"]:
            latest[qid] = r["id"]
    if not latest:
        return []
    missed_ids = [qid for qid, aid in latest.items()
                  if _q(conn, "SELECT correct FROM attempts WHERE id=?",
                         (aid,))[0]["correct"] == 0]
    if not missed_ids:
        return []
    qs = _q(conn, "SELECT id, statement, chapter_id, topic_id, qtype, "
                  "page_start, page_end FROM questions WHERE id IN (%s)" %
            ",".join("?" * len(missed_ids)), missed_ids)
    return qs


def _dismissed(conn):
    raw = _get_setting(conn, DISMISSED_KEY, "[]")
    try:
        return set(json.loads(raw or "[]"))
    except (ValueError, TypeError):
        return set()


def _dismiss(conn, rec_id):
    dismissed = _dismissed(conn)
    dismissed.add(rec_id)
    _set_setting(conn, DISMISSED_KEY, json.dumps(sorted(dismissed)))


def _build_queue(conn):
    """Deterministic revision queue: list of (rec_id, label, detail)."""
    queue = []
    if _mastery is not None:
        try:
            topics = _mastery.all_topic_mastery(conn)
        except Exception:
            topics = {}
        for tid, m in sorted(topics.items(), key=lambda kv: kv[1]["score"]):
            if m["band"] == "weak":
                queue.append(("topic:%s" % tid,
                              "Revise weak topic: %s" % m.get("name", tid),
                              "Mastery %.0f%% — %s" % (
                                  m["score"],
                                  "; ".join(m["reasons"][:2]))))
    due = _due_flashcards(conn)
    if due:
        queue.append(("flashcards:due",
                      "Review %d due flashcard%s" % (due, "" if due == 1 else "s"),
                      "Spaced-repetition cards due today or overdue."))
    for q in _missed_questions(conn)[:10]:
        queue.append(("missed:%s" % q["id"],
                      "Reattempt missed question (%s)" % (q.get("qtype") or "?"),
                      (q.get("statement") or "")[:120]))
    return queue


def _band_chip(band):
    return {"weak": "🔴 weak", "developing": "🟡 developing",
            "strong": "🟢 strong"}.get(band, band)


def render(conn):
    import streamlit as st
    st.header("Revision Planner")
    st.caption("Ordered by mastery — weakest first. Dismiss any "
               "recommendation you disagree with; dismissed items are stored "
               "in settings key '%s' and can be restored." % DISMISSED_KEY)

    dismissed = _dismissed(conn)

    # --- topics by mastery ---------------------------------------------------
    st.subheader("Topics by mastery")
    if _mastery is None:
        st.caption("Mastery module unavailable — topics listed in chapter order.")
        topics = _q(conn, "SELECT t.id, t.name, c.title AS ch FROM topics t "
                          "LEFT JOIN chapters c ON c.id=t.chapter_id "
                          "ORDER BY c.number, t.sort_order")
        for t in topics:
            st.write("- %s (%s)" % (t["name"], t.get("ch") or ""))
    else:
        topics = _mastery.all_topic_mastery(conn)
        if not topics:
            st.caption("No topics in the syllabus yet.")
        for tid, m in sorted(topics.items(), key=lambda kv: kv[1]["score"]):
            with st.expander("%s  %s" % (_band_chip(m["band"]),
                                         m.get("name", tid))):
                st.write("Score: **%.1f / 100**" % m["score"])
                st.caption("Formula: score = 0.40×recent accuracy + "
                           "0.25×flashcard recall + 0.20×calculation success "
                           "+ 0.15×application success "
                           "(missing parts excluded, weights renormalised; "
                           "<3 attempts caps the score at 40).")
                for reason in m["reasons"]:
                    st.write("- " + reason)

    # --- due flashcards / missed questions ------------------------------------
    c1, c2 = st.columns(2)
    c1.metric("Due flashcards", _due_flashcards(conn))
    c2.metric("Missed questions", len(_missed_questions(conn)))

    missed = _missed_questions(conn)
    if missed:
        st.subheader("Missed questions")
        for q in missed:
            with st.expander((q.get("statement") or q["id"])[:90]):
                st.write(q.get("statement") or "")
                ps, pe = q.get("page_start"), q.get("page_end")
                if ps:
                    st.caption("Source: p. %s%s — open the Study workspace "
                               "to view the source page."
                               % (ps, "–%s" % pe if pe and pe != ps else ""))
    else:
        st.caption("No missed questions on record — nothing to reattempt.")

    # --- revision queue --------------------------------------------------------
    st.subheader("Revision queue")
    queue = [rec for rec in _build_queue(conn) if rec[0] not in dismissed]
    if not queue:
        st.caption("Queue is empty — either everything is covered or every "
                   "recommendation was dismissed.")
    for rec_id, label, detail in queue:
        cols = st.columns([6, 1])
        cols[0].write("**%s**" % label)
        cols[0].caption(detail)
        if cols[1].button("Dismiss", key="dis_%s" % rec_id):
            _dismiss(conn, rec_id)
            st.rerun()

    if dismissed and st.button("Restore dismissed recommendations"):
        _set_setting(conn, DISMISSED_KEY, "[]")
        st.rerun()

    st.caption("Generated %s · deterministic from your attempts and reviews." %
               datetime.now().strftime("%Y-%m-%d %H:%M"))
