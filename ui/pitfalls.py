"""Pitfalls & examiner insights.

Seeded pitfalls come ONLY from the examiner commentary printed in the
textbook (ch01, pp. 7–12) — quoted verbatim, […] marking extraction gaps.
Students can add their own pitfalls and turn any pitfall into a flashcard.
"""

try:
    import streamlit as st
except Exception:  # pragma: no cover - streamlit absent in tests
    st = None

from core import pitfalls as _pf

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


def _source_badge(p):
    if p["source"] == "examiner_commentary":
        return f"🧑‍🏫 Examiner commentary · p. {p['page']}"
    return "✏️ Your note"


def render(conn):
    """Pitfalls workspace."""
    if st is None:  # pragma: no cover
        return
    st.header("⚠️ Pitfalls & Examiner Insights")
    st.caption(
        "What the examiners say students keep getting wrong — quoted "
        "verbatim from the examiner commentary printed in your textbook "
        "(pp. 7–12). […] marks a gap in the book's own extraction, never a "
        "smoothed-over claim.")

    # Ensure seeds exist (idempotent; no-ops when commentary is absent).
    n = _pf.seed_pitfalls(conn)
    if n:
        st.success(f"Loaded {n} examiner pitfalls from the textbook.")

    chapters = _chapter_options(conn)
    ch_ids = ["(all)"] + [c[0] for c in chapters]
    ch_labels = {"(all)": "All chapters"}
    ch_labels.update({c[0]: c[1] for c in chapters})
    sel = st.selectbox("Chapter", ch_ids,
                       format_func=lambda x: ch_labels.get(x, x),
                       key="pit_ch")
    chapter_id = None if sel == "(all)" else sel

    pits = _pf.list_pitfalls(conn, chapter_id)
    if not pits:
        st.info("No pitfalls recorded for this selection yet.")
    for p in pits:
        with st.expander(f"{p['title']}  ·  {ch_labels.get(p['chapter_id'], '')}"):
            st.markdown(f"> {p['observation']}")
            st.caption(f"{_source_badge(p)}"
                       + (f" · topic: {p['topic']}" if p.get("topic") else ""))
            c1, c2 = st.columns(2)
            with c1:
                if st.button("🃏 Make flashcard", key=f"pit_fc_{p['id']}"):
                    cid = _pf.make_flashcard(conn, p["id"])
                    st.success(f"Flashcard #{cid} created — find it in "
                               f"Flashcards (deck: pitfalls).")
            with c2:
                if st.button("Delete", key=f"pit_del_{p['id']}"):
                    _pf.delete_pitfall(conn, p["id"])
                    st.success("Deleted.")
                    st.rerun()

    st.divider()
    with st.expander("➕ Add your own pitfall"):
        ch2 = st.selectbox("Chapter", [c[0] for c in chapters],
                           format_func=lambda x: ch_labels.get(x, x),
                           key="pit_add_ch")
        topic = st.text_input("Topic (e.g. Allowances)", key="pit_add_topic")
        title = st.text_input("Title (short)", key="pit_add_title")
        obs = st.text_area("Observation", key="pit_add_obs", height=100)
        page = st.text_input("Page (optional)", key="pit_add_page")
        if st.button("Save pitfall", key="pit_add_go"):
            if not title.strip() or not obs.strip():
                st.warning("Title and observation are required.")
            else:
                try:
                    pg = int(page) if page.strip() else None
                except ValueError:
                    pg = None
                _pf.add_pitfall(conn, ch2, topic.strip(), title.strip(),
                                obs.strip(), pg)
                st.success("Pitfall saved.")
                st.rerun()
