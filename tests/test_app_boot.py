"""Tests for first-run pack selection in app.py.

The real textbook pack must win over the synthetic DEMO pack on a fresh
install; DEMO is only a fallback.
"""

import importlib.util
import json
from pathlib import Path

import pytest


def _load_app_module():
    path = Path(__file__).resolve().parent.parent / "app.py"
    spec = importlib.util.spec_from_file_location("capt_app", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_real_pack_preferred(monkeypatch, tmp_path):
    mod = _load_app_module()
    real = tmp_path / "content_pack.json"
    real.write_text("{}")
    sample = tmp_path / "sample_pack.json"
    sample.write_text("{}")
    monkeypatch.setattr(mod, "REAL_PACK", real)
    monkeypatch.setattr(mod, "SAMPLE_PACK", sample)
    pack, is_demo = mod._initial_pack()
    assert pack == real
    assert is_demo is False


def test_demo_fallback_when_real_missing(monkeypatch, tmp_path):
    mod = _load_app_module()
    sample = tmp_path / "sample_pack.json"
    sample.write_text("{}")
    monkeypatch.setattr(mod, "REAL_PACK", tmp_path / "nope.json")
    monkeypatch.setattr(mod, "SAMPLE_PACK", sample)
    pack, is_demo = mod._initial_pack()
    assert pack == sample
    assert is_demo is True


def test_no_pack_at_all(monkeypatch, tmp_path):
    mod = _load_app_module()
    monkeypatch.setattr(mod, "REAL_PACK", tmp_path / "nope1.json")
    monkeypatch.setattr(mod, "SAMPLE_PACK", tmp_path / "nope2.json")
    assert mod._initial_pack() == (None, False)


def test_repo_real_pack_selected():
    """The full textbook pack (data/content_pack.json) must be committed.

    This repository is private (personal study use), so it ships the real
    extracted textbook content instead of the synthetic demo pack. The app
    prefers content_pack.json automatically when present.
    """
    repo_root = Path(__file__).resolve().parent.parent
    pack = repo_root / "data" / "content_pack.json"
    assert pack.is_file(), "content_pack.json must be committed to this private repo"
    doc = json.loads(pack.read_text(encoding="utf-8"))
    assert doc.get("pack_format") == 1, "unexpected pack format"
    assert len(doc.get("chapters", [])) == 14, "pack should hold all 14 chapters"
    assert (repo_root / "data" / "sample_pack.json").exists(), (
        "sample_pack.json must ship as the fallback"
    )
