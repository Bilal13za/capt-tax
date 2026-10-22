"""Tests for demo-stuck detection and one-click repair.

Regression test: a stale/demo app.db must never silently hide the real
textbook pack. When detected, is_demo_stuck() is True and
repair_reload_real_pack() removes the database so the next startup loads
the real pack.
"""

from pathlib import Path

from core.content_pack import (
    is_demo_stuck,
    load_pack,
    repair_reload_real_pack,
)
from core.db import get_conn, init_db

ROOT = Path(__file__).resolve().parent.parent
REAL_PACK = ROOT / "data" / "content_pack.json"
SAMPLE_PACK = ROOT / "data" / "sample_pack.json"


def _demo_db(tmp_path):
    db_path = tmp_path / "app.db"
    c = get_conn(db_path)
    init_db(c)
    load_pack(c, SAMPLE_PACK, is_demo=True)
    c.close()
    return db_path


def test_demo_stuck_detected(tmp_path):
    db_path = _demo_db(tmp_path)
    c = get_conn(db_path)
    assert is_demo_stuck(c, REAL_PACK) is True
    c.close()


def test_not_stuck_when_real_pack_missing(tmp_path):
    db_path = _demo_db(tmp_path)
    c = get_conn(db_path)
    assert is_demo_stuck(c, tmp_path / "no-such-pack.json") is False
    c.close()


def test_not_stuck_on_real_content(tmp_path):
    db_path = tmp_path / "app.db"
    c = get_conn(db_path)
    init_db(c)
    load_pack(c, REAL_PACK, is_demo=False)
    assert is_demo_stuck(c, REAL_PACK) is False
    c.close()


def test_not_stuck_on_empty_db(tmp_path):
    db_path = tmp_path / "app.db"
    c = get_conn(db_path)
    init_db(c)
    assert is_demo_stuck(c, REAL_PACK) is False
    c.close()


def test_repair_deletes_db_files(tmp_path):
    db_path = _demo_db(tmp_path)
    (tmp_path / "app.db-wal").write_text("x")
    c = get_conn(db_path)
    c.close()
    repair_reload_real_pack(db_path)
    assert not db_path.exists()
    assert not (tmp_path / "app.db-wal").exists()


def test_repair_then_fresh_startup_loads_real_pack(tmp_path):
    """End-to-end: demo db -> repair -> fresh open loads the real textbook."""
    db_path = _demo_db(tmp_path)
    c = get_conn(db_path)
    assert is_demo_stuck(c, REAL_PACK) is True
    c.close()
    repair_reload_real_pack(db_path)
    # simulate app startup on the now-missing database
    c2 = get_conn(db_path)
    init_db(c2)
    assert c2.execute("SELECT COUNT(*) AS c FROM books").fetchone()["c"] == 0
    load_pack(c2, REAL_PACK, is_demo=False)
    n_ch = c2.execute("SELECT COUNT(*) AS c FROM chapters").fetchone()["c"]
    assert n_ch == 14
    assert is_demo_stuck(c2, REAL_PACK) is False
    c2.close()
