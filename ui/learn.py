"""Learn workspace: Learn / Understand / Memorise / Practise / Revise per topic.

Pure data helpers (importable without streamlit):
    build_revision_sheet(conn, topic_id=None, chapter_id=None) -> dict
"""

import datetime as _dt
import json as _json
import sqlite3 as _sqlite3

try:
    import streamlit as st
except Exception:  # pragma: no cover - streamlit absent in tests
    st = None

try:
    from core import uihelpers as _uh
except Exception:  # pragma: no cover
    _uh = None

from core import marking as _marking
from core import sr as _sr


# ---------------------------------------------------------------------------
# Small uihelpers fallbacks (used only when core/uihelpers.py is absent)
# ---------------------------------------------------------------------------

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


def _topic_options(conn, chapter_id):
    if _uh is not None and hasattr(_uh, "topic_options"):
        try:
            return _uh.topic_options(conn, chapter_id)
        except Exception:
            pass
    rows = conn.execute(
        "SELECT id, name FROM topics WHERE chapter_id = ? ORDER BY sort_order, name",
        (chapter_id,),
    ).fetchall()
    return [(r["id"], r["name"]) for r in rows]


def _status_chip(status):
    if _uh is not None and hasattr(_uh, "status_chip"):
        try:
            _uh.status_chip(status)
            return
        except Exception:
            pass
    if st is not None:
        st.caption(f"status: {status}")


def _source_ref_line(ref, page_start=None, page_end=None):
    if _uh is not None and hasattr(_uh, "source_ref_line"):
        try:
            return _uh.source_ref_line(ref, page_start, page_end)
        except Exception:
            pass
    bits = [ref] if ref else []
    if page_start:
        bits.append(f"p. {page_start}" + (f"–{page_end}" if page_end else ""))
    return " · ".join(bits)


def _is_bookmarked(conn, target_kind, target_id):
    r = conn.execute(
        "SELECT 1 FROM bookmarks WHERE target_kind=? AND target_id=?",
        (target_kind, str(target_id)),
    ).fetchone()
    return r is not None


def _toggle_bookmark(conn, target_kind, target_id):
    if _is_bookmarked(conn, target_kind, target_id):
        conn.execute(
            "DELETE FROM bookmarks WHERE target_kind=? AND target_id=?",
            (target_kind, str(target_id)),
        )
        conn.commit()
        return False
    conn.execute(
        "INSERT INTO bookmarks(target_kind, target_id, created_at) VALUES (?,?,?)",
        (target_kind, str(target_id),
         _dt.datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    return True


# ---------------------------------------------------------------------------
# Pure data assembly (used by the Revise tab and by tests)
# ---------------------------------------------------------------------------

def build_revision_sheet(conn, topic_id=None, chapter_id=None):
    """Assemble a revision sheet grounded in imported content only.

    Returns dict with keys: definitions, rules, exceptions, formulas,
    missed_questions, sources. Empty lists when nothing exists.
    """
    clauses, params = [], []
    if topic_id is not None:
        clauses.append("topic_id = ?")
        params.append(topic_id)
    elif chapter_id is not None:
        clauses.append("chapter_id = ?")
        params.append(chapter_id)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

    def _q(sql, cols):
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    definitions = _q(
        f"SELECT id, title, body, source_ref, page_start, page_end, origin,"
        f" status FROM items {where} "
        + ("AND " if where else "WHERE ") + "kind = 'definition' ORDER BY id",
        None,
    )
    formulas = _q(
        f"SELECT id, title, body, source_ref, page_start, page_end, origin,"
        f" status FROM items {where} "
        + ("AND " if where else "WHERE ") + "kind = 'formula' ORDER BY id",
        None,
    )
    notes = _q(
        f"SELECT id, title, body, source_ref, origin, status FROM items {where} "
        + ("AND " if where else "WHERE ") + "kind IN ('note','common_mistake')",
        None,
    )
    rules = []
    if chapter_id is not None or topic_id is not None:
        try:
            if topic_id is not None:
                ch = conn.execute(
                    "SELECT chapter_id FROM topics WHERE id = ?", (topic_id,)
                ).fetchone()
                ch_id = ch["chapter_id"] if ch else None
            else:
                ch_id = chapter_id
            if ch_id:
                rules = [dict(r) for r in conn.execute(
                    "SELECT id, rule_code, title, category, rate_or_threshold,"
                    " exceptions_json, exclusions_json, source_ref, page_start,"
                    " page_end, verification_status FROM tax_rules"
                    " WHERE chapter_id = ? ORDER BY rule_code, id",
                    (ch_id,),
                ).fetchall()]
        except Exception:
            rules = []

    # Previously-missed questions: attempts with correct=0 on question attempts.
    missed = []
    try:
        mq = conn.execute(
            """SELECT DISTINCT q.id, q.number, q.section, q.statement, q.qtype,
                      q.page_start, q.page_end, q.origin
               FROM attempts a JOIN questions q ON q.id = a.question_id
               WHERE a.correct = 0 AND a.kind IN ('question','theory','mcq','tf','numerical')
            """
            + (f" AND q.topic_id = ?" if topic_id else "")
            + (f" AND q.chapter_id = ?" if (chapter_id and not topic_id) else ""),
            ([topic_id] if topic_id else ([chapter_id] if chapter_id else [])),
        ).fetchall()
        missed = [dict(r) for r in mq]
    except _sqlite3.OperationalError:
        # attempts/questions tables not created yet (foundation team owns db)
        missed = []

    # Examiner pitfalls for the chapter (seeded from the book's own
    # examiner commentary; student-added pitfalls included).
    pitfalls = []
    try:
        _ch_id = chapter_id
        if topic_id is not None:
            _ch = conn.execute("SELECT chapter_id FROM topics WHERE id = ?",
                               (topic_id,)).fetchone()
            _ch_id = _ch["chapter_id"] if _ch else None
        if _ch_id:
            try:
                from core import pitfalls as _pf
                pitfalls = _pf.list_pitfalls(conn, _ch_id)
            except Exception:
                pitfalls = []
    except _sqlite3.OperationalError:
        pitfalls = []

    return {
        "definitions": definitions,
        "formulas": formulas,
        "notes": notes,
        "rules": rules,
        "missed_questions": missed,
        "pitfalls": pitfalls,
    }


# ---------------------------------------------------------------------------
# Tab renderers
# ---------------------------------------------------------------------------

def _render_learn_tab(conn, topic_id, chapter_id):
    rows = conn.execute(
        """SELECT * FROM items WHERE topic_id = ?
           AND kind IN ('definition','note','example','formula','common_mistake')
           ORDER BY CASE kind
             WHEN 'definition' THEN 0 WHEN 'formula' THEN 1
             WHEN 'example' THEN 2 WHEN 'common_mistake' THEN 3 ELSE 4 END, id""",
        (topic_id,),
    ).fetchall()
    if not rows:
        st.info("No learning content for this topic yet.")
    for r in rows:
        with st.expander(f"[{r['kind']}] {r['title'] or '(untitled)'}"):
            # Verbatim source text in blockquote style; never paraphrased.
            st.markdown(f"> {r['body']}")
            st.caption(_source_ref_line(r["source_ref"], r["page_start"], r["page_end"]))
            _status_chip(r["status"])
            if r["origin"] == "ocr" or r["status"] == "auto_detected_unverified":
                st.warning("Unverified content — check against the source page before trusting it.")
            with st.expander("View source page"):
                st.caption("Source page rendering is provided by the foundation team's viewer.")
                if _uh is not None and hasattr(_uh, "show_source_page"):
                    try:
                        _uh.show_source_page(conn, r["source_ref"], r["page_start"])
                    except Exception as e:
                        st.caption(f"Viewer unavailable: {e}")

    st.divider()
    st.subheader("My notes")
    note = conn.execute(
        "SELECT * FROM notes WHERE target_kind='topic' AND target_id=?",
        (topic_id,),
    ).fetchone()
    body = st.text_area("Personal notes (clearly yours — not source text)",
                        value=note["body"] if note else "",
                        key=f"notes_{topic_id}", height=150)
    if st.button("Save notes", key=f"save_notes_{topic_id}"):
        now = _dt.datetime.now().isoformat(timespec="seconds")
        if note:
            conn.execute("UPDATE notes SET body=?, updated_at=? WHERE id=?",
                         (body, now, note["id"]))
        else:
            conn.execute(
                "INSERT INTO notes(target_kind, target_id, body, created_at, updated_at)"
                " VALUES (?,?,?,?,?)", ("topic", topic_id, body, now, now))
        conn.commit()
        st.success("Notes saved.")
    col1, col2 = st.columns(2)
    with col1:
        bm = _is_bookmarked(conn, "topic", topic_id)
        if st.button(("★ " if bm else "☆ ") + "Bookmark topic",
                     key=f"bm_{topic_id}"):
            _toggle_bookmark(conn, "topic", topic_id)
            st.rerun()
    with col2:
        rv = _is_bookmarked(conn, "revise", topic_id)
        if st.button(("✓ " if rv else "") + "Mark for revision",
                     key=f"rev_{topic_id}"):
            _toggle_bookmark(conn, "revise", topic_id)
            st.rerun()


def _render_understand_tab(conn, topic_id):
    st.subheader("Concept cards")
    cards = conn.execute(
        "SELECT * FROM items WHERE topic_id=? AND kind='concept_card' ORDER BY id",
        (topic_id,),
    ).fetchall()
    if not cards:
        st.info("No concept cards yet.")
    for c in cards:
        with st.expander(f"{c['title'] or '(untitled)'}"):
            if c["status"] == "flagged":
                st.warning("DRAFT — needs your review. Not verified.")
            st.markdown(f"> {c['body']}")
            _status_chip(c["status"])
            new_title = st.text_input("Title", value=c["title"] or "",
                                      key=f"cc_t_{c['id']}")
            new_body = st.text_area("Body", value=c["body"] or "",
                                    key=f"cc_b_{c['id']}")
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Save edits", key=f"cc_save_{c['id']}"):
                    for field, old, new in (("title", c["title"], new_title),
                                            ("body", c["body"], new_body)):
                        if (old or "") != (new or ""):
                            conn.execute(
                                "INSERT INTO import_corrections(target_kind, target_id,"
                                " field, old_value, new_value, created_at)"
                                " VALUES (?,?,?,?,?,?)",
                                ("item", c["id"], field, old, new,
                                 _dt.datetime.now().isoformat(timespec="seconds")),
                            )
                    conn.execute(
                        "UPDATE items SET title=?, body=? WHERE id=?",
                        (new_title, new_body, c["id"]))
                    conn.commit()
                    st.success("Saved — edit history kept.")
                    st.rerun()
            with col2:
                if st.button("Mark verified", key=f"cc_ver_{c['id']}"):
                    conn.execute(
                        "INSERT INTO import_corrections(target_kind, target_id, field,"
                        " old_value, new_value, created_at) VALUES (?,?,?,?,?,?)",
                        ("item", c["id"], "status", c["status"], "verified",
                         _dt.datetime.now().isoformat(timespec="seconds")))
                    conn.execute("UPDATE items SET status='verified' WHERE id=?",
                                 (c["id"],))
                    conn.commit()
                    st.success("Marked verified.")
                    st.rerun()

    st.divider()
    if st.button("Suggest draft cards from definitions"):
        defs = conn.execute(
            "SELECT * FROM items WHERE topic_id=? AND kind='definition'",
            (topic_id,),
        ).fetchall()
        made = 0
        for d in defs:
            exists = conn.execute(
                "SELECT 1 FROM items WHERE topic_id=? AND kind='concept_card'"
                " AND title=?", (topic_id, d["title"])).fetchone()
            if exists:
                continue
            conn.execute(
                """INSERT INTO items(kind, topic_id, chapter_id, title, body,
                                     source_ref, origin, status)
                   VALUES ('concept_card',?,?,?,?,?,'student','flagged')""",
                (topic_id, d["chapter_id"], d["title"],
                 f"DRAFT — needs your review.\n\n{d['body']}", d["source_ref"]))
            made += 1
        conn.commit()
        st.success(f"Created {made} draft card(s) — flagged, never auto-verified.")
        st.rerun()


def _render_memorise_tab(conn, topic_id, chapter_id):
    try:
        from ui.flashcards import review_widget
    except Exception:
        st.error("Flashcard widget unavailable (ui/flashcards.py could not be imported).")
        return
    stats = _sr.deck_stats(conn, topic_id=topic_id)
    c1, c2, c3 = st.columns(3)
    c1.metric("Cards", stats["total"])
    c2.metric("Due", stats["due"])
    c3.metric("New", stats["new"])
    if st.button("Generate cards from this topic"):
        n = _sr.ensure_cards_for_topic(conn, topic_id)
        st.success(f"Created {n} card(s).")
        st.rerun()
    review_widget(conn, topic_id=topic_id)


def _render_practise_tab(conn, topic_id):
    qs = conn.execute(
        "SELECT * FROM questions WHERE topic_id=? ORDER BY number, id",
        (topic_id,),
    ).fetchall()
    if not qs:
        st.info("No questions for this topic yet.")
    for q in qs:
        with st.expander(f"Q{q['number'] or ''} [{q['qtype']}] "
                         f"({q['origin']}) — {str(q['statement'])[:80]}"):
            st.write(q["statement"])
            st.caption(f"Source: p. {q['page_start']}"
                       + (f"–{q['page_end']}" if q.get("page_end") else ""))
            _render_attempt_form(conn, dict(q))


def _render_attempt_form(conn, q):
    qtype = q.get("qtype")
    key = f"pract_{q['id']}"
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
            _marking.record_attempt(conn, question_id=q["id"], kind="question",
                                    qtype="mcq", correct=correct,
                                    marks_obtained=marks,
                                    marks_max=float(q.get("marks") or 1.0))
            st.success(fb) if correct else st.error(fb)
    elif qtype == "tf":
        choice = st.radio("Your answer", ["True", "False"], key=key + "_tf")
        if st.button("Check", key=key + "_go"):
            correct, marks, fb = _marking.mark_tf(q, choice)
            _marking.record_attempt(conn, question_id=q["id"], kind="question",
                                    qtype="tf", correct=correct,
                                    marks_obtained=marks,
                                    marks_max=float(q.get("marks") or 1.0))
            st.success(fb) if correct else st.error(fb)
    elif qtype == "numerical":
        val = st.text_input("Your answer (number only)", key=key + "_num")
        rounding = st.selectbox("Rounding", ["nearest", "2dp", "integer", "none"],
                                key=key + "_rnd")
        if q.get("numeric_tolerance") is not None:
            st.caption(f"Tolerance: ±{q['numeric_tolerance']}")
        if st.button("Check", key=key + "_go"):
            correct, marks, note = _marking.mark_numerical(q, val, rounding=rounding)
            _marking.record_attempt(conn, question_id=q["id"], kind="question",
                                    qtype="numerical", correct=correct,
                                    marks_obtained=marks,
                                    marks_max=float(q.get("marks") or 1.0))
            st.success(note) if correct else st.error(note)
    else:  # theory / long / scenario / short
        rubric = _marking.theory_rubric(q)
        st.caption("Rubric (self-assessment — the app never auto-scores theory):")
        claimed = []
        for i, p in enumerate(rubric):
            got = st.checkbox(f"{p['point']} ({p['marks']} marks)",
                              key=f"{key}_rub_{i}")
            claimed.append({"point": p["point"],
                            "marks_claimed": p["marks"] if got else 0.0})
        if st.button("Record self-assessment", key=key + "_go"):
            _marking.record_self_assessment(conn, q["id"], _json.dumps(claimed))
            st.success("Self-assessment recorded (correct=NULL — no auto score).")


def _render_revise_tab(conn, topic_id, chapter_id):
    sheet = build_revision_sheet(conn, topic_id=topic_id, chapter_id=chapter_id)
    st.subheader("Revision sheet")
    st.caption("Grounded in imported content only. Empty sections mean nothing "
               "exists yet — nothing is invented.")
    with st.expander(f"Definitions ({len(sheet['definitions'])})", expanded=True):
        for d in sheet["definitions"]:
            st.markdown(f"> **{d['title']}** — {d['body']}")
            st.caption(_source_ref_line(d.get("source_ref"), d.get("page_start"),
                                        d.get("page_end")))
            _status_chip(d.get("status"))
    with st.expander(f"Rules ({len(sheet['rules'])})"):
        for r in sheet["rules"]:
            st.markdown(f"**{r.get('rule_code') or ''} {r.get('title') or ''}**")
            if r.get("exceptions_json"):
                st.caption(f"Exceptions: {r['exceptions_json']}")
            st.caption(_source_ref_line(r.get("source_ref"), r.get("page_start"),
                                        r.get("page_end")))
    with st.expander(f"Formulas ({len(sheet['formulas'])})"):
        for f in sheet["formulas"]:
            st.markdown(f"> **{f['title']}** — {f['body']}")
            st.caption(_source_ref_line(f.get("source_ref"), f.get("page_start"),
                                        f.get("page_end")))
    with st.expander(f"Notes & common mistakes ({len(sheet['notes'])})"):
        for n in sheet["notes"]:
            st.markdown(f"> **{n['title']}** — {n['body']}")
    with st.expander(f"⚠️ Examiner pitfalls ({len(sheet['pitfalls'])})"):
        if not sheet["pitfalls"]:
            st.info("No examiner pitfalls recorded for this chapter.")
        for p in sheet["pitfalls"]:
            st.markdown(f"> **{p['title']}** — {p['observation']}")
            st.caption(f"{'🧑‍🏫 Examiner commentary' if p['source'] == 'examiner_commentary' else '✏️ Your note'}"
                       + (f" · p. {p['page']}" if p.get("page") else ""))
    with st.expander(f"Previously missed questions "
                     f"({len(sheet['missed_questions'])})"):
        if not sheet["missed_questions"]:
            st.info("No missed questions recorded yet.")
        for m in sheet["missed_questions"]:
            st.write(f"Q{m.get('number') or ''} [{m.get('qtype')}] "
                     f"{str(m.get('statement'))[:120]}")
            st.caption(_source_ref_line(m.get("source_ref"), m.get("page_start"),
                                        m.get("page_end")))


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render(conn):
    """Learn workspace."""
    if st is None:  # pragma: no cover
        return
    st.header("Learn")
    _demo_banner(conn)

    chapters = _chapter_options(conn)
    if not chapters:
        st.info("No chapters imported yet.")
        return
    ch_map = {c[0]: c[1] for c in chapters}
    sel_ch = st.selectbox("Chapter", list(ch_map.keys()),
                          format_func=lambda x: ch_map[x], key="learn_ch")
    topics = _topic_options(conn, sel_ch)
    if not topics:
        st.info("No topics in this chapter yet.")
        return
    t_map = {t[0]: t[1] for t in topics}
    sel_t = st.selectbox("Topic", list(t_map.keys()),
                         format_func=lambda x: t_map[x], key="learn_t")

    tabs = st.tabs(["Learn", "Understand", "Memorise", "Practise", "Revise"])
    with tabs[0]:
        _render_learn_tab(conn, sel_t, sel_ch)
    with tabs[1]:
        _render_understand_tab(conn, sel_t)
    with tabs[2]:
        _render_memorise_tab(conn, sel_t, sel_ch)
    with tabs[3]:
        _render_practise_tab(conn, sel_t)
    with tabs[4]:
        _render_revise_tab(conn, sel_t, sel_ch)
