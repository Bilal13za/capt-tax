"""Mock Examinations UI.

render(conn): blueprint builder -> timed/untimed exam navigator -> review ->
results, plus a past-sessions list with re-review.

Teammate-module policy (documented here): core/uihelpers.py (foundation) and
core/marking.py (learning-engine) may not exist yet. Both are imported under
guard; when missing, local fallbacks are used. Marking preference order:
core/marking.py when present, else the local equivalents in core/exams.py
(which mirror the marking contract).
"""

import json
from datetime import datetime, timezone

from core.exams import (build_exam, save_answer, submit_exam, exam_summary,
                        list_sessions, auto_mark_question)

# --- guarded teammate modules -------------------------------------------------
try:
    from core import uihelpers as _uihelpers
except Exception:
    _uihelpers = None
try:
    from core import marking as _marking
except Exception:
    _marking = None

QTYPES = ["mcq", "tf", "short", "theory", "numerical", "scenario", "long"]


# --- local fallbacks ----------------------------------------------------------

def _get_setting(conn, key, default=None):
    if _uihelpers is not None and hasattr(_uihelpers, "get_setting"):
        return _uihelpers.get_setting(conn, key, default)
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


def _demo_banner(conn, st):
    if _uihelpers is not None and hasattr(_uihelpers, "demo_banner"):
        try:
            _uihelpers.demo_banner(conn)
            return
        except Exception:
            pass
    if _is_demo(conn):
        st.warning("DEMO content pack — synthetic data for development, "
                   "not real tax material.")


def _chapter_options(conn):
    if _uihelpers is not None and hasattr(_uihelpers, "chapter_options"):
        try:
            return _uihelpers.chapter_options(conn)
        except Exception:
            pass
    try:
        rows = conn.execute("SELECT id, number, title FROM chapters "
                            "ORDER BY number").fetchall()
        return [("ch%s" % r[0], "Ch %s — %s" % (r[1], r[2])) for r in rows]
    except Exception:
        return []


def _chapter_title(conn, chapter_id):
    for cid, label in _chapter_options(conn):
        if cid == chapter_id:
            return label
    return chapter_id or "—"


def _source_line(q):
    ps, pe = q.get("page_start"), q.get("page_end")
    if ps and pe and pe != ps:
        return "Source: pp. %s–%s" % (ps, pe)
    if ps:
        return "Source: p. %s" % ps
    return "Source page not recorded"


def _mark_fn(question, answer):
    """mark_fn for submit_exam: (question_dict, answer) -> (correct, marks).

    Prefers the learning-engine team's core/marking.py per-question-type
    functions when present (they return (correct_bool, marks, feedback);
    the feedback is surfaced in the question workspace, not the exam
    summary). Falls back to the local equivalents in core/exams.py.
    Theory / scenario / long answers are never auto-marked (correct=None
    -> "needs manual review").
    """
    qtype = (question.get("qtype") or "").lower()
    if _marking is not None:
        try:
            if qtype == "mcq" and hasattr(_marking, "mark_mcq"):
                c, m, _fb = _marking.mark_mcq(question, answer)
                return (1 if c else 0), float(m)
            if qtype == "tf" and hasattr(_marking, "mark_tf"):
                c, m, _fb = _marking.mark_tf(question, answer)
                return (1 if c else 0), float(m)
            if qtype == "numerical" and hasattr(_marking, "mark_numerical"):
                c, m, _fb = _marking.mark_numerical(question, answer)
                return (1 if c else 0), float(m)
        except Exception:
            pass
    return auto_mark_question(question, answer)


def _parse_json(value, default=None):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


# --- exam flow ----------------------------------------------------------------

def _get_session_row(conn, session_id):
    row = conn.execute("SELECT * FROM exam_sessions WHERE id=?",
                       (session_id,)).fetchone()
    if row is None:
        return None
    cols = [c[0] for c in conn.execute(
        "SELECT * FROM exam_sessions LIMIT 0").description]
    return dict(zip(cols, row))


def _question_rows(conn, question_ids):
    if not question_ids:
        return []
    cur = conn.execute("SELECT * FROM questions WHERE id IN (%s)" %
                       ",".join("?" * len(question_ids)), question_ids)
    cols = [c[0] for c in cur.description]
    by_id = {r[cols.index("id")]: dict(zip(cols, r)) for r in cur.fetchall()}
    return [by_id[qid] for qid in question_ids if qid in by_id]


def _remaining_seconds(conn, session):
    stored = _parse_json(session.get("blueprint_json"), {}) or {}
    minutes = stored.get("time_minutes")
    if session.get("mode") != "timed" or not minutes:
        return None
    try:
        starts = datetime.fromisoformat(session["starts_at"])
    except (TypeError, ValueError):
        return None
    if starts.tzinfo is None:
        starts = starts.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - starts).total_seconds()
    return int(float(minutes) * 60 - elapsed)


def _fmt_hms(seconds):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, s)


def _answer_widget(st, q, key, current):
    qtype = (q.get("qtype") or "").lower()
    if qtype == "mcq":
        options = _parse_json(q.get("mcq_options_json"), []) or []
        if not options:
            st.caption("No options stored for this MCQ.")
            return current
        idx = options.index(current) if current in options else 0
        return st.radio("Choose one:", options, index=idx, key=key)
    if qtype == "tf":
        opts = ["True", "False"]
        idx = opts.index(current) if current in opts else 0
        return st.radio("True or False:", opts, index=idx, key=key)
    if qtype == "short":
        return st.text_input("Your answer:", value=current or "", key=key)
    if qtype == "numerical":
        return st.text_input("Your answer (number):", value=current or "",
                             key=key)
    # theory / scenario / long
    return st.text_area("Your answer:", value=current or "", height=180,
                        key=key)


def _render_builder(conn, st):
    st.subheader("Build a mock exam")
    chapters = _chapter_options(conn)
    try:
        difficulties = [r[0] for r in conn.execute(
            "SELECT DISTINCT difficulty FROM questions WHERE difficulty "
            "IS NOT NULL ORDER BY difficulty").fetchall()]
    except Exception:
        difficulties = []

    with st.form("blueprint"):
        title = st.text_input("Title", value="Mock exam 1")
        mode = st.radio("Mode", ["timed", "untimed"], horizontal=True)
        time_minutes = st.number_input("Time limit (minutes)",
                                       min_value=5, max_value=600, value=60,
                                       disabled=(mode == "untimed"))
        ch_ids = [c[0] for c in chapters]
        sel_chapters = st.multiselect("Chapters", ch_ids,
                                      default=ch_ids,
                                      format_func=lambda c: dict(chapters).get(c, c))
        sel_qtypes = st.multiselect("Question types", QTYPES, default=QTYPES)
        sel_diff = st.multiselect("Difficulty", difficulties,
                                  default=difficulties)
        count = st.number_input("Number of questions", min_value=1,
                                max_value=200, value=10)
        marks_limit = st.number_input("Marks limit (0 = none)", min_value=0,
                                      max_value=1000, value=0)
        include_incorrect = st.checkbox("Include previously incorrect "
                                        "questions", value=True)
        include_unattempted = st.checkbox("Include unattempted questions",
                                          value=True)
        start = st.form_submit_button("Start exam")

    if start:
        blueprint = {
            "chapters": sel_chapters if sel_chapters else "all",
            "qtypes": sel_qtypes,
            "difficulty": sel_diff,
            "count": int(count),
            "marks_limit": float(marks_limit) if marks_limit else None,
            "include_incorrect": include_incorrect,
            "include_unattempted": include_unattempted,
            "time_minutes": int(time_minutes) if mode == "timed" else None,
        }
        try:
            session_id, qids = build_exam(conn, title, mode, blueprint)
        except ValueError as e:
            st.error(str(e))
            return
        st.session_state["capt_exam_id"] = session_id
        st.session_state["capt_exam_qidx"] = 0
        st.session_state["capt_exam_review"] = False
        st.session_state["capt_exam_answers"] = {}
        st.session_state["capt_exam_qstart"] = datetime.now(
            timezone.utc).isoformat()
        st.rerun()

    st.subheader("Past sessions")
    sessions = list_sessions(conn)
    if not sessions:
        st.caption("No mock exams yet. Build one above.")
        return
    for s in sessions:
        cols = st.columns([4, 2, 2, 1])
        score = ("%.1f / %.1f" % (s.get("obtained") or 0,
                                  s.get("total_marks") or 0)
                 if s.get("status") == "submitted" else s.get("status"))
        cols[0].write("**%s**" % (s.get("title") or "Untitled"))
        cols[1].write(s.get("mode", ""))
        cols[2].write(score)
        if cols[3].button("Review", key="rev_%s" % s["id"]):
            st.session_state["capt_exam_id"] = s["id"]
            st.session_state["capt_exam_review"] = s.get("status") != "submitted"
            st.session_state["capt_exam_qidx"] = 0
            st.session_state["capt_exam_answers"] = {}
            st.rerun()


def _render_results(conn, st, summary):
    st.subheader("Results — %s" % summary["title"])
    total, obtained = summary["total"], summary["obtained"]
    pct = (100.0 * obtained / total) if total else 0.0
    c1, c2, c3 = st.columns(3)
    c1.metric("Score", "%.1f / %.1f" % (obtained, total))
    c2.metric("Percentage", "%.1f%%" % pct)
    t = summary["time"]
    c3.metric("Time used", _fmt_hms(t["total_seconds"]))
    st.caption("Average %ss per answered question; %d unanswered." %
               (t["avg_seconds"], t["unanswered"]))

    if summary["pending_review"]:
        st.info("%d answer(s) need manual review against the model answer "
                "(theory / scenario / long questions are never auto-marked)." %
                len(summary["pending_review"]))

    st.subheader("By chapter")
    rows = []
    for cid, b in sorted(summary["by_chapter"].items()):
        acc = (100.0 * b["obtained"] / b["total"]) if b["total"] else 0.0
        rows.append({"Chapter": _chapter_title(conn, cid),
                     "Questions": b["count"],
                     "Marks": "%.1f/%.1f" % (b["obtained"], b["total"]),
                     "Accuracy %": round(acc, 1)})
    st.table(rows)

    st.subheader("By topic")
    trows = []
    for tid, b in sorted(summary["by_topic"].items()):
        acc = (100.0 * b["obtained"] / b["total"]) if b["total"] else 0.0
        trows.append({"Topic": tid, "Questions": b["count"],
                      "Marks": "%.1f/%.1f" % (b["obtained"], b["total"]),
                      "Accuracy %": round(acc, 1)})
    st.table(trows)

    st.subheader("By question type")
    qrows = [{"Type": qt, "Accuracy %": b["accuracy"],
              "Marks": "%.1f/%.1f" % (b["obtained"], b["total"])}
             for qt, b in sorted(summary["by_qtype"].items())]
    st.table(qrows)

    if summary["missed"]:
        st.subheader("Missed questions")
        qs = {q["id"]: q for q in _question_rows(conn, summary["missed"])}
        for qid in summary["missed"]:
            q = qs.get(qid, {})
            with st.expander("Q: %s" % (q.get("statement") or qid)[:80]):
                st.write(q.get("statement") or "")
                st.caption(_source_line(q) + " — open the Study workspace "
                           "to view the source page.")
                if q.get("solution"):
                    st.write("**Model answer:**")
                    st.write(q["solution"])
                else:
                    st.caption("No verified solution in the book.")

    weak_topics = [tid for tid, b in summary["by_topic"].items()
                   if b["total"] and (b["obtained"] / b["total"]) < 0.5]
    if weak_topics:
        st.subheader("Weak concepts")
        for tid in weak_topics:
            st.write("- %s" % tid)

    st.subheader("Next steps")
    recs = []
    if summary["missed"]:
        recs.append("Reattempt the %d missed question(s) after revising "
                    "their topics." % len(summary["missed"]))
    if weak_topics:
        recs.append("Revise weak topic(s): %s." % ", ".join(weak_topics))
    if summary["pending_review"]:
        recs.append("Self-mark the %d theory-type answer(s) against the "
                    "model answers." % len(summary["pending_review"]))
    if t["unanswered"]:
        recs.append("Practise time management — %d question(s) were left "
                    "unanswered." % t["unanswered"])
    if not recs:
        recs.append("Solid paper. Build another mock with a tighter time "
                    "limit or harder difficulty.")
    for r in recs:
        st.write("- " + r)
    st.caption("A mock-exam score reflects this question set only — it does "
               "not predict the real ICAP exam result.")

    if st.button("Back to exam list"):
        for k in ("capt_exam_id", "capt_exam_qidx", "capt_exam_review",
                  "capt_exam_answers", "capt_exam_qstart"):
            st.session_state.pop(k, None)
        st.rerun()


def _render_in_exam(conn, st, session):
    stored = _parse_json(session.get("blueprint_json"), {}) or {}
    question_ids = stored.get("question_ids") or []
    questions = _question_rows(conn, question_ids)
    if not questions:
        st.error("This session has no questions stored.")
        return

    # timed: auto-submit on expiry (Streamlit reruns re-check this)
    remaining = _remaining_seconds(conn, session)
    if remaining is not None:
        if remaining <= 0:
            st.warning("Time expired — submitting automatically.")
            summary = submit_exam(conn, session["id"], _mark_fn)
            _render_results(conn, st, summary)
            return
        st.info("Time remaining: **%s**" % _fmt_hms(remaining))

    if st.session_state.get("capt_exam_review"):
        _render_review(conn, st, session, questions)
        return

    idx = st.session_state.get("capt_exam_qidx", 0)
    idx = max(0, min(idx, len(questions) - 1))
    q = questions[idx]
    qid = q["id"]
    cache = st.session_state.setdefault("capt_exam_answers", {})

    st.subheader("Question %d of %d" % (idx + 1, len(questions)))
    nav_cols = st.columns(min(len(questions), 10))
    for i in range(len(questions)):
        label = str(i + 1)
        if questions[i]["id"] in cache:
            label = "✓ " + label
        if nav_cols[i % len(nav_cols)].button(
                label, key="nav_%d" % i,
                type="primary" if i == idx else "secondary"):
            _autosave_current(conn, st, session, q)
            st.session_state["capt_exam_qidx"] = i
            st.session_state["capt_exam_qstart"] = datetime.now(
                timezone.utc).isoformat()
            st.rerun()

    st.write("**[%s · %s]** %s" % (q.get("qtype") or "?",
                                   _chapter_title(conn, q.get("chapter_id")),
                                   q.get("statement") or ""))
    st.caption(_source_line(q))
    current = cache.get(qid, {}).get("answer")
    answer = _answer_widget(st, q, key="ans_%s" % qid, current=current)

    b1, b2, b3 = st.columns(3)
    if b1.button("Save & Next"):
        _autosave_current(conn, st, session, q, answer)
        st.session_state["capt_exam_qidx"] = min(idx + 1, len(questions) - 1)
        st.session_state["capt_exam_qstart"] = datetime.now(
            timezone.utc).isoformat()
        st.rerun()
    if b2.button("Save & Previous"):
        _autosave_current(conn, st, session, q, answer)
        st.session_state["capt_exam_qidx"] = max(idx - 1, 0)
        st.session_state["capt_exam_qstart"] = datetime.now(
            timezone.utc).isoformat()
        st.rerun()
    if b3.button("Review & Submit"):
        _autosave_current(conn, st, session, q, answer)
        st.session_state["capt_exam_review"] = True
        st.rerun()


def _autosave_current(conn, st, session, q, answer=None):
    qid = q["id"]
    cache = st.session_state.setdefault("capt_exam_answers", {})
    if answer is None:
        answer = cache.get(qid, {}).get("answer")
    try:
        qstart = datetime.fromisoformat(
            st.session_state.get("capt_exam_qstart") or "")
        if qstart.tzinfo is None:
            qstart = qstart.replace(tzinfo=timezone.utc)
        spent = int((datetime.now(timezone.utc) - qstart).total_seconds())
    except (TypeError, ValueError):
        spent = 0
    prev = cache.get(qid, {}).get("seconds", 0)
    total_spent = prev + max(0, spent)
    cache[qid] = {"answer": answer, "seconds": total_spent}
    save_answer(conn, session["id"], qid,
                {"answer": answer} if not isinstance(answer, dict) else answer,
                total_spent)


def _render_review(conn, st, session, questions):
    st.subheader("Review before submitting")
    cache = st.session_state.get("capt_exam_answers", {})
    for i, q in enumerate(questions):
        answered = q["id"] in cache and cache[q["id"]].get("answer") not in (
            None, "")
        cols = st.columns([1, 6, 2])
        cols[0].write("Q%d" % (i + 1))
        cols[1].write((q.get("statement") or "")[:100])
        cols[2].write("✓ answered" if answered else "— unanswered")
    c1, c2 = st.columns(2)
    if c1.button("Back to questions"):
        st.session_state["capt_exam_review"] = False
        st.rerun()
    if c2.button("Submit exam", type="primary"):
        summary = submit_exam(conn, session["id"], _mark_fn)
        _render_results(conn, st, summary)


def render(conn):
    import streamlit as st
    _demo_banner(conn, st)
    st.header("Mock Examinations")
    st.caption("Build timed or untimed mock exams from the question bank. "
               "Scores reflect the selected questions only — they do not "
               "predict the real exam result.")

    session_id = st.session_state.get("capt_exam_id")
    if not session_id:
        _render_builder(conn, st)
        return
    session = _get_session_row(conn, session_id)
    if session is None:
        st.error("Exam session not found.")
        st.session_state.pop("capt_exam_id", None)
        return
    if session.get("status") == "submitted" and not st.session_state.get(
            "capt_exam_review"):
        _render_results(conn, st, exam_summary(conn, session_id))
        return
    if session.get("status") == "submitted":
        _render_results(conn, st, exam_summary(conn, session_id))
        return
    _render_in_exam(conn, st, session)
