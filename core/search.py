"""Full-text search over fts_content with snippet highlighting.

Pure functions — no streamlit import. The FTS5 table is maintained by the
foundation (core.db.rebuild_fts); rebuild_index() below is a thin wrapper
around it.
"""

from __future__ import annotations

import sqlite3

DEFAULT_LIMIT = 50


def _quote_phrase(query: str) -> str:
    """Build a safe FTS5 MATCH expression from a raw user query.

    Splits on whitespace, strips FTS5 operator characters from each token,
    and joins tokens with AND. An empty query yields an empty string (caller
    should return no results rather than MATCH '').
    """
    tokens = []
    for tok in query.split():
        clean = "".join(ch for ch in tok if ch.isalnum() or ch in ("-", "_", ".", "%"))
        clean = clean.strip("-_.")
        if clean:
            # quote tokens containing dots so "12(2)"-style tokens behave
            tokens.append(f'"{clean}"')
    return " AND ".join(tokens)


def search(conn, query, chapter_id=None, topic_id=None, kinds=None, limit=50):
    """Search fts_content and return ranked rows with snippets.

    Returns a list of dicts: {kind, ref_id, title, snippet, chapter_id,
    topic_id, rank}. Snippets use <mark>…</mark> around matched terms.
    Filters: chapter_id, topic_id, kinds (list of kind strings).
    """
    query = (query or "").strip()
    if not query:
        return []
    match = _quote_phrase(query)
    if not match:
        return []

    sql = """
        SELECT f.kind, f.ref_id, f.title,
               snippet(fts_content, 2, '<mark>', '</mark>', ' … ', 24) AS snippet,
               f.chapter_id, f.topic_id, rank
        FROM fts_content f
        WHERE fts_content MATCH ?
    """
    params = [match]
    if chapter_id:
        sql += " AND f.chapter_id = ?"
        params.append(chapter_id)
    if topic_id:
        sql += " AND f.topic_id = ?"
        params.append(topic_id)
    if kinds:
        placeholders = ",".join("?" for _ in kinds)
        sql += f" AND f.kind IN ({placeholders})"
        params.extend(kinds)
    sql += " ORDER BY rank LIMIT ?"
    params.append(int(limit))

    cur = conn.cursor()
    try:
        cur.execute(sql, params)
    except sqlite3.OperationalError:
        # FTS table missing/malformed → no results rather than a crash
        return []
    rows = []
    for kind, ref_id, title, snippet, ch_id, t_id, rank in cur.fetchall():
        rows.append({
            "kind": kind,
            "ref_id": ref_id,
            "title": title or "",
            "snippet": snippet or "",
            "chapter_id": ch_id,
            "topic_id": t_id,
            "rank": rank,
        })
    return rows


def rebuild_index(conn):
    """Rebuild the FTS index via the foundation's rebuild_fts (lazy import).

    Returns True when a rebuild ran, False when core.db is unavailable.
    """
    try:
        from core.db import rebuild_fts  # type: ignore
    except Exception:
        return False
    rebuild_fts(conn)
    return True


__all__ = ["search", "rebuild_index", "DEFAULT_LIMIT"]
