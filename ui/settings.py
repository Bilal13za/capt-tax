"""Settings & Backup section: app settings, manual/auto backup,
restore (guarded), and CSV/Markdown exports.

Uses core/uihelpers.py when it exists (guarded import); otherwise local
fallbacks with the same names so integration stays trivial.
"""

from __future__ import annotations

import datetime
import os

import streamlit as st

from core import backup as backup_core
from core import pageshot, search as search_core

try:  # foundation-owned shared helpers; may not exist yet
    from core.uihelpers import (  # type: ignore
        get_setting, set_setting, status_chip,
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

    def status_chip(text, kind="info"):
        {"info": st.info, "ok": st.success, "warn": st.warning,
         "err": st.error}.get(kind, st.info)(text)


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _default_backup_dir() -> str:
    return os.path.join(_project_root(), "data", "backups")


def _default_export_dir() -> str:
    d = os.path.join(_project_root(), "data", "exports")
    os.makedirs(d, exist_ok=True)
    return d


# --------------------------------------------------------------------------
# main render
# --------------------------------------------------------------------------

def render(conn):
    st.header("Settings & Backup")

    # ---- settings -------------------------------------------------------
    with st.expander("⚙ Settings", expanded=True):
        tax_year = st.text_input(
            "Tax-year context (free text)",
            value=get_setting(conn, "tax_year_context", "") or "",
            help="Which tax year / syllabus the study material targets, e.g. "
                 "'Tax Year 2026 (FY 2025-26), CAF-2 Spring 2027'.")
        auto_days = st.number_input("Auto-backup every N days (0 = disabled)",
                                    min_value=0, max_value=365,
                                    value=int(get_setting(conn, "auto_backup_days",
                                                           "7") or 7))
        dpi = st.number_input("Source-page render DPI", min_value=72, max_value=300,
                              value=int(get_setting(conn, "page_dpi",
                                                    str(pageshot.DEFAULT_DPI))
                                        or pageshot.DEFAULT_DPI))
        bdir = st.text_input("Backup directory",
                             value=get_setting(conn, "backup_dir",
                                               _default_backup_dir()) or
                             _default_backup_dir())
        if st.button("Save settings", key="set_save"):
            set_setting(conn, "tax_year_context", tax_year)
            set_setting(conn, "auto_backup_days", int(auto_days))
            set_setting(conn, "page_dpi", int(dpi))
            set_setting(conn, "backup_dir", bdir)
            st.success("Settings saved.")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("🔄 Rebuild search index", key="set_rebuild_fts"):
            with st.spinner("Rebuilding…"):
                ok = search_core.rebuild_index(conn)
            if ok:
                st.success("Search index rebuilt.")
            else:
                st.warning("core.db is not available yet — nothing rebuilt.")
    with col_b:
        if st.button("🩺 Run integrity check", key="set_integrity"):
            _integrity_check(conn)

    st.divider()

    # ---- backup ----------------------------------------------------------
    st.subheader("Backup")
    backup_dir = get_setting(conn, "backup_dir", _default_backup_dir()) or \
        _default_backup_dir()
    os.makedirs(backup_dir, exist_ok=True)

    if st.button("💾 Create backup now", type="primary", key="bk_now"):
        with st.spinner("Backing up…"):
            try:
                zp = backup_core.backup_db(conn, backup_dir, note="manual")
                st.success(f"Backup created: {os.path.basename(zp)}")
            except Exception as e:  # noqa: BLE001
                st.error(f"Backup failed: {e}")

    _auto_backup_status(conn, backup_dir)

    st.markdown("### Existing backups")
    rows = backup_core.list_backups(conn, backup_dir)
    if not rows:
        st.caption("No backups yet.")
    for r in rows:
        with st.container(border=True):
            c1, c2, c3 = st.columns([3, 1, 1])
            c1.write(f"**{r['filename']}**")
            c1.caption(f"{r['created_at']}" + (f" — {r['note']}" if r['note'] else ""))
            if r["path"]:
                with open(r["path"], "rb") as fh:
                    c2.download_button("⬇ Download", data=fh.read(),
                                       file_name=r["filename"],
                                       key=f"bk_dl_{r['id']}")
                force = c3.checkbox("Force", key=f"bk_force_{r['id']}",
                                    help="Restore even if this is the only backup copy.")
                if c3.button("Restore", key=f"bk_restore_{r['id']}"):
                    _do_restore(conn, r, backup_dir, force)
            else:
                c2.caption("file missing")

    st.divider()

    # ---- exports ----------------------------------------------------------
    st.subheader("Exports")
    ecol1, ecol2 = st.columns(2)
    with ecol1:
        if st.button("Export notes → CSV", key="exp_csv"):
            out = os.path.join(
                _default_export_dir(),
                f"notes-{datetime.date.today().isoformat()}.csv")
            try:
                backup_core.export_notes_csv(conn, out)
                with open(out, "rb") as fh:
                    st.download_button("⬇ Download notes.csv", data=fh.read(),
                                       file_name=os.path.basename(out),
                                       key="exp_csv_dl")
                st.success(f"Wrote {out}")
            except Exception as e:  # noqa: BLE001
                st.error(f"Export failed: {e}")
    with ecol2:
        if st.button("Export progress → Markdown", key="exp_md"):
            out = os.path.join(
                _default_export_dir(),
                f"progress-{datetime.date.today().isoformat()}.md")
            try:
                backup_core.export_progress_markdown(conn, out)
                with open(out, "rb") as fh:
                    st.download_button("⬇ Download progress.md", data=fh.read(),
                                       file_name=os.path.basename(out),
                                       key="exp_md_dl")
                st.success(f"Wrote {out}")
            except Exception as e:  # noqa: BLE001
                st.error(f"Export failed: {e}")


def _auto_backup_status(conn, backup_dir):
    days_raw = get_setting(conn, "auto_backup_days", "0") or "0"
    try:
        days = int(days_raw)
    except (TypeError, ValueError):
        days = 0
    if days <= 0:
        st.caption("Auto-backup is disabled (set N days above to enable).")
        return
    rows = backup_core.list_backups(conn, backup_dir)
    if not rows:
        st.caption(f"Auto-backup: enabled every {days} day(s); no backup yet — "
                   "creating one on next app start.")
        return
    last = rows[0]["created_at"]
    try:
        last_dt = datetime.datetime.fromisoformat(last)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)
        nxt = last_dt + datetime.timedelta(days=days)
        now = datetime.datetime.now(datetime.timezone.utc)
        if nxt <= now:
            status_chip(f"Auto-backup overdue (last: {last}).", "warn")
        else:
            st.caption(f"Auto-backup: last {last}; next due ~{nxt:%Y-%m-%d %H:%M}.")
    except Exception:
        st.caption(f"Auto-backup: last backup {last}.")


def _do_restore(conn, row, backup_dir, force):
    db_file = backup_core.db_file_of_conn(conn)
    if not db_file:
        st.error("Cannot determine the live database file path — restore "
                 "aborted for safety.")
        return
    # guard: never overwrite the only copy unless forced
    siblings = [f for f in os.listdir(backup_dir)
                if f.startswith(backup_core.BACKUP_PREFIX) and f.endswith(".zip")]
    if len(siblings) < 2 and not force:
        st.error("Refusing to restore: this is the only backup copy. "
                 "Create another backup first, or tick **Force** to override — "
                 "a safety copy of the current DB is still taken first.")
        return
    with st.spinner("Restoring (safety backup of current DB first)…"):
        try:
            safety = backup_core.restore_backup(row["path"], db_file,
                                                force=force,
                                                backup_dest_dir=backup_dir)
        except backup_core.RestoreGuardError as e:
            st.error(str(e))
            return
        except Exception as e:  # noqa: BLE001
            st.error(f"Restore failed: {e}")
            return
    st.success(f"Restored from {row['filename']}. "
               f"Safety copy of the previous DB: {os.path.basename(safety)} "
               f"— restart the app to use the restored database.")


def _integrity_check(conn):
    problems = []
    try:
        ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if ic != "ok":
            problems.append(f"PRAGMA integrity_check: {ic}")
    except Exception as e:  # noqa: BLE001
        problems.append(f"integrity_check failed: {e}")
    expected = ["books", "chapters", "topics", "pages", "slides", "items",
                "tax_rules", "questions", "notes", "bookmarks",
                "import_corrections", "settings", "backups", "fts_content"]
    have = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    missing = [t for t in expected if t not in have]
    if missing:
        problems.append("Missing tables: " + ", ".join(missing))
    if problems:
        for p in problems:
            status_chip(p, "err")
    else:
        status_chip("Integrity OK — database is consistent and all "
                    "expected tables exist.", "ok")


__all__ = ["render"]
