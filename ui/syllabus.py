"""Syllabus section — Subject → Chapter → Topic tree, topic record editor,
hierarchy corrections, and official-syllabus keyword mapping.

Pure logic (derive / rename / move / merge / keyword matching) is
streamlit-free so it can be unit-tested headless; only ``render()`` and the
``_render_*`` helpers touch streamlit.

Integration notes (for the foundation team wiring app.py):
  - Exposes ``render(conn)``; ``conn`` is a sqlite3 connection to the app DB.
  - Never imports other teams' ``ui.*`` modules; ``core.uihelpers`` and
    ``core.mastery`` are used only through guarded lazy imports with local
    fallbacks, so this module works whether or not they exist.
  - Every manual hierarchy change is logged to ``import_corrections``.
"""

import json
import re
import sqlite3
from datetime import datetime, timezone

import streamlit as st


# ---------------------------------------------------------------------------
# Small DB / JSON helpers (work with or without row_factory)
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _q(conn, sql, params=()):
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _one(conn, sql, params=()):
    rows = _q(conn, sql, params)
    return rows[0] if rows else None


def _loads(value, default):
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _s(value) -> str:
    return "" if value is None else str(value)


# ---------------------------------------------------------------------------
# Settings (core.uihelpers if present, else direct settings-table access —
# same pattern as core/marking.py)
# ---------------------------------------------------------------------------

def _uihelpers():
    try:
        from core import uihelpers as _uh
        return _uh
    except Exception:
        return None


def get_setting(conn, key, default=None):
    try:
        uh = _uihelpers()
        if uh is not None and hasattr(uh, "get_setting"):
            return uh.get_setting(conn, key, default)
    except Exception:
        pass
    try:
        row = _one(conn, "SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default
    except Exception:
        return default


def set_setting(conn, key, value):
    try:
        uh = _uihelpers()
        if uh is not None and hasattr(uh, "set_setting"):
            uh.set_setting(conn, key, value)
            return
    except Exception:
        pass
    conn.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, _s(value)),
    )
    conn.commit()


def _demo_banner(book):
    """Show the DEMO banner for synthetic packs (helper or local fallback)."""
    uh = _uihelpers()
    fn = getattr(uh, "demo_banner", None) if uh is not None else None
    if callable(fn):
        try:
            fn(book)
            return
        except Exception:
            pass
    if book and book.get("is_demo"):
        st.warning(
            "DEMO content pack — synthetic data for development. "
            "Not the real textbook."
        )


def _is_demo_book(book) -> bool:
    uh = _uihelpers()
    fn = getattr(uh, "is_demo_book", None) if uh is not None else None
    if callable(fn):
        try:
            return bool(fn(book))
        except Exception:
            pass
    return bool(book.get("is_demo")) if book else False


def _chapter_options(conn, book_id):
    uh = _uihelpers()
    fn = getattr(uh, "chapter_options", None) if uh is not None else None
    if callable(fn):
        try:
            return list(fn(conn, book_id))
        except Exception:
            pass
    return [
        (c["id"], f"Ch {c['number']}: {c['title']}")
        for c in _q(conn,
                   "SELECT id, number, title FROM chapters WHERE book_id = ? "
                   "ORDER BY number, id", (book_id,))
    ]


def _topic_options(conn, chapter_id):
    uh = _uihelpers()
    fn = getattr(uh, "topic_options", None) if uh is not None else None
    if callable(fn):
        try:
            return list(fn(conn, chapter_id))
        except Exception:
            pass
    return [
        (t["id"], t["name"])
        for t in _q(conn,
                   "SELECT id, name FROM topics WHERE chapter_id = ? "
                   "ORDER BY sort_order, name", (chapter_id,))
    ]


def _source_ref_line(topic) -> str:
    uh = _uihelpers()
    fn = getattr(uh, "source_ref_line", None) if uh is not None else None
    if callable(fn):
        try:
            return _s(fn(topic))
        except Exception:
            pass
    ref = (topic.get("source_ref") or "").strip()
    return f"Source ref: {ref}" if ref else "Source ref: —"


def _status_chip(status):
    uh = _uihelpers()
    fn = getattr(uh, "status_chip", None) if uh is not None else None
    if callable(fn):
        try:
            fn(status)
            return
        except Exception:
            pass
    st.caption(f"Status: {status}")


# ---------------------------------------------------------------------------
# Book / chapter / topic reads
# ---------------------------------------------------------------------------

def _get_book(conn):
    """Current book: settings 'current_book_id' when valid, else first book."""
    bid = get_setting(conn, "current_book_id", None)
    if bid is not None:
        try:
            book = _one(conn, "SELECT * FROM books WHERE id = ?", (int(bid),))
        except (TypeError, ValueError):
            book = None
        if book:
            return book
    return _one(conn, "SELECT * FROM books ORDER BY id LIMIT 1")


def _chapters(conn, book_id):
    return _q(conn, "SELECT * FROM chapters WHERE book_id = ? ORDER BY number, id",
              (book_id,))


def _topics(conn, chapter_id):
    return _q(conn,
              "SELECT * FROM topics WHERE chapter_id = ? ORDER BY sort_order, name",
              (chapter_id,))


def _book_label(book) -> str:
    bits = [book.get("title") or "Untitled book"]
    for k in ("volume", "edition"):
        if book.get(k):
            bits.append(str(book[k]))
    return " · ".join(bits)


# ---------------------------------------------------------------------------
# Counts (definitions / examples / questions / flashcards / mistakes)
# ---------------------------------------------------------------------------

_ITEM_KINDS = ("definition", "example", "flashcard", "mistake")


def counts_for_topic(conn, topic_id) -> dict:
    counts = {k: 0 for k in ("definitions", "examples", "flashcards", "mistakes")}
    rows = _q(conn,
              "SELECT kind, COUNT(*) AS n FROM items WHERE topic_id = ? GROUP BY kind",
              (topic_id,))
    for r in rows:
        key = {"definition": "definitions", "example": "examples",
               "flashcard": "flashcards", "mistake": "mistakes"}.get(r["kind"])
        if key:
            counts[key] = r["n"]
    q = _one(conn, "SELECT COUNT(*) AS n FROM questions WHERE topic_id = ?",
             (topic_id,))
    counts["questions"] = q["n"] if q else 0
    return counts


def counts_for_chapter(conn, chapter_id) -> dict:
    counts = {k: 0 for k in ("definitions", "examples", "flashcards", "mistakes")}
    rows = _q(conn,
              "SELECT kind, COUNT(*) AS n FROM items WHERE chapter_id = ? GROUP BY kind",
              (chapter_id,))
    for r in rows:
        key = {"definition": "definitions", "example": "examples",
               "flashcard": "flashcards", "mistake": "mistakes"}.get(r["kind"])
        if key:
            counts[key] = r["n"]
    q = _one(conn, "SELECT COUNT(*) AS n FROM questions WHERE chapter_id = ?",
             (chapter_id,))
    counts["questions"] = q["n"] if q else 0
    t = _one(conn, "SELECT COUNT(*) AS n FROM topics WHERE chapter_id = ?",
             (chapter_id,))
    counts["topics"] = t["n"] if t else 0
    return counts


def unverified_definition_count(conn, topic_id) -> int:
    row = _one(conn,
               "SELECT COUNT(*) AS n FROM items WHERE topic_id = ? AND kind = 'definition' "
               "AND status = 'auto_detected_unverified'",
               (topic_id,))
    return row["n"] if row else 0


def _counts_line(counts) -> str:
    return (f"Definitions: {counts['definitions']} · Examples: {counts['examples']} · "
            f"Questions: {counts['questions']} · Flashcards: {counts['flashcards']} · "
            f"Mistakes: {counts['mistakes']}")


# ---------------------------------------------------------------------------
# Revision bookmark (items kind='bookmark', title='revise')
# ---------------------------------------------------------------------------

def is_revision_bookmarked(conn, topic_id) -> bool:
    return _one(conn,
                "SELECT id FROM items WHERE kind = 'bookmark' AND topic_id = ? "
                "AND title = 'revise' LIMIT 1",
                (topic_id,)) is not None


def toggle_revision_bookmark(conn, topic_id) -> bool:
    """Toggle the 'revise' bookmark for a topic. Returns new state (True=marked)."""
    row = _one(conn,
               "SELECT id FROM items WHERE kind = 'bookmark' AND topic_id = ? "
               "AND title = 'revise' LIMIT 1",
               (topic_id,))
    if row:
        conn.execute("DELETE FROM items WHERE id = ?", (row["id"],))
        conn.commit()
        return False
    conn.execute(
        "INSERT INTO items(kind, topic_id, title, origin, status) "
        "VALUES ('bookmark', ?, 'revise', 'student', 'active')",
        (topic_id,),
    )
    conn.commit()
    return True


# ---------------------------------------------------------------------------
# Mastery (core.mastery if present, else "—")
# ---------------------------------------------------------------------------

def mastery_band(conn, topic_id) -> str:
    """Per-topic mastery band from core.mastery when available, else '—'.

    Uses the real ``core.mastery.topic_mastery(conn, topic_id)`` API
    ({"score" 0..100, "band", "reasons", "components"}) and formats it as
    e.g. ``"developing (58%)"``. Falls back gracefully when core.mastery is
    absent or has an unexpected shape.
    """
    try:
        from core import mastery as _m
    except Exception:
        return "—"
    fn = getattr(_m, "topic_mastery", None)
    if callable(fn):
        try:
            val = fn(conn, topic_id)
        except Exception:
            return "—"
        if isinstance(val, dict):
            band = val.get("band")
            if band is None:
                return "—"
            score = val.get("score")
            if isinstance(score, (int, float)):
                return f"{band} ({score:.0f}%)"
            return str(band)
        return "—" if val is None else str(val)
    for attr in ("topic_band", "band_for_topic", "get_topic_band", "band"):
        fn = getattr(_m, attr, None)
        if callable(fn):
            try:
                val = fn(conn, topic_id)
            except Exception:
                continue
            return "—" if val is None else str(val)
    return "—"


# ---------------------------------------------------------------------------
# import_corrections logging + hierarchy mutations (pure logic)
# ---------------------------------------------------------------------------

def log_correction(conn, target_kind, target_id, field, old_value, new_value):
    """Log one manual hierarchy change. Returns the new row id."""
    cur = conn.execute(
        "INSERT INTO import_corrections(target_kind, target_id, field, old_value, "
        "new_value, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (_s(target_kind), _s(target_id), _s(field), _s(old_value), _s(new_value),
         _utcnow()),
    )
    conn.commit()
    return cur.lastrowid


def _new_topic_id(conn, chapter_id) -> str:
    n = 1
    while True:
        tid = f"{chapter_id}-t{n:02d}"
        if not _one(conn, "SELECT id FROM topics WHERE id = ?", (tid,)):
            return tid
        n += 1


def _max_sort_order(conn, chapter_id) -> int:
    row = _one(conn, "SELECT MAX(sort_order) AS m FROM topics WHERE chapter_id = ?",
               (chapter_id,))
    return row["m"] if row and row["m"] is not None else -1


def derive_topics_from_parts(conn, chapter_id, origin="import"):
    """Create one topic per chapter 'part' (parts_json). Idempotent.

    Returns the list of new topic ids (empty when topics already exist or
    the chapter has no parts). Each creation is logged to import_corrections
    with origin recorded.
    """
    ch = _one(conn, "SELECT * FROM chapters WHERE id = ?", (chapter_id,))
    if not ch:
        raise ValueError(f"unknown chapter: {chapter_id}")
    if _one(conn, "SELECT id FROM topics WHERE chapter_id = ? LIMIT 1",
            (chapter_id,)):
        return []
    parts = [str(p).strip() for p in _loads(ch.get("parts_json"), [])]
    parts = [p for p in parts if p]
    if not parts:
        return []
    page_ref = ""
    if ch.get("page_start") is not None and ch.get("page_end") is not None:
        page_ref = f"pp. {ch['page_start']}–{ch['page_end']}"
    new_ids = []
    for i, name in enumerate(parts):
        tid = _new_topic_id(conn, chapter_id)
        conn.execute(
            "INSERT INTO topics(id, chapter_id, name, sort_order, objectives_json, "
            "source_ref) VALUES (?, ?, ?, ?, ?, ?)",
            (tid, chapter_id, name, i, json.dumps([]), page_ref),
        )
        log_correction(conn, "topic", tid, "__created__", "", name)
        log_correction(conn, "topic", tid, "origin", "", origin)
        new_ids.append(tid)
    conn.commit()
    return new_ids


def rename_chapter(conn, chapter_id, new_title) -> bool:
    new_title = (new_title or "").strip()
    if not new_title:
        raise ValueError("chapter title must not be empty")
    ch = _one(conn, "SELECT * FROM chapters WHERE id = ?", (chapter_id,))
    if not ch:
        raise ValueError(f"unknown chapter: {chapter_id}")
    if ch["title"] == new_title:
        return False
    conn.execute("UPDATE chapters SET title = ? WHERE id = ?",
                 (new_title, chapter_id))
    conn.commit()
    log_correction(conn, "chapter", chapter_id, "title", ch["title"], new_title)
    return True


def rename_topic(conn, topic_id, new_name) -> bool:
    new_name = (new_name or "").strip()
    if not new_name:
        raise ValueError("topic name must not be empty")
    t = _one(conn, "SELECT * FROM topics WHERE id = ?", (topic_id,))
    if not t:
        raise ValueError(f"unknown topic: {topic_id}")
    if t["name"] == new_name:
        return False
    conn.execute("UPDATE topics SET name = ? WHERE id = ?", (new_name, topic_id))
    conn.commit()
    log_correction(conn, "topic", topic_id, "name", t["name"], new_name)
    return True


def reorder_topics(conn, chapter_id, ordered_ids) -> int:
    """Apply a new topic order (list of topic ids). Returns # of rows changed."""
    current = [t["id"] for t in _topics(conn, chapter_id)]
    if set(ordered_ids) != set(current):
        raise ValueError("ordered_ids must contain exactly the chapter's topics")
    changed = 0
    for i, tid in enumerate(ordered_ids):
        old = _one(conn, "SELECT sort_order FROM topics WHERE id = ?", (tid,))
        if old and old["sort_order"] != i:
            conn.execute("UPDATE topics SET sort_order = ? WHERE id = ?", (i, tid))
            log_correction(conn, "topic", tid, "sort_order", old["sort_order"], i)
            changed += 1
    conn.commit()
    return changed


def move_topic_step(conn, topic_id, direction) -> bool:
    """Move a topic one step up (-1) / down (+1) within its chapter."""
    t = _one(conn, "SELECT * FROM topics WHERE id = ?", (topic_id,))
    if not t:
        raise ValueError(f"unknown topic: {topic_id}")
    ids = [x["id"] for x in _topics(conn, t["chapter_id"])]
    i = ids.index(topic_id)
    j = i + direction
    if j < 0 or j >= len(ids):
        return False
    ids[i], ids[j] = ids[j], ids[i]
    reorder_topics(conn, t["chapter_id"], ids)
    return True


def move_topic(conn, topic_id, new_chapter_id) -> bool:
    """Move a topic to another chapter (appended at the end)."""
    t = _one(conn, "SELECT * FROM topics WHERE id = ?", (topic_id,))
    if not t:
        raise ValueError(f"unknown topic: {topic_id}")
    ch = _one(conn, "SELECT id FROM chapters WHERE id = ?", (new_chapter_id,))
    if not ch:
        raise ValueError(f"unknown chapter: {new_chapter_id}")
    if t["chapter_id"] == new_chapter_id:
        return False
    old_chapter, old_order = t["chapter_id"], t["sort_order"]
    new_order = _max_sort_order(conn, new_chapter_id) + 1
    conn.execute("UPDATE topics SET chapter_id = ?, sort_order = ? WHERE id = ?",
                 (new_chapter_id, new_order, topic_id))
    conn.commit()
    log_correction(conn, "topic", topic_id, "chapter_id", old_chapter, new_chapter_id)
    log_correction(conn, "topic", topic_id, "sort_order", old_order, new_order)
    return True


def create_topic(conn, chapter_id, name, source_ref="") -> str:
    """Create a new topic under a chapter. Returns the new topic id."""
    name = (name or "").strip()
    if not name:
        raise ValueError("topic name must not be empty")
    if not _one(conn, "SELECT id FROM chapters WHERE id = ?", (chapter_id,)):
        raise ValueError(f"unknown chapter: {chapter_id}")
    tid = _new_topic_id(conn, chapter_id)
    order = _max_sort_order(conn, chapter_id) + 1
    conn.execute(
        "INSERT INTO topics(id, chapter_id, name, sort_order, objectives_json, "
        "source_ref) VALUES (?, ?, ?, ?, ?, ?)",
        (tid, chapter_id, name, order, json.dumps([]), (source_ref or "").strip()),
    )
    conn.commit()
    log_correction(conn, "topic", tid, "__created__", "", name)
    return tid


def merge_topics(conn, primary_id, secondary_ids):
    """Merge secondary topics into the primary topic.

    Moves linked items/questions bookmarks to the primary, unions learning
    objectives, deletes the secondaries. Every step is logged.
    """
    primary = _one(conn, "SELECT * FROM topics WHERE id = ?", (primary_id,))
    if not primary:
        raise ValueError(f"unknown topic: {primary_id}")
    secondaries = [s for s in secondary_ids if s != primary_id]
    if not secondaries:
        raise ValueError("choose at least one topic to merge into the primary")
    objectives = list(_loads(primary.get("objectives_json"), []))
    for sid in secondaries:
        sec = _one(conn, "SELECT * FROM topics WHERE id = ?", (sid,))
        if not sec:
            raise ValueError(f"unknown topic: {sid}")
        if sec["chapter_id"] != primary["chapter_id"]:
            raise ValueError("can only merge topics within the same chapter")
        conn.execute("UPDATE items SET topic_id = ? WHERE topic_id = ?",
                     (primary_id, sid))
        conn.execute("UPDATE questions SET topic_id = ? WHERE topic_id = ?",
                     (primary_id, sid))
        for obj in _loads(sec.get("objectives_json"), []):
            if obj not in objectives:
                objectives.append(obj)
        conn.execute("DELETE FROM topics WHERE id = ?", (sid,))
        log_correction(conn, "topic", sid, "__merged_into__", sec["name"], primary_id)
    if objectives != _loads(primary.get("objectives_json"), []):
        old = primary.get("objectives_json")
        new = json.dumps(objectives)
        conn.execute("UPDATE topics SET objectives_json = ? WHERE id = ?",
                     (new, primary_id))
        log_correction(conn, "topic", primary_id, "objectives_json", old, new)
    conn.commit()
    return primary_id


# ---------------------------------------------------------------------------
# Official-syllabus keyword matching (deterministic token overlap)
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset(
    "a an the and or of to in on for with by from as at is are was were be been "
    "being this that these those it its into over under between through during "
    "after before about which who whom whose will shall may can could would should "
    "must each other more most such no not any all per vs including include "
    "following follow follows related relating".split()
)
# Words so common in a tax syllabus that they carry no matching signal.
_TAX_GENERIC = frozenset(
    "tax taxation taxes income principle principles compliance compliant "
    "pakistan fbr".split()
)


def tokenize(text) -> list:
    toks = re.findall(r"[a-z0-9]+", (text or "").lower())
    return [t for t in toks
            if len(t) >= 3 and t not in _STOPWORDS and t not in _TAX_GENERIC]


def match_syllabus_lines(syllabus_lines, entries, min_score=2):
    """Keyword-match syllabus lines against chapter/topic entries.

    ``entries``: list of dicts with keys ``kind`` ('chapter'|'topic'), ``id``,
    ``label``. Returns ``{line: [(entry, score), ...]}`` sorted by score desc
    then label; lines with no overlap map to ``[]``. Fully deterministic.
    """
    scored_entries = [(e, set(tokenize(e.get("label", "")))) for e in entries]
    out = {}
    for line in syllabus_lines:
        line_toks = set(tokenize(line))
        cands = []
        for entry, entry_toks in scored_entries:
            if not line_toks or not entry_toks:
                continue
            score = len(line_toks & entry_toks)
            if score >= min_score or (score >= 1 and len(line_toks) <= 4):
                cands.append((entry, score))
        cands.sort(key=lambda c: (-c[1], c[0].get("label", "")))
        out[line] = cands
    return out


# ---------------------------------------------------------------------------
# render()
# ---------------------------------------------------------------------------

def render(conn):
    st.header("Syllabus")
    book = _get_book(conn)
    if book is None:
        st.info("No textbook has been imported yet.")
        st.markdown(
            "**Next step:** open the *Textbook Library* section and import your "
            "textbook (a content-pack JSON file). The syllabus tree, topics and "
            "everything else in this app are built from the imported book — "
            "nothing is invented."
        )
        return

    _demo_banner(book)
    st.caption(f"Book: {_book_label(book)}")

    tabs = st.tabs([
        "Syllabus tree",
        "Topic editor",
        "Hierarchy corrections",
        "Syllabus mapping",
    ])
    with tabs[0]:
        _render_tree(conn, book)
    with tabs[1]:
        _render_topic_editor(conn, book)
    with tabs[2]:
        _render_corrections(conn, book)
    with tabs[3]:
        _render_mapping(conn, book)


def _render_tree(conn, book):
    chapters = _chapters(conn, book["id"])
    if not chapters:
        st.info("This book has no chapters yet.")
        st.markdown(
            "Chapters come from the imported content pack. If the importer did "
            "not detect them, you can add chapters through the importer in "
            "*Textbook Library*."
        )
        return
    st.caption("Subject → Chapter → Topic. Expand a chapter, then a topic.")
    for ch in chapters:
        topics = _topics(conn, ch["id"])
        label = (f"Ch {ch['number']}: {ch['title']} — "
                 f"pp. {ch['page_start']}–{ch['page_end']} "
                 f"({len(topics)} topic{'s' if len(topics) != 1 else ''})")
        with st.expander(label):
            parts = [str(p) for p in _loads(ch.get("parts_json"), []) if str(p).strip()]
            if parts:
                st.markdown("**Chapter parts:** " + "; ".join(parts))
            cc = counts_for_chapter(conn, ch["id"])
            st.caption(_counts_line(cc))
            if not topics:
                st.warning("No topics under this chapter yet.")
                if parts:
                    if st.button("Derive topics from chapter parts",
                                 key=f"derive_{ch['id']}"):
                        new_ids = derive_topics_from_parts(conn, ch["id"])
                        st.success(f"Created {len(new_ids)} topic(s) from chapter parts.")
                        st.rerun()
                else:
                    st.caption("This chapter has no parts list — add a topic "
                               "manually in *Hierarchy corrections*.")
                continue
            for t in topics:
                with st.expander(f"{t['name']}"):
                    st.write(_source_ref_line(t))
                    tc = counts_for_topic(conn, t["id"])
                    st.caption(_counts_line(tc))
                    st.caption(f"Mastery: {mastery_band(conn, t['id'])}")
                    n_unver = unverified_definition_count(conn, t["id"])
                    if n_unver:
                        st.warning(
                            f"{n_unver} auto-detected definition(s) are unverified — "
                            "verify them in the Tax Rule Library before treating "
                            "them as confirmed."
                        )
                    objectives = _loads(t.get("objectives_json"), [])
                    if objectives:
                        st.markdown("**Learning objectives:**")
                        for obj in objectives[:5]:
                            st.markdown(f"- {obj}")
                        if len(objectives) > 5:
                            st.caption(f"…and {len(objectives) - 5} more "
                                       "(see Topic editor).")
                    rev = is_revision_bookmarked(conn, t["id"])
                    _status_chip("marked for revision" if rev else "not marked for revision")


def _render_topic_editor(conn, book):
    st.subheader("Topic record editor")
    chapters = _chapters(conn, book["id"])
    if not chapters:
        st.info("No chapters yet — import a book first (Textbook Library).")
        return
    ch_opts = [(c["id"], f"Ch {c['number']}: {c['title']}") for c in chapters]
    ch_id = st.selectbox("Chapter", options=[o[0] for o in ch_opts],
                         format_func=dict(ch_opts).get, key="ed_chapter")
    topics = _topics(conn, ch_id)
    if not topics:
        st.info("No topics in this chapter yet — derive them from chapter parts "
                "or add one in *Hierarchy corrections*.")
        return
    t_opts = [(t["id"], t["name"]) for t in topics]
    t_id = st.selectbox("Topic", options=[o[0] for o in t_opts],
                        format_func=dict(t_opts).get, key="ed_topic")
    topic = _one(conn, "SELECT * FROM topics WHERE id = ?", (t_id,))

    st.markdown("### Linked content")
    tc = counts_for_topic(conn, t_id)
    st.caption(_counts_line(tc))
    n_unver = unverified_definition_count(conn, t_id)
    if n_unver:
        st.warning(f"{n_unver} unverified definition(s) linked to this topic.")

    st.markdown("### Mastery & revision")
    st.write(f"Mastery band (computed): **{mastery_band(conn, t_id)}**")
    st.caption("Mastery is computed by the app — it cannot be edited here.")
    rev = is_revision_bookmarked(conn, t_id)
    if st.button("Remove from revision list" if rev else "Mark for revision",
                 key=f"ed_rev_{t_id}"):
        new_state = toggle_revision_bookmark(conn, t_id)
        st.success("Removed from revision list." if not new_state
                   else "Marked for revision.")
        st.rerun()

    st.markdown("### Edit topic")
    with st.form(key=f"ed_form_{t_id}"):
        name = st.text_input("Name", value=topic["name"])
        objectives = _loads(topic.get("objectives_json"), [])
        obj_text = st.text_area("Learning objectives (one per line)",
                                value="\n".join(str(o) for o in objectives),
                                height=120)
        source_ref = st.text_input("Source ref",
                                   value=(topic.get("source_ref") or ""))
        saved = st.form_submit_button("Save changes")
    if saved:
        changed = False
        if name.strip() and name.strip() != topic["name"]:
            rename_topic(conn, t_id, name.strip())
            changed = True
        new_objectives = [ln.strip() for ln in obj_text.splitlines() if ln.strip()]
        if new_objectives != [str(o) for o in objectives]:
            old_json = topic.get("objectives_json")
            new_json = json.dumps(new_objectives)
            conn.execute("UPDATE topics SET objectives_json = ? WHERE id = ?",
                         (new_json, t_id))
            conn.commit()
            log_correction(conn, "topic", t_id, "objectives_json", old_json, new_json)
            changed = True
        if (source_ref or "").strip() != (topic.get("source_ref") or ""):
            old_ref = topic.get("source_ref") or ""
            conn.execute("UPDATE topics SET source_ref = ? WHERE id = ?",
                         ((source_ref or "").strip(), t_id))
            conn.commit()
            log_correction(conn, "topic", t_id, "source_ref", old_ref,
                           (source_ref or "").strip())
            changed = True
        st.success("Topic updated — changes logged to import corrections."
                   if changed else "No changes.")
        if changed:
            st.rerun()


def _render_corrections(conn, book):
    st.subheader("Hierarchy corrections")
    st.caption(
        "Fix the imported hierarchy here. Every change is written to "
        "`import_corrections` with the old and new values — nothing is silent."
    )
    chapters = _chapters(conn, book["id"])
    if not chapters:
        st.info("No chapters yet — import a book first (Textbook Library).")
        return
    ch_opts = [(c["id"], f"Ch {c['number']}: {c['title']}") for c in chapters]
    ch_map = dict(ch_opts)

    st.markdown("#### Rename chapter")
    rc_id = st.selectbox("Chapter", options=[o[0] for o in ch_opts],
                         format_func=ch_map.get, key="rc_chapter")
    rc_new = st.text_input("New chapter title", key="rc_new")
    if st.button("Rename chapter", key="rc_go"):
        try:
            if rename_chapter(conn, rc_id, rc_new):
                st.success("Chapter renamed and logged.")
                st.rerun()
            else:
                st.info("Title unchanged.")
        except ValueError as e:
            st.error(str(e))

    st.markdown("#### Rename topic")
    rt_ch = st.selectbox("Chapter (rename topic)", options=[o[0] for o in ch_opts],
                         format_func=ch_map.get, key="rt_chapter")
    rt_topics = _topics(conn, rt_ch)
    if rt_topics:
        rt_map = {t["id"]: t["name"] for t in rt_topics}
        rt_id = st.selectbox("Topic", options=list(rt_map),
                             format_func=rt_map.get, key="rt_topic")
        rt_new = st.text_input("New topic name", key="rt_new")
        if st.button("Rename topic", key="rt_go"):
            try:
                if rename_topic(conn, rt_id, rt_new):
                    st.success("Topic renamed and logged.")
                    st.rerun()
                else:
                    st.info("Name unchanged.")
            except ValueError as e:
                st.error(str(e))
    else:
        st.caption("No topics in this chapter.")

    st.markdown("#### Reorder topics")
    ro_ch = st.selectbox("Chapter (reorder)", options=[o[0] for o in ch_opts],
                         format_func=ch_map.get, key="ro_chapter")
    ro_topics = _topics(conn, ro_ch)
    if ro_topics:
        for i, t in enumerate(ro_topics):
            c1, c2, c3 = st.columns([7, 1, 1])
            c1.write(f"{i + 1}. {t['name']}")
            if c2.button("↑", key=f"ro_up_{t['id']}", disabled=(i == 0)):
                move_topic_step(conn, t["id"], -1)
                st.rerun()
            if c3.button("↓", key=f"ro_dn_{t['id']}",
                         disabled=(i == len(ro_topics) - 1)):
                move_topic_step(conn, t["id"], +1)
                st.rerun()
    else:
        st.caption("No topics in this chapter.")

    st.markdown("#### Move topic to another chapter")
    mv_ch = st.selectbox("From chapter", options=[o[0] for o in ch_opts],
                         format_func=ch_map.get, key="mv_chapter")
    mv_topics = _topics(conn, mv_ch)
    if mv_topics:
        mv_map = {t["id"]: t["name"] for t in mv_topics}
        mv_id = st.selectbox("Topic", options=list(mv_map),
                             format_func=mv_map.get, key="mv_topic")
        dest_opts = [o for o in ch_opts if o[0] != mv_ch]
        mv_dest = st.selectbox("Destination chapter", options=[o[0] for o in dest_opts],
                               format_func=dict(dest_opts).get, key="mv_dest")
        if st.button("Move topic", key="mv_go"):
            try:
                if move_topic(conn, mv_id, mv_dest):
                    st.success("Topic moved and logged.")
                    st.rerun()
                else:
                    st.info("Topic is already in that chapter.")
            except ValueError as e:
                st.error(str(e))
    else:
        st.caption("No topics in this chapter.")

    st.markdown("#### Create topic")
    ct_ch = st.selectbox("Chapter (new topic)", options=[o[0] for o in ch_opts],
                         format_func=ch_map.get, key="ct_chapter")
    ct_name = st.text_input("Topic name", key="ct_name")
    ct_ref = st.text_input("Source ref (optional)", key="ct_ref")
    if st.button("Create topic", key="ct_go"):
        try:
            tid = create_topic(conn, ct_ch, ct_name, ct_ref)
            st.success(f"Topic created (`{tid}`) and logged.")
            st.rerun()
        except ValueError as e:
            st.error(str(e))

    st.markdown("#### Merge topics")
    mg_ch = st.selectbox("Chapter (merge)", options=[o[0] for o in ch_opts],
                         format_func=ch_map.get, key="mg_chapter")
    mg_topics = _topics(conn, mg_ch)
    if len(mg_topics) >= 2:
        mg_map = {t["id"]: t["name"] for t in mg_topics}
        mg_primary = st.selectbox("Keep this topic (primary)",
                                  options=list(mg_map), format_func=mg_map.get,
                                  key="mg_primary")
        mg_sec = st.multiselect("Merge these into the primary",
                                options=[i for i in mg_map if i != mg_primary],
                                format_func=mg_map.get, key="mg_sec")
        st.caption("Linked definitions, questions, bookmarks, objectives and "
                   "revision marks move to the primary topic; merged topics are "
                   "deleted. All logged.")
        if st.button("Merge topics", key="mg_go", disabled=not mg_sec):
            try:
                merge_topics(conn, mg_primary, mg_sec)
                st.success("Topics merged and logged.")
                st.rerun()
            except ValueError as e:
                st.error(str(e))
    else:
        st.caption("Need at least two topics in the chapter to merge.")

    st.markdown("#### Derive topics from chapter parts")
    missing = [c for c in chapters
               if not _topics(conn, c["id"])
               and _loads(c.get("parts_json"), [])]
    if not missing:
        st.caption("Every chapter that has a parts list already has topics.")
    for c in missing:
        parts = [str(p) for p in _loads(c.get("parts_json"), []) if str(p).strip()]
        if st.button(f"Derive {len(parts)} topic(s) for Ch {c['number']}",
                     key=f"der_{c['id']}"):
            new_ids = derive_topics_from_parts(conn, c["id"])
            st.success(f"Created {len(new_ids)} topic(s); logged as import origin.")
            st.rerun()

    st.markdown("#### Correction history")
    logs = _q(conn, "SELECT * FROM import_corrections ORDER BY id DESC LIMIT 50")
    if logs:
        for lg in logs:
            st.caption(
                f"#{lg['id']} · {lg['target_kind']} `{lg['target_id']}` · "
                f"{lg['field']}: `{lg['old_value']}` → `{lg['new_value']}` "
                f"({lg['created_at']})"
            )
    else:
        st.caption("No corrections logged yet.")


def _render_mapping(conn, book):
    st.subheader("Official syllabus mapping")
    st.markdown(
        "Paste the official ICAP syllabus text below. The app keyword-matches "
        "each line against chapter and topic titles (deterministic token "
        "overlap) and *suggests* links — you confirm the mapping yourself. "
        "Discrepancies are listed, never auto-\"resolved\"."
    )
    saved_text = get_setting(conn, "syllabus_text", "") or ""
    text = st.text_area("Official syllabus text (one item per line)",
                        value=saved_text, height=180, key="map_text")
    if st.button("Save & match", key="map_save_text"):
        set_setting(conn, "syllabus_text", text)
        st.rerun()

    lines = [ln.strip() for ln in saved_text.splitlines() if ln.strip()]
    if not lines:
        st.info("Paste the syllabus text above and press *Save & match*.")
        return

    chapters = _chapters(conn, book["id"])
    entries, topic_chapter = [], {}
    for c in chapters:
        entries.append({"kind": "chapter", "id": c["id"],
                        "label": f"Ch {c['number']}: {c['title']}"})
        for t in _topics(conn, c["id"]):
            entries.append({"kind": "topic", "id": t["id"],
                            "label": f"{t['name']} (Ch {c['number']})"})
            topic_chapter[t["id"]] = c["id"]
    matches = match_syllabus_lines(lines, entries)

    mapping = _loads(get_setting(conn, "syllabus_mapping", "{}"), {})
    st.markdown("#### Chapter ↔ syllabus lines")
    for c in chapters:
        with st.expander(f"Ch {c['number']}: {c['title']}"):
            sugg = []
            for line, cands in matches.items():
                hit = [(e, s) for e, s in cands
                       if e["id"] == c["id"]
                       or topic_chapter.get(e["id"]) == c["id"]]
                if hit:
                    sugg.append((line, max(s for _, s in hit)))
            sugg.sort(key=lambda x: (-x[1], x[0]))
            if sugg:
                st.markdown("**Suggested (keyword overlap — confirm yourself):**")
                for line, score in sugg[:8]:
                    st.caption(f"· (score {score}) {line}")
            else:
                st.caption("No keyword suggestions for this chapter.")
            current = "\n".join(mapping.get(c["id"], []))
            new_val = st.text_area("Mapped syllabus lines (one per line — your call)",
                                   value=current, key=f"mapedit_{c['id']}",
                                   height=100)
            if st.button("Save mapping", key=f"mapsave_{c['id']}"):
                mapping[c["id"]] = [ln.strip() for ln in new_val.splitlines()
                                    if ln.strip()]
                set_setting(conn, "syllabus_mapping", json.dumps(mapping))
                st.success("Mapping saved.")
                st.rerun()

    st.markdown("#### Discrepancies (never auto-resolved)")
    unmatched_lines = [ln for ln, cands in matches.items() if not cands]
    matched_ids = {e["id"] for cands in matches.values() for e, _ in cands}
    mapped_ids = {cid for cid, ls in mapping.items() if ls}
    orphan_entries = [e for e in entries
                      if e["id"] not in matched_ids and e["id"] not in mapped_ids]
    if unmatched_lines:
        st.warning("Syllabus lines with no keyword match:")
        for ln in unmatched_lines:
            st.caption(f"· {ln}")
    else:
        st.caption("Every syllabus line matched at least one chapter/topic.")
    if orphan_entries:
        st.warning("Chapters/topics with no syllabus match and no manual mapping:")
        for e in orphan_entries[:20]:
            st.caption(f"· {e['label']}")
        if len(orphan_entries) > 20:
            st.caption(f"…and {len(orphan_entries) - 20} more.")
    else:
        st.caption("Every chapter/topic is matched or manually mapped.")
