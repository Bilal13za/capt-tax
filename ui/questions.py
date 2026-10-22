"""Question Bank: filter questions and attempt them by type."""

import json as _json

try:
    import streamlit as st
except Exception:  # pragma: no cover - streamlit absent in tests
    st = None

try:
    from core import uihelpers as _uh
except Exception:  # pragma: no cover
    _uh = None

from core import marking as _marking


def _demo_banner(conn):
    if _uh is not None and hasattr(_uh, "demo_banner"):
        try:
            _uh.demo_banner(conn)
            return
        except Exception:
            pass
    if st is not None:
        st.warning("DEMO content — synthetic sample data, not from the textbook.")


def _chapter_options(conn):
    if _uh is not None and hasattr(_uh, "chapter_options"):
        try:
            return _uh.chapter_options(conn)
        except Exception:
            pass
    rows = conn.execute(
        "SELECT id, number, title FROM chapters ORDER BY number"
    ).fetchall()
    return [(r["id"], f"Ch {r['number']}: {r['title']}") for r in rows]


def _origin_label(origin):
    return {"imported": "from textbook", "sample": "DEMO sample",
            "student": "student-added", "generated": "generated practice"}.get(
                origin, origin)


def _attempted_ids(conn):
    rows = conn.execute(
        "SELECT DISTINCT question_id FROM attempts WHERE question_id IS NOT NULL"
    ).fetchall()
    return {r["question_id"] for r in rows}


def _incorrect_ids(conn):
    rows = conn.execute(
        "SELECT DISTINCT question_id FROM attempts WHERE question_id IS NOT NULL"
        " AND correct = 0"
    ).fetchall()
    return {r["question_id"] for r in rows}


def _revise_ids(conn):
    rows = conn.execute(
        "SELECT target_id FROM bookmarks WHERE target_kind = 'revise'"
    ).fetchall()
    return {r["target_id"] for r in rows}


def _attempt_widget(conn, q):
    """Per-qtype attempt widget with deterministic marking."""
    q = dict(q)
    qtype = q.get("qtype")
    key = f"qb_{q['id']}"

    if qtype == "mcq":
        try:
            opts = _json.loads(q.get("mcq_options_json") or "[]")
        except Exception:
            opts = []
        labels = [o.get("label", str(o)) if isinstance(o, dict) else str(o)
                  for o in opts] or ["a", "b", "c", "d"]
        choice = st.radio("Your answer", labels, key=key + "_mcq")
        if st.button("Check", key=key + "_go"):
            correct, marks, fb = _marking.mark_mcq(q, choice)
            _marking.record_attempt(
                conn, question_id=q["id"], kind="question", qtype="mcq",
                correct=correct, marks_obtained=marks,
                marks_max=_qmarks(q))
            (st.success if correct else st.error)(fb)

    elif qtype == "tf":
        choice = st.radio("Your answer", ["True", "False"], key=key + "_tf")
        if st.button("Check", key=key + "_go"):
            correct, marks, fb = _marking.mark_tf(q, choice)
            _marking.record_attempt(
                conn, question_id=q["id"], kind="question", qtype="tf",
                correct=correct, marks_obtained=marks,
                marks_max=_qmarks(q))
            (st.success if correct else st.error)(fb)

    elif qtype == "numerical":
        val = st.text_input("Your answer (number only)", key=key + "_num")
        rules = _marking.get_marking_rules(conn)
        rounding = st.selectbox(
            "Rounding", ["nearest", "2dp", "integer", "none"],
            index=["nearest", "2dp", "integer", "none"].index(
                rules.get("rounding_default", "nearest")),
            key=key + "_rnd")
        tol = q.get("numeric_tolerance")
        st.caption(f"Tolerance: ±{tol if tol is not None else rules['numerical_default_tolerance']}")
        if st.button("Check", key=key + "_go"):
            correct, marks, note = _marking.mark_numerical(q, val, rounding=rounding)
            _marking.record_attempt(
                conn, question_id=q["id"], kind="question", qtype="numerical",
                correct=correct, marks_obtained=marks,
                marks_max=_qmarks(q))
            (st.success if correct else st.error)(note)

    else:  # theory / long / scenario / short — self-assessed, never auto-scored
        if q.get("has_solution"):
            with st.expander("Model solution (from source)"):
                st.markdown(f"> {q.get('solution')}")
        else:
            st.warning("Answer not verified — no solution on record. "
                       "You may add one below; it will be labelled student-added.")
            sol = st.text_area("Add your solution", key=key + "_sol")
            if st.button("Save my solution", key=key + "_solsave") and sol.strip():
                conn.execute(
                    "UPDATE questions SET solution=?, has_solution=1,"
                    " origin='student', verified_answer=0,"
                    " answer_note='Student-added solution — not verified.'"
                    " WHERE id=?", (sol.strip(), q["id"]))
                conn.commit()
                st.success("Saved as student-added (not verified).")
                st.rerun()
        st.caption("Self-assessment against the rubric — the app never auto-scores theory.")
        rubric = _marking.theory_rubric(q)
        claimed = []
        for i, p in enumerate(rubric):
            got = st.checkbox(f"{p['point']} ({p['marks']} marks)",
                              key=f"{key}_rub_{i}")
            claimed.append({"point": p["point"],
                            "marks_claimed": p["marks"] if got else 0.0})
        if st.button("Record self-assessment", key=key + "_go"):
            _marking.record_self_assessment(conn, q["id"], _json.dumps(claimed))
            st.success("Recorded (correct=NULL — no auto score).")


def _qmarks(q):
    try:
        return float(q.get("marks") or 1.0)
    except (TypeError, ValueError):
        return 1.0


def render(conn):
    """Question Bank."""
    if st is None:  # pragma: no cover
        return
    st.header("Question Bank")
    _demo_banner(conn)

    # Focus jump from the Learn workspace
    focus = st.session_state.pop("qb_focus", None)

    chapters = _chapter_options(conn)
    ch_map = {"(all)": "All chapters"}
    ch_map.update({c[0]: c[1] for c in chapters})

    f1, f2, f3 = st.columns(3)
    with f1:
        sel_ch = st.selectbox("Chapter", list(ch_map.keys()),
                              format_func=lambda x: ch_map[x], key="qb_ch")
    with f2:
        sel_type = st.selectbox("Type", ["(all)", "mcq", "tf", "short", "theory",
                                         "numerical", "scenario", "long"],
                                key="qb_type")
    with f3:
        sel_diff = st.selectbox("Difficulty", ["(all)", "easy", "medium", "hard"],
                                key="qb_diff")

    f4, f5, f6 = st.columns(3)
    with f4:
        only_unattempted = st.checkbox("Unattempted only", key="qb_unatt")
    with f5:
        only_incorrect = st.checkbox("Incorrect only", key="qb_incorr")
    with f6:
        only_revise = st.checkbox("Due for revision", key="qb_rev")

    clauses, params = [], []
    if sel_ch != "(all)":
        clauses.append("chapter_id = ?")
        params.append(sel_ch)
    if sel_type != "(all)":
        clauses.append("qtype = ?")
        params.append(sel_type)
    if sel_diff != "(all)":
        clauses.append("difficulty = ?")
        params.append(sel_diff)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM questions {where} ORDER BY chapter_id, number, id",
        params,
    ).fetchall()

    attempted = _attempted_ids(conn)
    incorrect = _incorrect_ids(conn)
    revise = _revise_ids(conn)

    shown = 0
    for r in rows:
        q = dict(r)
        if only_unattempted and q["id"] in attempted:
            continue
        if only_incorrect and q["id"] not in incorrect:
            continue
        if only_revise and q["id"] not in revise and q.get("topic_id") not in revise:
            continue
        shown += 1
        title = (f"Q{q.get('number') or ''} [{q.get('qtype')}] "
                 f"({_origin_label(q.get('origin'))})")
        if q["id"] in incorrect:
            title = "❌ " + title
        elif q["id"] in attempted:
            title = "✓ " + title
        with st.expander(title, expanded=(focus == q["id"])):
            st.write(q["statement"])
            st.caption(f"Source: p. {q.get('page_start')}"
                       + (f"–{q.get('page_end')}" if q.get("page_end") else "")
                       + f" · section: {q.get('section') or '—'}"
                       + f" · origin: {_origin_label(q.get('origin'))}")
            if not q.get("has_solution") and q.get("qtype") in ("mcq", "numerical", "tf"):
                st.warning("Answer not verified — no key on record.")
            with st.expander("View source page"):
                st.caption("Source page rendering is provided by the foundation team's viewer.")
                if _uh is not None and hasattr(_uh, "show_source_page"):
                    try:
                        _uh.show_source_page(conn, None, q.get("page_start"))
                    except Exception as e:
                        st.caption(f"Viewer unavailable: {e}")
            if q.get("chapter_id"):
                if st.button("🧭 Open answer approach",
                             key=f"qb_approach_{q['id']}"):
                    st.session_state["nav"] = "Answer Approaches"
                    st.session_state["approach_chapter"] = q["chapter_id"]
                    st.rerun()
            _attempt_widget(conn, q)
    if shown == 0:
        st.info("No questions match these filters.")
