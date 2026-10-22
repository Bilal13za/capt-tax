"""Tests for core/backup.py. No streamlit, no network."""

import csv
import os
import sqlite3
import zipfile

import pytest

from core import backup as backup_core

DDL = """
CREATE TABLE books(id INTEGER PRIMARY KEY, title TEXT, volume TEXT, edition TEXT,
  author TEXT, publisher TEXT, source_file TEXT, page_count INTEGER,
  tax_context_note TEXT, solutions_note TEXT, is_demo INTEGER, created_at TEXT);
CREATE TABLE notes(id INTEGER PRIMARY KEY, target_kind TEXT, target_id TEXT,
  body TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE settings(key TEXT PRIMARY KEY, value TEXT);
"""


@pytest.fixture()
def db_path(tmp_path):
    p = str(tmp_path / "app.db")
    c = sqlite3.connect(p)
    c.executescript(DDL)
    c.execute("INSERT INTO books (title, is_demo) VALUES ('Test Book', 0)")
    c.execute("INSERT INTO notes (target_kind, target_id, body) VALUES "
              "('chapter', 'ch1', 'remember section 12(2)')")
    c.commit()
    c.close()
    return p


def test_backup_creates_zip_and_row(db_path, tmp_path):
    dest = str(tmp_path / "backups")
    zp = backup_core.backup_db(db_path, dest, note="unit test")
    assert os.path.isfile(zp)
    assert zp.endswith(".zip")
    with zipfile.ZipFile(zp) as zf:
        assert "app.db" in zf.namelist()
    c = sqlite3.connect(db_path)
    rows = c.execute("SELECT filename, note FROM backups").fetchall()
    c.close()
    assert len(rows) == 1
    assert rows[0][0] == os.path.basename(zp)
    assert rows[0][1] == "unit test"


def test_restore_guard_refuses_only_copy(db_path, tmp_path):
    dest = str(tmp_path / "backups")
    zp = backup_core.backup_db(db_path, dest)
    with pytest.raises(backup_core.RestoreGuardError):
        backup_core.restore_backup(zp, db_path)


def test_restore_with_force_works_and_preserves_data(db_path, tmp_path):
    dest = str(tmp_path / "backups")
    backup_core.backup_db(db_path, dest, note="first")
    zp = backup_core.backup_db(db_path, dest, note="second")

    # corrupt the live db to prove the restore actually replaces it
    c = sqlite3.connect(db_path)
    c.execute("UPDATE books SET title='MUTATED'")
    c.commit()
    c.close()

    safety = backup_core.restore_backup(zp, db_path, force=True,
                                        backup_dest_dir=dest)
    assert safety and os.path.isfile(safety)  # auto safety backup first
    c = sqlite3.connect(db_path)
    title = c.execute("SELECT title FROM books").fetchone()[0]
    c.close()
    assert title == "Test Book"


def test_restore_auto_safety_backup_registered(db_path, tmp_path):
    dest = str(tmp_path / "backups")
    backup_core.backup_db(db_path, dest)
    zp = backup_core.backup_db(db_path, dest)
    backup_core.restore_backup(zp, db_path, force=True, backup_dest_dir=dest)
    zips = [f for f in os.listdir(dest) if f.endswith(".zip")]
    assert len(zips) == 3  # two manual + one auto safety copy


def test_list_backups(db_path, tmp_path):
    dest = str(tmp_path / "backups")
    assert backup_core.list_backups(db_path, dest) == []
    backup_core.backup_db(db_path, dest, note="n1")
    rows = backup_core.list_backups(db_path, dest)
    assert len(rows) == 1
    assert rows[0]["path"] and os.path.isfile(rows[0]["path"])
    assert rows[0]["note"] == "n1"


def test_export_notes_csv(db_path, tmp_path):
    out = str(tmp_path / "notes.csv")
    backup_core.export_notes_csv(db_path, out)
    assert os.path.isfile(out)
    with open(out, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert any(r["body"] == "remember section 12(2)" for r in rows)


def test_export_progress_markdown(db_path, tmp_path):
    out = str(tmp_path / "progress.md")
    backup_core.export_progress_markdown(db_path, out)
    assert os.path.isfile(out)
    text = open(out, encoding="utf-8").read()
    assert "Progress Export" in text
    # tolerates missing chapters table
    assert "No chapters table yet" in text


def test_maybe_auto_backup_disabled_by_default(db_path, tmp_path):
    assert backup_core.maybe_auto_backup(db_path, str(tmp_path / "b")) is None


def test_maybe_auto_backup_runs_when_due(db_path, tmp_path):
    dest = str(tmp_path / "b")
    c = sqlite3.connect(db_path)
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES "
              "('auto_backup_days', '30')")
    c.commit()
    c.close()
    zp = backup_core.maybe_auto_backup(db_path, dest)
    assert zp and os.path.isfile(zp)
    # second call immediately → not due
    assert backup_core.maybe_auto_backup(db_path, dest) is None


def test_db_file_of_conn(db_path):
    c = sqlite3.connect(db_path)
    try:
        assert backup_core.db_file_of_conn(c) == os.path.abspath(db_path)
    finally:
        c.close()
