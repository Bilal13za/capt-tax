"""CAPT Taxation — shared UI helpers for all ui.* section modules.

This module's API is stable and documented in docs/UI_CONTRACT.md. Other
teams' ui modules should import these helpers instead of re-implementing
them. Keep the signatures stable; add new helpers at the end.

Public API:
    get_setting(conn, key, default=None)
    set_setting(conn, key, value)
    is_demo_book(conn) -> bool
    demo_banner() -> None
    chapter_options(conn) -> list[(id, label)]
    topic_options(conn, chapter_id=None) -> list[(id, label)]
    source_ref_line(row) -> str
    show_source_page(page_no, label="View source page") -> None
    status_chip(text) -> None
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

DEMO_WARNING_TEXT = "DEMO data — synthetic, not real tax law"

# Expected interface of core.pageshot (owned by the importer team):
#     render_page_image(pdf_path: str, page_no: int, dpi: int = 150)
#         -> PIL.Image.Image | None
PAGESHOT_FUNC = "render_page_image"


# ---------------------------------------------------------------- settings

def get_setting(conn, key: str, default=None):
    """Read a settings value; return *default* when the key is absent."""
    row = conn.execute(
        "SELECT value FROM settings WHERE key=?", (key,)
    ).fetchone()
    return row["value"] if row is not None else default


def set_setting(conn, key: str, value) -> None:
    """Insert or replace a settings value (stored as text)."""
    conn.execute(
        "INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)",
        (key, str(value)),
    )
    conn.commit()


# ---------------------------------------------------------------- demo mode

def is_demo_book(conn, book_id=None) -> bool:
    """True when the given book (or the active book when book_id is None)
    is flagged as demo/synthetic data."""
    if book_id is not None:
        book = conn.execute(
            "SELECT * FROM books WHERE id=?", (book_id,)
        ).fetchone()
    else:
        from core.content_pack import get_active_book

        book = get_active_book(conn)
    return bool(book is not None and (book["is_demo"] or 0) == 1)


def demo_banner() -> None:
    """Standard DEMO warning banner shown on every page using demo data."""
    st.warning(DEMO_WARNING_TEXT)


# ---------------------------------------------------------------- selectors

def chapter_options(conn) -> list:
    """Return [(chapter_id, label)] for the active book's chapters, ordered
    by chapter number then title. Label is 'Ch <number> · <title>'."""
    from core.content_pack import get_active_book

    book = get_active_book(conn)
    if book is None:
        return []
    rows = conn.execute(
        "SELECT id, number, title FROM chapters WHERE book_id=?"
        " ORDER BY number, title",
        (book["id"],),
    ).fetchall()
    options = []
    for r in rows:
        num = r["number"]
        label = (
            f"Ch {num} · {r['title']}" if num is not None else f"{r['id']} · {r['title']}"
        )
        options.append((r["id"], label))
    return options


def topic_options(conn, chapter_id=None) -> list:
    """Return [(topic_id, label)] for topics, optionally filtered to one
    chapter, ordered by sort_order then name."""
    if chapter_id:
        rows = conn.execute(
            "SELECT id, name FROM topics WHERE chapter_id=?"
            " ORDER BY sort_order, name",
            (chapter_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, name FROM topics ORDER BY chapter_id, sort_order, name"
        ).fetchall()
    return [(r["id"], r["name"]) for r in rows]


# ---------------------------------------------------------------- source refs

def _val(row, key, default=None):
    """Read a column from a sqlite3.Row, dict or dataclass-ish object."""
    if row is None:
        return default
    try:
        v = row[key]
    except (KeyError, IndexError, TypeError):
        v = getattr(row, key, default)
    return default if v is None else v


def source_ref_line(row) -> str:
    """Build a human-readable 'p. X · <section>' line from a content row.

    Only uses values the row actually carries (page_start/page_end,
    source_ref, section); never fabricates page numbers. Returns "" when
    nothing is known.
    """
    page_start = _val(row, "page_start")
    page_end = _val(row, "page_end")
    source_ref = _val(row, "source_ref", "") or ""
    section = _val(row, "section", "") or ""

    parts = []
    if page_start is not None:
        try:
            ps = int(page_start)
        except (TypeError, ValueError):
            ps = None
        if ps is not None:
            pe = None
            if page_end is not None:
                try:
                    pe = int(page_end)
                except (TypeError, ValueError):
                    pe = None
            if pe is not None and pe != ps:
                parts.append(f"p. {ps}–{pe}")
            else:
                parts.append(f"p. {ps}")
    if source_ref:
        parts.append(str(source_ref))
    if section:
        parts.append(str(section))
    return " · ".join(parts)


# ---------------------------------------------------------------- source page

def show_source_page(page_no, label: str = "View source page", conn=None) -> None:
    """Expander that renders the real PDF page image as the source of truth.

    Args:
        page_no: printed page number (from the pack; never invented).
        label: expander label.
        conn: optional DB connection used to resolve the book PDF path.

    Never crashes: if core.pageshot is not built yet, or the PDF is missing,
    a clear message is shown instead.
    """
    with st.expander(label):
        if page_no is None:
            st.info("No page number was recorded for this item.")
            return
        try:
            from core import pageshot  # owned by the importer team
        except ImportError:
            st.info(
                "Source-page preview is not available yet "
                "(the page renderer is still being built)."
            )
            return

        pdf_path = _find_pdf(conn)
        if pdf_path is None:
            st.info("The source PDF is not present in assets/ — cannot render the page.")
            return

        render = getattr(pageshot, PAGESHOT_FUNC, None)
        if not callable(render):
            st.info(
                f"The page renderer does not expose {PAGESHOT_FUNC}() yet."
            )
            return
        try:
            image = render(str(pdf_path), int(page_no))
        except Exception as exc:  # never let rendering break the page
            st.info(f"Could not render page {page_no}: {exc}")
            return
        if image is None:
            st.info(f"Page {page_no} could not be rendered from the PDF.")
            return
        st.image(image, caption=f"Source page {page_no} (rendered from the PDF)",
                 use_column_width=True)


def _find_pdf(conn) -> Path | None:
    """Best-effort PDF resolution: book source_file under assets/, else
    assets/book.pdf."""
    root = Path(__file__).resolve().parent.parent
    assets = root / "assets"
    if conn is not None:
        try:
            from core.content_pack import get_active_book

            book = get_active_book(conn)
            if book is not None:
                src = (book["source_file"] or "").strip()
                if src:
                    cand = assets / Path(src).name
                    if cand.is_file():
                        return cand
        except Exception:
            pass
    default = assets / "book.pdf"
    try:
        if default.is_file():
            return default
    except OSError:
        pass
    return None


# ---------------------------------------------------------------- misc

def status_chip(text: str) -> None:
    """Render a small inline status pill (e.g. verification status)."""
    st.markdown(
        '<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
        "border:1px solid #9aa4b2;font-size:0.8em;color:inherit;"
        f'">{text}</span>',
        unsafe_allow_html=True,
    )
