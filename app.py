"""CAPT Taxation — Exam Preparation System (foundation entry point).

Offline-first desktop study app for ICAP CAF-2 Taxation. No AI, no network.
Each sidebar section delegates to ui.<module>.render(conn); modules that are
not built yet show a placeholder so the app always boots.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from core.db import get_conn, init_db, integrity_check  # noqa: E402
from core.db import rebuild_fts  # noqa: E402
from core.content_pack import get_active_book, load_pack  # noqa: E402
from core.content_pack import (  # noqa: E402
    is_demo_stuck, repair_reload_real_pack)
from core import uihelpers as uh  # noqa: E402
from core import approaches as _approaches  # noqa: E402
from core import pitfalls as _pitfalls  # noqa: E402

APP_TITLE = "CAPT Tax Prep"
DB_PATH = ROOT / "data" / "app.db"
SAMPLE_PACK = ROOT / "data" / "sample_pack.json"
REAL_PACK = ROOT / "data" / "content_pack.json"


def _initial_pack():
    """Which pack to auto-load on a fresh database.

    The real textbook pack wins when present; the synthetic DEMO pack is
    only a fallback. Returns (path, is_demo).
    """
    if REAL_PACK.is_file():
        return REAL_PACK, False
    if SAMPLE_PACK.is_file():
        return SAMPLE_PACK, True
    return None, False

# (sidebar label, ui module name). Modules not yet built render a placeholder.
NAV_ITEMS = [
    ("Dashboard", "ui.dashboard"),
    ("Textbook Library", "ui.library"),
    ("Syllabus", "ui.syllabus"),
    ("Learn", "ui.learn"),
    ("Chapter Maps", "ui.maps"),
    ("Flashcards", "ui.flashcards"),
    ("Question Bank", "ui.questions"),
    ("Answer Approaches", "ui.approaches"),
    ("Calculation Practice", "ui.calc_practice"),
    ("Mock Examinations", "ui.exams"),
    ("Pitfalls", "ui.pitfalls"),
    ("Tax Rule Library", "ui.rules"),
    ("Revision Planner", "ui.revision"),
    ("Progress Analytics", "ui.analytics"),
    ("Settings & Backup", "ui.settings"),
]


@st.cache_resource
def _get_conn():
    """Open the DB once per process, initialise schema, run integrity check,
    and auto-load the synthetic DEMO pack on first run."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn(DB_PATH)
    init_db(conn)
    integrity_check(conn)
    existing = conn.execute("SELECT COUNT(*) AS c FROM books").fetchone()["c"]
    if existing == 0:
        pack, is_demo = _initial_pack()
        if pack is not None:
            load_pack(conn, pack, is_demo=is_demo)
    # Idempotent feature seeds (no-ops when their source content is absent).
    _approaches.seed_approaches(conn)
    if _pitfalls.seed_pitfalls(conn):
        rebuild_fts(conn)  # index newly seeded pitfalls for search
    return conn


def _render_module(module_name: str, conn) -> None:
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        st.info("Module not yet built — coming soon.")
        return
    render = getattr(module, "render", None)
    if not callable(render):
        st.info("Module not yet built — coming soon.")
        return
    render(conn)


def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    if "nav" not in st.session_state:
        st.session_state["nav"] = NAV_ITEMS[0][0]

    try:
        conn = _get_conn()
    except RuntimeError as exc:
        st.error(f"Database integrity check failed: {exc}")
        st.stop()

    book = get_active_book(conn)

    # --- sidebar -----------------------------------------------------------
    with st.sidebar:
        st.title("📚 " + APP_TITLE)
        st.caption("CAF-2 Taxation · offline study system")
        choice = st.radio(
            "Sections",
            [label for label, _ in NAV_ITEMS],
            index=[label for label, _ in NAV_ITEMS].index(st.session_state["nav"]),
            label_visibility="collapsed",
        )
        st.session_state["nav"] = choice
        st.divider()
        if book is not None:
            st.caption(f"Book: {book['title']}")
            if (book["is_demo"] or 0) == 1:
                st.caption("⚠️ DEMO data")

    # --- main area ----------------------------------------------------------
    if uh.is_demo_book(conn):
        uh.demo_banner()
        if is_demo_stuck(conn, REAL_PACK):
            st.error(
                "⚠️ Your real textbook is in the app folder, but the app is "
                "showing demo data because a leftover demo database was "
                "found. One click fixes it — your real book (14 chapters, "
                "131 questions) will load. The demo data holds no study "
                "progress, so nothing of yours is lost.")
            if st.button("🔄 Load my real textbook now", type="primary"):
                conn.close()
                repair_reload_real_pack(DB_PATH)
                st.cache_resource.clear()
                st.rerun()
            st.stop()
    if book is not None and (book["tax_context_note"] or "").strip():
        st.info(f"🧾 Tax context: {book['tax_context_note']}")

    module_name = dict(NAV_ITEMS)[st.session_state["nav"]]
    _render_module(module_name, conn)


if __name__ == "__main__":
    main()
