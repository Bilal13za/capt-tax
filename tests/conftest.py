"""Shared pytest fixtures: temp DB with init_db + the synthetic sample pack."""

from pathlib import Path

import pytest

from core.content_pack import load_pack
from core.db import get_conn, init_db

ROOT = Path(__file__).resolve().parent.parent
SAMPLE_PACK = ROOT / "data" / "sample_pack.json"


@pytest.fixture()
def conn(tmp_path):
    """Fresh temp database, schema initialised, sample pack loaded as DEMO."""
    db_path = tmp_path / "test.db"
    c = get_conn(db_path)
    init_db(c)
    load_pack(c, SAMPLE_PACK, is_demo=True)
    yield c
    c.close()


@pytest.fixture()
def pack_path():
    return SAMPLE_PACK
