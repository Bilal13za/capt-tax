"""Flashcards workspace: deck stats, due review, card generation.

The review widget is defined here as ``review_widget(conn, chapter_id=None,
topic_id=None, deck_tag=None)`` and is reused (lazy import) by ui/learn.py.
"""

try:
    import streamlit as st
except Exception:  # pragma: no cover - streamlit absent in tests
    st = None

try:
    from core import uihelpers as _uh
except Exception:  # pragma: no cover
    _uh = None

from core import sr as _sr
from core import mapcards as _mc


def _demo_banner(conn):
    if _uh is not None and hasattr(_uh, "demo_banner"):
        try:
            _uh.demo_banner(conn)
            return
        except Exception:
            pass
    if st is not None:
        st.warning("DEMO content — synthetic sample data, not from the textbook.")


def _status_chip(status):
    if _uh is not None and hasattr(_uh, "status_chip"):
        try:
            _uh.status_chip(status)
            return
        except Exception:
            pass
    if st is not None:
        st.caption(f"status: {status}")


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


def review_widget(conn, chapter_id=None, topic_id=None, deck_tag=None):
    """Flashcard review widget: question -> reveal -> Again/Hard/Good/Easy.

    Shared by the Flashcards workspace and the Learn > Memorise tab.
    """
    if st is None:  # pragma: no cover
        return
    due = _sr.due_cards(conn, chapter_id=chapter_id, topic_id=topic_id,
                        deck_tag=deck_tag)
    if not due:
        st.success("No cards due. 🎉")
        return

    idx_key = f"fc_idx_{chapter_id}_{topic_id}_{deck_tag}"
    rev_key = f"fc_revealed_{chapter_id}_{topic_id}_{deck_tag}"
    if idx_key not in st.session_state:
        st.session_state[idx_key] = 0
        st.session_state[rev_key] = False
    idx = st.session_state[idx_key] % len(due)
    card = due[idx]

    st.caption(f"Card {idx + 1} of {len(due)} due")
    st.subheader(card["question_text"] or "(no question text)")
    if card.get("source_ref"):
        st.caption(f"Source: {card['source_ref']}")
    if not st.session_state[rev_key]:
        if st.button("Reveal answer", key=f"reveal_{idx_key}_{card['id']}"):
            st.session_state[rev_key] = True
            st.rerun()
    else:
        st.info(card["answer_text"] or "(no answer text)")
        cols = st.columns(4)
        for col, rating in zip(cols, ("again", "hard", "good", "easy")):
            with col:
                if st.button(rating.capitalize(),
                             key=f"rate_{idx_key}_{card['id']}_{rating}"):
                    _sr.review_card(conn, card["id"], rating)
                    st.session_state[idx_key] = idx + 1
                    st.session_state[rev_key] = False
                    st.rerun()


def render(conn):
    """Flashcards workspace."""
    if st is None:  # pragma: no cover
        return
    st.header("Flashcards")
    _demo_banner(conn)

    chapters = _chapter_options(conn)
    ch_ids = ["(all)"] + [c[0] for c in chapters]
    ch_labels = {"(all)": "All chapters"}
    ch_labels.update({c[0]: c[1] for c in chapters})
    sel_ch = st.selectbox("Chapter", ch_ids,
                          format_func=lambda x: ch_labels.get(x, x))
    chapter_id = None if sel_ch == "(all)" else sel_ch

    filt = st.radio("Show", ["Due only", "Difficult only", "All cards"],
                    horizontal=True)
    deck_tag = st.text_input("Deck tag filter (optional)", "")

    stats = _sr.deck_stats(conn, chapter_id=chapter_id,
                           deck_tag=deck_tag or None)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total cards", stats["total"])
    c2.metric("Due", stats["due"])
    c3.metric("New", stats["new"])
    c4.metric("Lapsed", stats["lapses"])

    if filt == "Difficult only":
        st.info("Difficult = lapses > 0 or ease < 2.0.")
        cards = [c for c in _sr.due_cards(conn, chapter_id=chapter_id,
                                         deck_tag=deck_tag or None, limit=500)
                 if (c.get("lapses") or 0) > 0 or (c.get("ease") or 2.5) < 2.0]
        for c in cards:
            with st.expander(f"{c['question_text'] or '(no text)'} "
                             f"(ease {c.get('ease')}, lapses {c.get('lapses')})"):
                st.write(c["answer_text"])
    elif filt == "All cards":
        rows = conn.execute(
            "SELECT f.*, s.ease, s.lapses FROM flashcards f "
            "LEFT JOIN sr_reviews s ON s.card_id = f.id "
            + ("WHERE f.chapter_id = ?" if chapter_id else ""),
            ([chapter_id] if chapter_id else []),
        ).fetchall()
        for r in rows:
            with st.expander(r["question_text"] or "(no text)"):
                st.write(r["answer_text"])
                st.caption(f"origin: {r['origin']} · ease: {r['ease']} · "
                           f"lapses: {r['lapses']}")
    else:
        review_widget(conn, chapter_id=chapter_id,
                      deck_tag=deck_tag or None)

    st.divider()
    st.subheader("🗺 Map drill")
    st.caption("Review flashcards generated from chapter mind maps "
               "(definition, topic-recall and question-pointer cards). "
               "Same SM-2 scheduling as standard cards.")
    map_chapters = _mc.chapters_with_maps(conn)
    if not map_chapters:
        st.info("No chapter maps available yet.")
    else:
        mc_map = {c["id"]: (f"Ch {c['number']}: {c['title']} "
                            f"({c['cards']}/{c['leaves']} cards)")
                  for c in map_chapters}
        mc_sel = st.selectbox("Chapter", list(mc_map.keys()),
                              format_func=lambda x: mc_map[x],
                              key="mapdrill_ch")
        mc1, mc2 = st.columns(2)
        with mc1:
            if st.button("🃏 Generate map cards for this chapter",
                         key=f"mapdrill_gen_{mc_sel}"):
                n = _mc.generate_map_cards(conn, mc_sel)
                if n:
                    st.success(f"Created {n} map card(s).")
                else:
                    st.info("Map cards already exist — nothing new created.")
                st.rerun()
        with mc2:
            mstats = _sr.deck_stats(conn, chapter_id=mc_sel, deck_tag="map")
            st.caption(f"{mstats['total']} map cards · {mstats['due']} due · "
                       f"{mstats['new']} new")
        if mstats["total"]:
            review_widget(conn, chapter_id=mc_sel, deck_tag="map")
        else:
            st.info("Generate map cards first (button above), or create them "
                    "from the Chapter Maps section.")

    st.divider()
    st.subheader("Generate cards")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Generate cards for this chapter"):
            n = _sr.ensure_cards_for_chapter(conn, chapter_id) if chapter_id \
                else 0
            st.success(f"Created {n} card(s).")
            st.rerun()
    with col2:
        st.caption("Topic-level generation lives in Learn > Memorise.")
