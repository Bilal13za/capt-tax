"""Backup / restore / export for the app database.

Import-safe: no streamlit import at module level.

Safety rules (binding):
  - restore_backup() NEVER overwrites the only copy: it refuses to restore
    unless at least one other backup exists OR force=True is passed, and it
    always auto-backs-up the current DB before replacing it.
"""

from __future__ import annotations

import csv
import datetime
import os
import shutil
import sqlite3
import tempfile
import zipfile

BACKUP_PREFIX = "capt-tax-backup"


def _utcnow() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def _get_conn(conn_or_path):
    if isinstance(conn_or_path, sqlite3.Connection):
        return conn_or_path, False
    return sqlite3.connect(str(conn_or_path)), True


def db_file_of_conn(conn) -> str | None:
    """Best-effort absolute path of the DB file behind a connection."""
    try:
        for _seq, _name, path in conn.execute("PRAGMA database_list").fetchall():
            if _name == "main" and path:
                return os.path.abspath(path)
    except Exception:
        pass
    return None


def _table_exists(conn, name) -> bool:
    cur = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return cur.fetchone() is not None


def _ensure_backup_table(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS backups
           (id INTEGER PRIMARY KEY, filename TEXT, created_at TEXT, note TEXT)""")


def _snapshot_db(conn, tmp_path):
    """Write a consistent snapshot of the DB to tmp_path via the backup API."""
    dest = sqlite3.connect(tmp_path)
    try:
        conn.backup(dest)
    finally:
        dest.close()


def backup_db(conn_or_path, dest_dir, note="") -> str:
    """Create a timestamped zip backup of the DB (+ uploads dir if present).

    Registers a row in the `backups` table. Returns the zip file path.
    """
    conn, close = _get_conn(conn_or_path)
    try:
        _ensure_backup_table(conn)
        os.makedirs(dest_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        filename = f"{BACKUP_PREFIX}-{stamp}.zip"
        # belt-and-braces: never overwrite an existing backup file
        suffix = 1
        while os.path.exists(os.path.join(dest_dir, filename)):
            suffix += 1
            filename = f"{BACKUP_PREFIX}-{stamp}-{suffix}.zip"
        zip_path = os.path.join(dest_dir, filename)

        db_file = db_file_of_conn(conn)
        uploads_dir = None
        if db_file:
            cand = os.path.join(os.path.dirname(db_file), "uploads")
            if os.path.isdir(cand):
                uploads_dir = cand

        with tempfile.TemporaryDirectory() as tmp:
            snap = os.path.join(tmp, "app.db")
            _snapshot_db(conn, snap)
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(snap, "app.db")
                if uploads_dir:
                    for root, _dirs, files in os.walk(uploads_dir):
                        for f in files:
                            full = os.path.join(root, f)
                            rel = os.path.relpath(full, uploads_dir)
                            zf.write(full, os.path.join("uploads", rel))

        conn.execute(
            "INSERT INTO backups (filename, created_at, note) VALUES (?, ?, ?)",
            (filename, _utcnow(), note or ""),
        )
        conn.commit()
        return zip_path
    finally:
        if close:
            conn.close()


def list_backups(conn_or_path, dest_dir=None):
    """Return backup rows newest-first: [{id, filename, created_at, note, path}].

    `path` is filled in when dest_dir is given and the file exists there.
    """
    conn, close = _get_conn(conn_or_path)
    try:
        if not _table_exists(conn, "backups"):
            return []
        rows = conn.execute(
            "SELECT id, filename, created_at, note FROM backups ORDER BY id DESC"
        ).fetchall()
    finally:
        if close:
            conn.close()
    out = []
    for bid, filename, created_at, note in rows:
        p = os.path.join(dest_dir, filename) if dest_dir else None
        out.append({
            "id": bid, "filename": filename, "created_at": created_at,
            "note": note or "",
            "path": p if (p and os.path.isfile(p)) else None,
        })
    return out


class RestoreGuardError(Exception):
    """Raised when restore_backup refuses to run without force=True."""


def restore_backup(zip_path, db_path, force=False, backup_dest_dir=None) -> str:
    """Restore app.db from a backup zip.

    Guard ("never overwrite the only copy"): refuses with RestoreGuardError
    unless at least one other backup zip exists alongside the zip's directory
    OR force=True. Always auto-backs-up the current DB first (into
    backup_dest_dir, defaulting to the backup's own directory).
    Returns the path of the safety backup created.
    """
    zip_path = str(zip_path)
    db_path = str(db_path)
    if not os.path.isfile(zip_path):
        raise FileNotFoundError(f"Backup zip not found: {zip_path}")

    here = os.path.dirname(os.path.abspath(zip_path))
    siblings = [f for f in os.listdir(here)
                if f.startswith(BACKUP_PREFIX) and f.endswith(".zip")]
    if len(siblings) < 2 and not force:
        raise RestoreGuardError(
            "Refusing to restore: this is the only backup copy. "
            "Create another backup first, or pass force=True to override."
        )

    safety_dir = backup_dest_dir or here
    safety_path = None
    if os.path.isfile(db_path):
        safety_path = backup_db(db_path, safety_dir,
                                note="auto: safety copy before restore")

    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        if "app.db" not in names:
            raise ValueError(f"Backup zip is missing app.db: {zip_path}")
        with tempfile.TemporaryDirectory() as tmp:
            zf.extract("app.db", tmp)
            extracted = os.path.join(tmp, "app.db")
            # sanity: it must be a readable sqlite db
            probe = sqlite3.connect(extracted)
            try:
                probe.execute("SELECT 1").fetchone()
            finally:
                probe.close()
            os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
            shutil.copy2(extracted, db_path)
    return safety_path


# --------------------------------------------------------------------------
# Exports
# --------------------------------------------------------------------------

def export_notes_csv(conn_or_path, path) -> str:
    """Export all student notes (+ bookmarks, if the table exists) to CSV."""
    conn, close = _get_conn(conn_or_path)
    try:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["kind", "id", "target_kind", "target_id", "body",
                        "created_at", "updated_at"])
            if _table_exists(conn, "notes"):
                for r in conn.execute(
                        "SELECT id, target_kind, target_id, body, created_at, updated_at "
                        "FROM notes ORDER BY id"):
                    w.writerow(["note", r[0], r[1], r[2], r[3], r[4], r[5]])
            if _table_exists(conn, "bookmarks"):
                for r in conn.execute(
                        "SELECT id, target_kind, target_id, created_at FROM bookmarks ORDER BY id"):
                    w.writerow(["bookmark", r[0], r[1], r[2], "", r[3], ""])
        return path
    finally:
        if close:
            conn.close()


def export_progress_markdown(conn_or_path, path) -> str:
    """Export a human-readable progress summary (tolerates missing tables)."""
    conn, close = _get_conn(conn_or_path)
    try:
        lines = ["# CAPT Tax — Progress Export",
                 f"_Exported {_utcnow()}_", ""]
        has = lambda t: _table_exists(conn, t)

        # attempts / mastery tables may be owned by another team; probe gently
        attempts_tbl = next((t for t in ("attempts", "practice_attempts", "question_attempts")
                             if has(t)), None)
        mastery_tbl = next((t for t in ("mastery", "topic_mastery") if has(t)), None)

        if has("chapters"):
            lines.append("## Chapters")
            for cid, num, title in conn.execute(
                    "SELECT id, number, title FROM chapters ORDER BY number"):
                lines.append(f"### Chapter {num}: {title}")
                if attempts_tbl:
                    try:
                        n_att, n_ok = conn.execute(
                            f"SELECT COUNT(*), COALESCE(SUM(CASE WHEN "
                            f"{_correct_col(conn, attempts_tbl)} THEN 1 ELSE 0 END),0) "
                            f"FROM {attempts_tbl} WHERE chapter_id = ?", (cid,)).fetchone()
                        lines.append(f"- Attempts: {n_att} ({n_ok} correct)")
                    except Exception:
                        lines.append("- Attempts: (table shape not recognised)")
                if has("topics"):
                    for tid, tname in conn.execute(
                            "SELECT id, name FROM topics WHERE chapter_id = ? ORDER BY sort_order",
                            (cid,)):
                        mark = ""
                        if mastery_tbl:
                            try:
                                row = conn.execute(
                                    f"SELECT * FROM {mastery_tbl} WHERE topic_id = ?",
                                    (tid,)).fetchone()
                                if row:
                                    mark = f" — mastery snapshot: {dict(zip([d[0] for d in conn.execute(f'SELECT * FROM {mastery_tbl} LIMIT 1').description], row))}"
                            except Exception:
                                pass
                        lines.append(f"  - {tname}{mark}")
                lines.append("")
        else:
            lines.append("_No chapters table yet — nothing to summarise._")

        if has("notes"):
            n = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
            lines += ["", f"## Notes: {n}"]
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        return path
    finally:
        if close:
            conn.close()


def _correct_col(conn, table):
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    for cand in ("is_correct", "correct", "score"):
        if cand in cols:
            return cand
    return "1=0"


# --------------------------------------------------------------------------
# Auto-backup
# --------------------------------------------------------------------------

def _get_setting(conn, key, default=None):
    if not _table_exists(conn, "settings"):
        return default
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else default


def _set_setting(conn, key, value):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                 (key, str(value)))
    conn.commit()


def maybe_auto_backup(conn_or_path, dest_dir=None):
    """Create a backup if 'auto_backup_days' elapsed since the last one.

    Returns the new zip path, or None when no backup was due / disabled.
    Honors settings keys: 'auto_backup_days' (0/empty = disabled),
    'backup_dir' (fallback dest_dir).
    """
    conn, close = _get_conn(conn_or_path)
    try:
        try:
            days = int(_get_setting(conn, "auto_backup_days", "0") or 0)
        except (TypeError, ValueError):
            days = 0
        if days <= 0:
            return None
        dest = dest_dir or _get_setting(conn, "backup_dir") or "."
        last = None
        if _table_exists(conn, "backups"):
            row = conn.execute(
                "SELECT created_at FROM backups ORDER BY id DESC LIMIT 1").fetchone()
            if row:
                last = row[0]
        if last:
            try:
                last_dt = datetime.datetime.fromisoformat(last)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=datetime.timezone.utc)
                due = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
                if last_dt > due:
                    return None
            except Exception:
                pass
        os.makedirs(dest, exist_ok=True)
        return backup_db(conn, dest, note=f"auto: every {days} day(s)")
    finally:
        if close:
            conn.close()


__all__ = [
    "backup_db", "list_backups", "restore_backup", "RestoreGuardError",
    "export_notes_csv", "export_progress_markdown", "maybe_auto_backup",
    "db_file_of_conn", "BACKUP_PREFIX",
]
