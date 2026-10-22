"""Dashboard UI.

render(conn): continue-studying card, today's plan items, due-flashcard
count, weak topics, recent exam results, syllabus coverage, upcoming
revision. Every teammate dependency is imported under guard so the
dashboard works even if core/sr.py, core/mastery.py or core/uihelpers.py
are missing.
"""

from datetime import date

# --- guarded imports: dashboard must work without teammates' modules --------
try:
    from core import sr as _sr
except Exception:
    _sr = None
try:
    from core import mastery as _mastery
except Exception:
    _mastery = None
try:
    from core import planner as _planner
except Exception:
    _planner = None
try:
    from core import uihelpers as _uihelpers
except Exception:
    _uihelpers = None


def _q(conn, sql, params=()):
    cur = conn.execute(sql, params)
    cols = [c[0] for c in (cur.description or [])]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _table_exists(conn, name):
    return bool(_q(conn, "SELECT name FROM sqlite_master WHERE type='table' "
                         "AND name=?", (name,)))


def _get_setting(conn, key, default=None):
    if _uihelpers is not None and hasattr(_uihelpers, "get_setting"):
        try:
            return _uihelpers.get_setting(conn, key, default)
        except Exception:
            pass
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?",
                           (key,)).fetchone()
        return row[0] if row else default
    except Exception:
        return default


def _is_demo(conn):
    if _uihelpers is not None and hasattr(_uihelpers, "is_demo_book"):
        try:
            return bool(_uihelpers.is_demo_book(conn))
        except Exception:
            pass
    title = str(_get_setting(conn, "book_title", "") or "")
    note = str(_get_setting(conn, "tax_context_note", "") or "")
    return "DEMO" in title.upper() or "SYNTHETIC DEMO" in note.upper()


def _due_flashcard_count(conn):
    if _sr is not None and hasattr(_sr, "due_cards"):
        try:
            return len(_sr.due_cards(conn))
        except Exception:
            pass
    if not _table_exists(conn, "sr_reviews"):
        return 0
    try:
        rows = _q(conn, "SELECT COUNT(*) AS n FROM sr_reviews "
                        "WHERE date(next_due) <= date('now')")
        return int(rows[0]["n"]) if rows else 0
    except Exception:
        return 0


def _weak_topics(conn, limit=5):
    if _mastery is None:
        return []
    try:
        topics = _mastery.all_topic_mastery(conn)
    except Exception:
        return []
    weak = [(tid, m) for tid, m in topics.items() if m["band"] == "weak"]
    weak.sort(key=lambda kv: kv[1]["score"])
    return weak[:limit]


def _recent_exams(conn, limit=3):
    if not _table_exists(conn, "exam_sessions"):
        return []
    return _q(conn, "SELECT id, title, submitted_at, total_marks, obtained "
                    "FROM exam_sessions WHERE status='submitted' "
                    "ORDER BY id DESC LIMIT ?", (limit,))


def _coverage(conn):
    """(topics_with_attempts, total_topics)."""
    if not _table_exists(conn, "topics"):
        return 0, 0
    total = _q(conn, "SELECT COUNT(*) AS n FROM topics")
    total = int(total[0]["n"]) if total else 0
    if not _table_exists(conn, "attempts") or not _table_exists(conn, "questions"):
        return 0, total
    rows = _q(conn, "SELECT COUNT(DISTINCT q.topic_id) AS n FROM attempts a "
                    "JOIN questions q ON q.id=a.question_id "
                    "WHERE q.topic_id IS NOT NULL")
    return (int(rows[0]["n"]) if rows and rows[0]["n"] else 0), total


def _last_attempt_topic(conn):
    if not _table_exists(conn, "attempts"):
        return None
    rows = _q(conn, "SELECT a.created_at, q.topic_id, t.name FROM attempts a "
                    "LEFT JOIN questions q ON q.id=a.question_id "
                    "LEFT JOIN topics t ON t.id=q.topic_id "
                    "WHERE a.question_id IS NOT NULL "
                    "ORDER BY a.created_at DESC, a.id DESC LIMIT 1")
    return rows[0] if rows else None


def render(conn):
    import streamlit as st
    if _is_demo(conn):
        st.warning("DEMO content pack — synthetic data for development, "
                   "not real tax material.")
    st.header("Dashboard")

    exam_date = _get_setting(conn, "exam_date", "2027-02-06")
    try:
        days_left = (date.fromisoformat(exam_date) - date.today()).days
        st.caption("CAF-2 exam: %s — %d day(s) to go." % (exam_date, days_left))
    except (TypeError, ValueError):
        st.caption("Exam date not set.")

    # --- continue studying ----------------------------------------------------
    st.subheader("Continue studying")
    continued = False
    if _planner is not None:
        try:
            nxt = _planner.next_pending_item(conn)
        except Exception:
            nxt = None
        if nxt:
            st.write("Next up: **%s** (%s)" % (nxt["activity"], nxt["day_date"]))
            st.caption("Open the Planner to work through it.")
            continued = True
    if not continued:
        last = _last_attempt_topic(conn)
        if last and last.get("topic_id"):
            st.write("Last attempted topic: **%s**" % (last.get("name") or
                                                       last["topic_id"]))
            st.caption("Pick it up in the Study workspace or start a mock exam.")
        else:
            st.caption("Nothing studied yet — generate a plan in the Planner "
                       "to get started.")

    c1, c2, c3 = st.columns(3)
    c1.metric("Due flashcards", _due_flashcard_count(conn))
    covered, total = _coverage(conn)
    c2.metric("Syllabus coverage", "%d / %d topics" % (covered, total))
    recent = _recent_exams(conn)
    c3.metric("Mock exams taken", len(recent))

    # --- today's plan -----------------------------------------------------------
    st.subheader("Today's plan")
    if _planner is not None:
        try:
            items = _planner.today_items(conn)
        except Exception:
            items = []
        if items:
            for it in items:
                st.write("- **%s** (%s)" % (it["activity"], it["status"]))
        else:
            st.caption("Nothing scheduled for today.")
    else:
        st.caption("Planner module unavailable.")

    # --- weak topics --------------------------------------------------------------
    st.subheader("Weak topics")
    weak = _weak_topics(conn)
    if _mastery is None:
        st.caption("Mastery module unavailable.")
    elif not weak:
        st.caption("No weak topics right now. Keep practising.")
    else:
        for tid, m in weak:
            st.write("- %s (%.0f/100)" % (m.get("name", tid), m["score"]))

    # --- recent exams ---------------------------------------------------------------
    st.subheader("Recent mock exams")
    if not recent:
        st.caption("No submitted mock exams yet.")
    for s in recent:
        pct = (100.0 * (s["obtained"] or 0) / s["total_marks"]
               if s["total_marks"] else 0.0)
        st.write("- **%s**: %.1f/%.1f (%.0f%%)" %
                 (s["title"], s["obtained"] or 0, s["total_marks"] or 0, pct))

    # --- upcoming revision ------------------------------------------------------------
    st.subheader("Upcoming revision")
    if _planner is not None:
        try:
            plan = _planner.active_plan(conn)
            upcoming = _q(conn, "SELECT day_date, activity FROM plan_items "
                                "WHERE plan_id=? AND day_date>? AND "
                                "status='pending' ORDER BY day_date, id LIMIT 5",
                          (plan["id"], date.today().isoformat())) if plan else []
        except Exception:
            upcoming = []
        if upcoming:
            for u in upcoming:
                st.write("- %s: %s" % (u["day_date"], u["activity"]))
        else:
            st.caption("Nothing scheduled ahead — generate or extend your plan.")
    else:
        st.caption("Planner module unavailable.")
