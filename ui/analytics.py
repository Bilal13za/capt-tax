"""Progress Analytics UI.

render(conn): per-topic mastery table WITH the formula shown, attempts over
time, accuracy by question type, study time, and band breakdown with
reasons. Honest empty states throughout — no charts invented from thin air.
"""

try:
    from core import uihelpers as _uihelpers
except Exception:
    _uihelpers = None
try:
    from core import mastery as _mastery
except Exception:
    _mastery = None


def _get_setting(conn, key, default=None):
    if _uihelpers is not None and hasattr(_uihelpers, "get_setting"):
        return _uihelpers.get_setting(conn, key, default)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?",
                           (key,)).fetchone()
        return row[0] if row else default
    except Exception:
        return default


def _q(conn, sql, params=()):
    cur = conn.execute(sql, params)
    cols = [c[0] for c in (cur.description or [])]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _table_exists(conn, name):
    return bool(_q(conn, "SELECT name FROM sqlite_master WHERE type='table' "
                         "AND name=?", (name,)))


def _fmt_hms(seconds):
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return "%dh %02dm" % (h, m) if h else "%dm %02ds" % (m, s)


def render(conn):
    import streamlit as st
    st.header("Progress Analytics")

    has_attempts = (_table_exists(conn, "attempts") and bool(
        _q(conn, "SELECT 1 FROM attempts LIMIT 1")))

    # --- mastery formula (always visible) --------------------------------------
    with st.expander("How mastery is calculated", expanded=not has_attempts):
        formula = getattr(_mastery, "FORMULA_TEXT",
                          "score = 0.40 x recent_accuracy + 0.25 x "
                          "flashcard_recall + 0.20 x calculation_success + "
                          "0.15 x application_success") if _mastery else \
            "Mastery module unavailable."
        st.code(formula)
        st.write(
            "- **recent_accuracy** (weight 0.40): correct rate over your last "
            "10 question attempts on the topic.\n"
            "- **flashcard_recall** (weight 0.25): share of the topic's "
            "flashcards last rated good/easy.\n"
            "- **calculation_success** (weight 0.20): correct rate on "
            "numerical questions.\n"
            "- **application_success** (weight 0.15): correct rate on "
            "scenario / theory / long questions.\n"
            "- Components with no data are excluded and the remaining "
            "weights are renormalised.\n"
            "- Fewer than 3 attempts caps the score at 40 (insufficient "
            "evidence).\n"
            "- Bands: <45 weak · 45–74 developing · ≥75 strong.")

    if not has_attempts:
        st.info("No attempts recorded yet. Solve some questions or review "
                "flashcards and analytics will appear here.")
        return

    # --- per-topic mastery table ----------------------------------------------
    st.subheader("Mastery by topic")
    if _mastery is None:
        st.caption("Mastery module unavailable.")
    else:
        topics = _mastery.all_topic_mastery(conn)
        rows = [{"Topic": m.get("name", tid),
                 "Chapter": m.get("chapter_title") or "",
                 "Score": round(m["score"], 1),
                 "Band": m["band"],
                 "Top reason": m["reasons"][0] if m["reasons"] else ""}
                for tid, m in sorted(topics.items(),
                                     key=lambda kv: kv[1]["score"])]
        st.table(rows)
        bands = {"weak": 0, "developing": 0, "strong": 0}
        for m in topics.values():
            bands[m["band"]] = bands.get(m["band"], 0) + 1
        b1, b2, b3 = st.columns(3)
        b1.metric("🔴 Weak topics", bands["weak"])
        b2.metric("🟡 Developing", bands["developing"])
        b3.metric("🟢 Strong", bands["strong"])
        with st.expander("Why is each topic in its band?"):
            for tid, m in sorted(topics.items(), key=lambda kv: kv[1]["score"]):
                st.write("**%s** (%s, %.0f):" % (m.get("name", tid),
                                                 m["band"], m["score"]))
                for reason in m["reasons"]:
                    st.caption("- " + reason)

    # --- attempts over time ----------------------------------------------------
    st.subheader("Attempts over time")
    per_day = _q(conn, "SELECT date(created_at) AS d, COUNT(*) AS n "
                       "FROM attempts GROUP BY d ORDER BY d")
    if per_day:
        st.bar_chart({r["d"]: r["n"] for r in per_day})
    else:
        st.caption("No attempts yet.")

    # --- accuracy by question type ----------------------------------------------
    st.subheader("Accuracy by question type")
    by_qt = _q(conn, "SELECT qtype, COUNT(*) AS n, "
                     "SUM(CASE WHEN correct=1 THEN 1 ELSE 0 END) AS ok "
                     "FROM attempts WHERE question_id IS NOT NULL "
                     "AND correct IS NOT NULL GROUP BY qtype")
    if by_qt:
        acc = {r["qtype"] or "unknown":
               round(100.0 * (r["ok"] or 0) / r["n"], 1) for r in by_qt}
        st.bar_chart(acc)
        for r in by_qt:
            st.caption("%s: %.1f%% (%d/%d correct)" %
                       (r["qtype"] or "unknown",
                        round(100.0 * (r["ok"] or 0) / r["n"], 1),
                        r["ok"] or 0, r["n"]))
    else:
        st.caption("No marked question attempts yet.")

    # --- study time ---------------------------------------------------------------
    st.subheader("Study time")
    total_seconds = 0
    if _table_exists(conn, "study_sessions"):
        rows = _q(conn, "SELECT started_at, ended_at FROM study_sessions "
                        "WHERE started_at IS NOT NULL AND ended_at IS NOT NULL")
        from datetime import datetime as _dt
        for r in rows:
            try:
                s = _dt.fromisoformat(r["started_at"])
                e = _dt.fromisoformat(r["ended_at"])
                total_seconds += max(0, (e - s).total_seconds())
            except (TypeError, ValueError):
                pass
    exam_seconds = _q(conn, "SELECT SUM(time_seconds) AS s FROM exam_answers")
    total_seconds += int(exam_seconds[0]["s"] or 0) if exam_seconds else 0
    attempt_seconds = _q(conn, "SELECT SUM(time_seconds) AS s FROM attempts "
                               "WHERE exam_session_id IS NULL")
    total_seconds += int(attempt_seconds[0]["s"] or 0) if attempt_seconds else 0
    n_attempts = _q(conn, "SELECT COUNT(*) AS n FROM attempts")
    st.metric("Total recorded study time",
              _fmt_hms(total_seconds))
    st.caption("%d attempt(s) recorded in total." %
               (n_attempts[0]["n"] if n_attempts else 0))

    st.caption("Analytics describe recorded activity only — they are not a "
               "prediction of exam performance.")
