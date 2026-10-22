"""Textbook Library section: book info, document import workflow
(upload → extract → REVIEW → confirm), and content-pack JSON loading.

Uses core/uihelpers.py when it exists (guarded import); otherwise local
fallbacks with the same names so integration stays trivial.
"""

from __future__ import annotations

import inspect
import os

import streamlit as st

from core import importer, pageshot

try:  # foundation-owned shared helpers; may not exist yet
    from core.uihelpers import (  # type: ignore
        get_setting, set_setting, is_demo_book, demo_banner,
        chapter_options, topic_options, source_ref_line,
        show_source_page, status_chip,
    )
    _HAS_UIHELPERS = True
except Exception:  # pragma: no cover - fallback until foundation lands
    _HAS_UIHELPERS = False

    def get_setting(conn, key, default=None):
        try:
            row = conn.execute("SELECT value FROM settings WHERE key = ?",
                               (key,)).fetchone()
            return row[0] if row else default
        except Exception:
            return default

    def set_setting(conn, key, value):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                     (key, str(value)))
        conn.commit()

    def is_demo_book(conn, book_id):
        row = conn.execute("SELECT is_demo FROM books WHERE id = ?",
                           (book_id,)).fetchone()
        return bool(row and row[0])

    def demo_banner():
        st.warning("DEMO data — synthetic sample content for development, "
                   "not from the real textbook.")

    def chapter_options(conn, book_id):
        return [(r[0], f"Ch {r[1]}: {r[2]}") for r in conn.execute(
            "SELECT id, number, title FROM chapters WHERE book_id = ? ORDER BY number",
            (book_id,))]

    def topic_options(conn, chapter_id):
        return [(r[0], r[1]) for r in conn.execute(
            "SELECT id, name FROM topics WHERE chapter_id = ? ORDER BY sort_order",
            (chapter_id,))]

    def source_ref_line(source_ref):
        return f"Source: {source_ref}" if source_ref else ""

    def show_source_page(pdf_path, page_no, dpi=110):
        try:
            png = pageshot.render_page(pdf_path, page_no, dpi=dpi)
            st.image(png, caption=f"Page {page_no} (source PDF)")
        except FileNotFoundError as e:
            st.error(str(e))
        except Exception as e:  # noqa: BLE001
            st.error(f"Could not render page {page_no}: {e}")

    def status_chip(text, kind="info"):
        {"info": st.info, "ok": st.success, "warn": st.warning,
         "err": st.error}.get(kind, st.info)(text)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _uploads_dir() -> str:
    d = os.path.join(_project_root(), "data", "uploads")
    os.makedirs(d, exist_ok=True)
    return d


def _all_books(conn):
    try:
        return conn.execute(
            "SELECT id, title, volume, edition, author, publisher, source_file, "
            "page_count, tax_context_note, solutions_note, is_demo "
            "FROM books ORDER BY id DESC").fetchall()
    except Exception:
        return []


def _active_book_id(conn):
    books = _all_books(conn)
    if not books:
        return None
    saved = get_setting(conn, "active_book_id")
    ids = [b[0] for b in books]
    try:
        if saved is not None and int(saved) in ids:
            return int(saved)
    except (TypeError, ValueError):
        pass
    # prefer the newest non-demo book, else the newest book
    for b in books:
        if not b[10]:
            return b[0]
    return books[0][0]


def _resolve_source_file(book_row):
    """Best-effort path to the book's PDF for 'View source page'."""
    source_file = book_row[6] or ""
    if source_file and os.path.isfile(source_file):
        return source_file
    cand = os.path.join(_uploads_dir(), os.path.basename(source_file))
    if os.path.isfile(cand):
        return cand
    assets = os.path.join(_project_root(), "assets", os.path.basename(source_file))
    if os.path.isfile(assets):
        return assets
    return None


def _page_stats(conn, book_id):
    try:
        total = conn.execute("SELECT COUNT(*) FROM pages WHERE book_id = ?",
                             (book_id,)).fetchone()[0]
        failed = conn.execute(
            "SELECT COUNT(*) FROM pages WHERE book_id = ? AND failed = 1",
            (book_id,)).fetchone()[0]
        slides = conn.execute(
            "SELECT COUNT(*) FROM slides s JOIN pages p ON s.page_n = p.n "
            "WHERE p.book_id = ?", (book_id,)).fetchone()[0]
    except Exception:
        total = failed = slides = 0
    return total, failed, slides


# --------------------------------------------------------------------------
# main render
# --------------------------------------------------------------------------

def render(conn):
    st.header("Textbook Library")

    books = _all_books(conn)
    active_id = _active_book_id(conn)

    # ---- book switcher / info -------------------------------------------
    if books:
        labels = {b[0]: f"{b[1]} ({b[3] or 'no edition'})" + (" [DEMO]" if b[10] else "")
                  for b in books}
        sel = st.selectbox("Active book", options=[b[0] for b in books],
                           format_func=lambda i: labels[i],
                           index=[b[0] for b in books].index(active_id))
        if sel != active_id:
            set_setting(conn, "active_book_id", sel)
            active_id = sel
            st.rerun()

        book = next(b for b in books if b[0] == active_id)
        if is_demo_book(conn, active_id):
            demo_banner()
        with st.container(border=True):
            st.subheader(book[1])
            meta = []
            if book[2]:
                meta.append(f"Volume: {book[2]}")
            if book[3]:
                meta.append(f"Edition: {book[3]}")
            if book[4]:
                meta.append(f"Author: {book[4]}")
            if book[5]:
                meta.append(f"Publisher: {book[5]}")
            st.caption(" · ".join(meta) if meta else "No bibliographic details recorded.")
            total, failed, slides = _page_stats(conn, active_id)
            c1, c2, c3 = st.columns(3)
            c1.metric("Pages imported", total)
            c2.metric("Slides", slides)
            c3.metric("Pages needing review", failed,
                      delta="action needed" if failed else None)
            if book[8]:
                st.info(f"Tax context: {book[8]}")
            if book[9]:
                st.caption(f"Solutions note: {book[9]}")
            if failed:
                with st.expander(f"⚠ {failed} page(s) flagged for manual review"):
                    try:
                        rows = conn.execute(
                            "SELECT n FROM pages WHERE book_id = ? AND failed = 1 "
                            "ORDER BY n", (active_id,)).fetchall()
                        st.write("Failed pages:", ", ".join(str(r[0]) for r in rows))
                        st.caption("Re-import with OCR, or fix the text manually — "
                                   "nothing was silently discarded.")
                    except Exception:
                        pass
    else:
        st.info("No books in the library yet. Import a textbook below to begin.")

    st.divider()

    # ---- import workflow -------------------------------------------------
    imp = st.session_state.get("lib_import")
    if imp and imp.get("stage") == "review":
        _render_review(conn, imp)
        return

    st.subheader("Import a textbook")
    up = st.file_uploader("Choose a file", type=["pdf", "docx", "txt"],
                          key="lib_uploader")
    col_a, col_b = st.columns(2)
    with col_a:
        title = st.text_input("Book title", key="lib_title",
                              placeholder="e.g. Taxation: Principles and Compliance")
    with col_b:
        edition = st.text_input("Edition (optional)", key="lib_edition")
    use_ocr = st.checkbox("Run OCR on image-heavy pages (needs rapidocr_onnxruntime)",
                          value=False, key="lib_ocr",
                          help="Pages whose text layer has <50 characters are "
                               "flagged; OCR fills them in and marks them origin='ocr'.")
    if st.button("Start import", disabled=not up or not title.strip(),
                 key="lib_start"):
        _start_import(conn, up, title.strip(), edition.strip(), use_ocr)

    st.divider()

    # ---- content pack JSON ----------------------------------------------
    st.subheader("Load a content-pack JSON")
    st.caption("Structured packs (docs/CONTENT_PACK_SCHEMA.md) import chapters, "
               "pages, slides and questions in one step.")
    pack = st.file_uploader("Choose a .json pack", type=["json"], key="lib_pack")
    if st.button("Load content pack", disabled=not pack, key="lib_pack_load"):
        _load_pack(conn, pack)


def _start_import(conn, uploaded_file, title, edition, use_ocr):
    data = uploaded_file.getvalue()
    safe_name = os.path.basename(uploaded_file.name)
    dest = os.path.join(_uploads_dir(), safe_name)
    base, ext = os.path.splitext(safe_name)
    i = 1
    while os.path.exists(dest):
        dest = os.path.join(_uploads_dir(), f"{base}_{i}{ext}")
        i += 1
    with open(dest, "wb") as fh:
        fh.write(data)

    with st.spinner("Extracting text…"):
        try:
            result = importer.import_document(
                conn, dest, title, edition=edition, ocr=use_ocr)
        except importer.UnsupportedFormatError as e:
            st.error(str(e))
            return
        except Exception as e:  # noqa: BLE001
            st.error(f"Import failed: {e}")
            return

    if result.get("ocr_missing"):
        st.warning("rapidocr_onnxruntime is not installed — image-heavy pages "
                   "were flagged for manual review instead of OCR'd.")
    st.session_state["lib_import"] = {
        "stage": "review",
        "book_id": result["book_id"],
        "saved_path": dest,
        "page_count": result["page_count"],
        "failed_pages": result["failed_pages"],
        "image_heavy_pages": result["image_heavy_pages"],
        "suggestions": result["suggestions"],
        "ocr_used": result["ocr_used"],
    }
    set_setting(conn, "active_book_id", result["book_id"])
    st.rerun()


def _render_review(conn, imp):
    book_id = imp["book_id"]
    st.subheader("Review import — confirm chapter & topic boundaries")
    st.caption("Nothing is final until you press **Confirm import**. "
               "Edit titles and page ranges; every change is logged.")

    # never silently discard: explicit counts
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Pages extracted", imp["page_count"])
    c2.metric("Failed (flagged)", len(imp["failed_pages"]))
    c3.metric("Image-heavy", len(imp["image_heavy_pages"]))
    c4.metric("OCR filled", "yes" if imp["ocr_used"] else "no")
    if imp["failed_pages"]:
        st.warning(f"Pages with failed extraction (stay flagged for manual review): "
                   f"{', '.join(map(str, imp['failed_pages']))}")
    if imp["image_heavy_pages"] and not imp["ocr_used"]:
        st.info(f"Image-heavy pages (thin text layer): "
                f"{', '.join(map(str, imp['image_heavy_pages']))}")

    st.markdown("### Suggested chapters")
    st.caption("Confidence: **high** = explicit 'CHAPTER n' marker found; "
               "**medium** = numbered heading; **low** = fallback covering the "
               "whole document — please fix the boundaries.")

    chapter_plan = []
    topic_plan = []
    for i, sug in enumerate(imp["suggestions"]):
        with st.expander(
                f"Suggestion {i + 1}: Ch {sug['number']} — {sug['title']} "
                f"(pp. {sug['page_start']}–{sug['page_end']}, {sug['confidence']})",
                expanded=(sug["confidence"] == "low")):
            cc1, cc2, cc3 = st.columns([1, 3, 2])
            number = cc1.number_input("Number", value=int(sug["number"]),
                                      min_value=1, key=f"ch_num_{i}")
            ch_title = cc2.text_input("Title", value=sug["title"], key=f"ch_title_{i}")
            ps = cc3.number_input("Page start", value=int(sug["page_start"]),
                                  min_value=1, key=f"ch_ps_{i}")
            pe = cc3.number_input("Page end", value=int(sug["page_end"]),
                                  min_value=1, key=f"ch_pe_{i}")
            topics_raw = st.text_area(
                "Topics in this chapter (one per line, optional)",
                key=f"ch_topics_{i}",
                placeholder="e.g.\nSalary — allowances\nSalary — perquisites")
            ch_id = f"imp_{book_id}_ch{i}"
            chapter_plan.append({
                "id": ch_id, "number": number, "title": ch_title,
                "page_start": min(ps, pe), "page_end": max(ps, pe),
            })
            for j, tname in enumerate(
                    [t.strip() for t in topics_raw.splitlines() if t.strip()]):
                topic_plan.append({
                    "id": f"{ch_id}_t{j}", "chapter_id": ch_id,
                    "name": tname, "sort_order": j,
                })

    st.markdown("### Failed pages")
    page_overrides = {}
    if imp["failed_pages"]:
        st.write("Tick a page once you have fixed its text manually — it will "
                 "be unflagged (the action is logged).")
        for n in imp["failed_pages"]:
            done = st.checkbox(f"Page {n}: text fixed manually", key=f"pg_fix_{n}")
            if done:
                page_overrides[n] = {"failed": False}
            pv = st.toggle(f"Preview page {n}", key=f"pg_view_{n}")
            if pv:
                show_source_page(imp["saved_path"], n)
    else:
        st.caption("No failed pages — every page extracted cleanly.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ Confirm import", type="primary", key="lib_confirm"):
            try:
                stats = importer.confirm_import(
                    conn, book_id, chapter_plan,
                    topic_plan=topic_plan, page_overrides=page_overrides)
            except Exception as e:  # noqa: BLE001
                st.error(f"Confirm failed: {e}")
                return
            st.session_state.pop("lib_import", None)
            for k in list(st.session_state.keys()):
                if k.startswith(("ch_num_", "ch_title_", "ch_ps_", "ch_pe_",
                                  "ch_topics_", "pg_fix_", "pg_view_")):
                    st.session_state.pop(k, None)
            st.success(f"Import confirmed: {stats['chapters']} chapter(s), "
                       f"{stats['topics']} topic(s), "
                       f"{stats['corrections_logged']} correction(s) logged. "
                       "Search index rebuilt.")
            st.rerun()
    with col2:
        if st.button("Discard this import", key="lib_discard"):
            try:
                conn.execute("DELETE FROM pages WHERE book_id = ?", (book_id,))
                conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
                conn.commit()
            except Exception:
                pass
            st.session_state.pop("lib_import", None)
            st.warning("Import discarded — no chapters or topics were kept.")
            st.rerun()


def _load_pack(conn, uploaded_file):
    try:
        from core import content_pack as cp  # type: ignore
    except Exception:
        st.error("Content-pack loader (core.content_pack) is not available yet — "
                 "the foundation team still owns that module.")
        return
    if not hasattr(cp, "load_pack"):
        st.error("core.content_pack has no load_pack() function.")
        return
    data = uploaded_file.getvalue()
    tmp = os.path.join(_uploads_dir(), os.path.basename(uploaded_file.name))
    with open(tmp, "wb") as fh:
        fh.write(data)
    try:
        sig = inspect.signature(cp.load_pack)
        params = list(sig.parameters)
    except (TypeError, ValueError):
        params = []
    with st.spinner("Loading content pack…"):
        try:
            if params[:2] == ["conn", "path"] or params[:1] == ["conn"]:
                result = cp.load_pack(conn, tmp)
            elif params[:2] == ["path", "conn"]:
                result = cp.load_pack(tmp, conn)
            else:  # best effort: try (conn, path) then (path)
                try:
                    result = cp.load_pack(conn, tmp)
                except TypeError:
                    result = cp.load_pack(tmp)
        except Exception as e:  # noqa: BLE001
            st.error(f"Content-pack load failed: {e}")
            return
    st.success(f"Content pack loaded: {result}")
    # refresh FTS through the search wrapper (harmless if already rebuilt)
    try:
        from core import search as _search
        _search.rebuild_index(conn)
    except Exception:
        pass
    st.rerun()


__all__ = ["render"]
