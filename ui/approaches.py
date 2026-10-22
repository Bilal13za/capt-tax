"""Answer Approaches — guided exam workflows per chapter.

Pure helpers are importable without streamlit; only ``render()`` touches it.
"""

import sqlite3 as _sqlite3

try:
    import streamlit as st
except Exception:  # pragma: no cover - streamlit absent in tests
    st = None

from core import approaches as _ap

try:
    from core import uihelpers as _uh
except Exception:  # pragma: no cover
    _uh = None


def _chapter_options(conn):
    if _uh is not None and hasattr(_uh, "chapter_options"):
        try:
            return _uh.chapter_options(conn)
        except Exception:
            pass
    rows = conn.execute(
        "SELECT id, number, title FROM chapters ORDER BY number").fetchall()
    return [(r["id"], f"Ch {r['number']}: {r['title']}") for r in rows]


def _link_caption(conn, step):
    """Human-readable description of a step's linked DB row (or '')."""
    kind, ref = step.get("link_kind"), step.get("link_ref")
    if not kind or kind == "none" or not ref:
        return ""
    try:
        if kind == "rule":
            r = conn.execute(
                "SELECT rule_code, title FROM tax_rules WHERE id=?",
                (ref,)).fetchone()
            if r:
                return f"🔗 Rule: {(r['rule_code'] or '')} {r['title'] or ''}".strip()
        elif kind == "definition":
            r = conn.execute("SELECT title FROM items WHERE id=?",
                             (ref,)).fetchone()
            if r:
                return f"🔗 Definition: {r['title']}"
        elif kind == "question":
            r = conn.execute(
                "SELECT number, section FROM questions WHERE id=?",
                (ref,)).fetchone()
            if r:
                return (f"🔗 Question: Q{r['number'] or ''} "
                        f"({r['section'] or ''})".strip())
    except _sqlite3.Error:
        pass
    return ""


def render(conn):
    """Answer Approaches workspace."""
    if st is None:  # pragma: no cover
        return
    st.header("🧭 Answer Approaches")
    st.caption(
        "A deterministic step checklist for attempting exam questions, one "
        "per chapter. These are **suggested workflows — exam technique, not "
        "tax law**. Verify every step against the book; edit them freely, "
        "every edit is logged.")

    chapters = _chapter_options(conn)
    if not chapters:
        st.info("No chapters imported yet.")
        return
    ch_ids = [c[0] for c in chapters]
    ch_labels = {c[0]: c[1] for c in chapters}

    # Deep link from the Question Bank ("Open answer approach").
    focus = st.session_state.pop("approach_chapter", None)
    default_ix = ch_ids.index(focus) if focus in ch_ids else 0
    sel = st.selectbox("Chapter", ch_ids,
                       format_func=lambda x: ch_labels.get(x, x),
                       index=default_ix, key="appr_chapter")

    aid = _ap.ensure_approach(conn, sel)
    appr = _ap.get_approach(conn, sel)
    st.subheader(appr["title"])
    st.info(f"💡 {appr['intro']}")
    if (appr.get("origin") or "") == "seeded":
        st.caption("Seeded workflow — suggested, not official. Edit freely.")

    # --- walkthrough sessions -------------------------------------------
    st.subheader("Walkthrough checklist")
    sessions = _ap.list_sessions(conn, aid)
    sess_labels = {s["id"]: f"{s['label']} ({s['status']})" for s in sessions}
    opts = ["(start a new walkthrough)"] + [s["id"] for s in sessions]
    pick = st.selectbox(
        "Walkthrough session",
        opts,
        format_func=lambda x: sess_labels.get(x, x)
        if x != "(start a new walkthrough)" else x,
        key=f"appr_sess_{aid}")
    if pick == "(start a new walkthrough)":
        label = st.text_input("Label (e.g. 'Q4(a) Spring 2025 attempt')",
                              key=f"appr_label_{aid}")
        if st.button("Start walkthrough", key=f"appr_start_{aid}"):
            sid = _ap.start_session(conn, aid, label or None)
            st.session_state[f"appr_active_{aid}"] = sid
            st.rerun()
        st.info("Start a walkthrough to tick off steps as you attempt a "
                "question. Progress is saved automatically.")
        active = None
    else:
        active = pick
        st.session_state[f"appr_active_{aid}"] = active

    steps = _ap.get_steps(conn, aid)
    if active is not None:
        prog = _ap.session_progress(conn, active)
        st.progress(prog["done"] / prog["total"] if prog["total"] else 0,
                    text=f"{prog['done']}/{prog['total']} steps done")
        checks = {r["step_id"]: r["done"] for r in conn.execute(
            "SELECT step_id, done FROM approach_checks WHERE session_id=?",
            (active,)).fetchall()}
        for s in steps:
            done = bool(checks.get(s["id"]))
            ticked = st.checkbox(s["title"], value=done,
                                 key=f"appr_chk_{active}_{s['id']}")
            if ticked != done:
                _ap.set_check(conn, active, s["id"], ticked)
                st.rerun()
            st.caption(s["detail"] or "")
            cap = _link_caption(conn, s)
            if cap:
                st.caption(cap)
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Mark walkthrough complete",
                         key=f"appr_done_{active}"):
                _ap.close_session(conn, active)
                st.success("Walkthrough closed.")
                st.rerun()
    else:
        for i, s in enumerate(steps, 1):
            with st.expander(f"Step {i}: {s['title']}", expanded=(i == 1)):
                st.write(s["detail"] or "")
                cap = _link_caption(conn, s)
                if cap:
                    st.caption(cap)

    # --- edit the workflow -------------------------------------------------
    st.divider()
    with st.expander("✏️ Edit this workflow"):
        st.caption("Changes are saved and logged (approach_edits). Steps are "
                   "technique — keep tax-law claims in the Rule Library.")
        for s in _ap.get_steps(conn, aid):
            with st.expander(f"Step {s['step_no']}: {s['title'][:60]}"):
                nt = st.text_input("Title", value=s["title"],
                                   key=f"appr_et_{s['id']}")
                nd = st.text_area("Detail", value=s["detail"] or "",
                                  key=f"appr_ed_{s['id']}", height=120)
                ec1, ec2 = st.columns(2)
                with ec1:
                    if st.button("Save step", key=f"appr_es_{s['id']}"):
                        if nt != s["title"]:
                            _ap.update_step(conn, aid, s["id"], "title", nt)
                        if nd != (s["detail"] or ""):
                            _ap.update_step(conn, aid, s["id"], "detail", nd)
                        st.success("Step updated.")
                        st.rerun()
                with ec2:
                    if st.button("Delete step", key=f"appr_del_{s['id']}"):
                        _ap.delete_step(conn, aid, s["id"])
                        st.success("Step deleted.")
                        st.rerun()
        st.subheader("Add a step")
        at = st.text_input("Step title", key=f"appr_at_{aid}")
        ad = st.text_area("Step detail", key=f"appr_ad_{aid}", height=100)
        if st.button("Add step", key=f"appr_add_{aid}") and at.strip():
            _ap.add_step(conn, aid, at.strip(), ad.strip())
            st.success("Step added.")
            st.rerun()
