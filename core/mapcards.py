"""Mind-map flashcards ("Map Cards") — pure logic, streamlit-free.

Builds SM-2 flashcards from the chapter-map trees produced by
``core.studymaps.build_chapter_map()``. Three card shapes:

* definition leaves -> front: term + map breadcrumb, back: the full
  definition (looked up from the items table; falls back to the map's
  preview text);
* group/topic nodes -> front: "Under «group», recall the key points",
  back: the leaf labels as a checklist;
* question leaves -> front: the question label, back: a pointer into the
  Question Bank (chapter / page / question id) — never a fabricated answer.

Every card carries origin='map', deck_tag='map', a real page reference and
the breadcrumb it was built from. Generation is idempotent: the
``map_cards`` registry keys on (chapter_id, node_path), so re-running
creates no duplicates.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from core import studymaps as _sm

DECK_TAG = "map"
ORIGIN = "map"
_MAX_LEAF_LABEL = 80
_MAX_GROUP_BACK_LEAVES = 12


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _q(conn: sqlite3.Connection, sql: str, params=()):
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _breadcrumb(chapter: dict, group_name: str) -> str:
    return (f"Ch {chapter.get('number')} · "
            f"{chapter.get('title', '').strip()} → {group_name}")


def _page_ref(chapter: dict, page) -> str:
    if page:
        return f"Ch {chapter.get('number')}, p. {page}"
    return f"Ch {chapter.get('number')}"


def _definition_body(conn: sqlite3.Connection, chapter_id: str,
                     term: str, fallback: str) -> tuple:
    """Return (full body, item_id) for a definition term, else (fallback, None)."""
    rows = _q(
        conn,
        "SELECT id, body FROM items WHERE chapter_id=? AND kind='definition' "
        "AND title=? LIMIT 1",
        (chapter_id, term),
    )
    if rows and (rows[0]["body"] or "").strip():
        return rows[0]["body"].strip(), rows[0]["id"]
    return (fallback or "").strip(), None


def _insert_card(conn: sqlite3.Connection, *, chapter_id: str, node_path: str,
                 question_text: str, answer_text: str, source_ref: str,
                 item_id=None) -> int:
    """Insert a flashcard + registry row. Returns the card id."""
    now = _utcnow()
    cur = conn.execute(
        """INSERT INTO flashcards(item_id, question_text, answer_text,
                                  chapter_id, topic_id, source_ref, origin,
                                  deck_tag, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (item_id, question_text, answer_text, chapter_id, None, source_ref,
         ORIGIN, DECK_TAG, now),
    )
    card_id = cur.lastrowid
    conn.execute(
        "INSERT INTO map_cards(chapter_id, node_path, card_id, created_at)"
        " VALUES (?,?,?,?)",
        (chapter_id, node_path, card_id, now),
    )
    return card_id


def _already(conn: sqlite3.Connection, chapter_id: str, node_path: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM map_cards WHERE chapter_id=? AND node_path=?",
        (chapter_id, node_path),
    ).fetchone() is not None


def generate_map_cards(conn: sqlite3.Connection, chapter_id: str) -> int:
    """Build map cards for one chapter. Idempotent. Returns cards created."""
    tree = _sm.build_chapter_map(conn, chapter_id)
    chapter = tree.get("chapter") or {}
    if not chapter.get("id"):
        return 0
    created = 0
    for group in tree["groups"]:
        gname = group["name"]
        leaves = group["leaves"]
        crumb = _breadcrumb(chapter, gname)

        # --- group card (skip single-leaf topic groups: usually footer noise)
        if not (group["kind"] == "topic" and len(leaves) <= 1):
            node_path = f"g:{gname}"
            if not _already(conn, chapter_id, node_path):
                shown = leaves[:_MAX_GROUP_BACK_LEAVES]
                back_lines = [f"• {l['label']}" for l in shown]
                if len(leaves) > _MAX_GROUP_BACK_LEAVES:
                    back_lines.append(
                        f"…and {len(leaves) - _MAX_GROUP_BACK_LEAVES} more "
                        f"on the Chapter Map")
                pages = sorted({l["page"] for l in leaves if l.get("page")})
                back = (f"{crumb}\n\n" + "\n".join(back_lines)
                        + (f"\n\nSource pages: "
                           f"{pages[0]}–{pages[-1]}" if pages else ""))
                _insert_card(
                    conn, chapter_id=chapter_id, node_path=node_path,
                    question_text=f"Under «{gname}», recall the key points.",
                    answer_text=back,
                    source_ref=_page_ref(chapter, pages[0] if pages else None),
                )
                created += 1

        # --- leaf cards
        for leaf in leaves:
            label = (leaf["label"] or "")[:_MAX_LEAF_LABEL]
            node_path = f"l:{gname}/{label}"
            if _already(conn, chapter_id, node_path):
                continue
            kind = leaf.get("kind")
            page = leaf.get("page")
            if kind == "definition":
                body, item_id = _definition_body(
                    conn, chapter_id, leaf["label"], leaf.get("detail") or "")
                front = f"{leaf['label']}\n({crumb})"
                back = body or "(definition text not found — check the source page)"
            elif kind == "question":
                qid = leaf.get("ref") or ""
                front = f"{leaf['label']}\n({crumb})"
                back = ("Work this from the Question Bank "
                        f"(Ch {chapter.get('number')}, p. {page})."
                        + (f" Question id: {qid}." if qid else "")
                        + " No answer is pre-filled here — attempt it first.")
                item_id = None
            else:  # slide / topic leaf: recall-against-the-map card
                front = f"{leaf['label']}\n({crumb})"
                back = ("Recall what this branch covers, then check yourself "
                        f"against the Chapter Map (p. {page}).")
                item_id = None
            _insert_card(
                conn, chapter_id=chapter_id, node_path=node_path,
                question_text=front, answer_text=back,
                source_ref=_page_ref(chapter, page), item_id=item_id,
            )
            created += 1
    conn.commit()
    return created


def map_card_count(conn: sqlite3.Connection, chapter_id: str | None = None) -> int:
    """How many map cards exist (optionally for one chapter)."""
    if chapter_id is None:
        row = conn.execute("SELECT COUNT(*) c FROM map_cards").fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) c FROM map_cards WHERE chapter_id=?",
            (chapter_id,)).fetchone()
    return row["c"]


def chapters_with_maps(conn: sqlite3.Connection) -> list:
    """Chapter options that have mappable content (for the Map drill picker)."""
    out = []
    for r in _q(conn, "SELECT id, number, title FROM chapters ORDER BY number"):
        tree = _sm.build_chapter_map(conn, r["id"])
        n = sum(len(g["leaves"]) for g in tree["groups"])
        if n:
            out.append({"id": r["id"], "number": r["number"],
                        "title": r["title"], "leaves": n,
                        "cards": map_card_count(conn, r["id"])})
    return out
