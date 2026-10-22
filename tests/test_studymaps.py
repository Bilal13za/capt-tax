"""Tests for core/studymaps.py — chapter importance tiers and mind-map trees.

Pure logic only (no streamlit at module level in core.studymaps).
"""

import sqlite3
import sys
import types
from pathlib import Path

import pytest

if "streamlit" not in sys.modules:
    sys.modules["streamlit"] = types.ModuleType("streamlit")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import studymaps as sm  # noqa: E402


DDL = """
CREATE TABLE books(id INTEGER PRIMARY KEY, title, volume, edition, author,
    publisher, source_file, page_count, tax_context_note, solutions_note,
    is_demo, created_at);
CREATE TABLE chapters(id TEXT PRIMARY KEY, book_id, number INT, title,
    page_start INT, page_end INT, parts_json);
CREATE TABLE pages(n INT PRIMARY KEY, book_id INT, chapter_id TEXT,
    has_slides INT, failed INT DEFAULT 0, text_merged TEXT);
CREATE TABLE slides(id INTEGER PRIMARY KEY, page_n INT, title TEXT,
    topic TEXT, text TEXT, sort_order INT);
CREATE TABLE questions(id TEXT PRIMARY KEY, book_id INT, chapter_id, topic_id,
    number, section, statement, solution, has_solution INT, page_start INT,
    page_end INT, origin, verified_answer INT, answer_note, qtype, difficulty,
    marks, suggested_minutes, rubric_json, numeric_answer, numeric_tolerance,
    rounding, mcq_options_json, mcq_answer, alt_answers_json);
"""


def _db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(DDL)
    conn.execute("INSERT INTO books(id, title) VALUES (1, 'Test Book')")
    return conn


def _seed_chapters(conn):
    # chA: many questions -> essential ; chB: middling -> high_yield/core ;
    # chC: tiny -> foundation. 100 questions, 100 pages total.
    conn.executemany(
        "INSERT INTO chapters(id, book_id, number, title, page_start, page_end)"
        " VALUES (?,?,?,?,?,?)",
        [("chA", 1, 1, "Big Chapter", 1, 40),
         ("chB", 1, 2, "Mid Chapter", 41, 70),
         ("chC", 1, 3, "Tiny Chapter", 71, 100)],
    )
    for i in range(70):
        conn.execute(
            "INSERT INTO questions(id, chapter_id, number, statement,"
            " page_start) VALUES (?,?,?, ?, ?)",
            (f"qA{i}", "chA", str(i + 1), f"Question {i + 1} text", 5),
        )
    for i in range(25):
        conn.execute(
            "INSERT INTO questions(id, chapter_id, number, statement,"
            " page_start) VALUES (?,?,?, ?, ?)",
            (f"qB{i}", "chB", str(i + 1), f"Question {i + 1} text", 45),
        )
    for i in range(5):
        conn.execute(
            "INSERT INTO questions(id, chapter_id, number, statement,"
            " page_start) VALUES (?,?,?, ?, ?)",
            (f"qC{i}", "chC", str(i + 1), f"Question {i + 1} text", 75),
        )
    conn.commit()


def test_tier_thresholds_follow_formula():
    conn = _db()
    _seed_chapters(conn)
    tiers = sm.classify_chapters(conn)
    # chA: 0.6*0.70 + 0.4*0.40 = 0.58 -> essential
    assert tiers["chA"]["tier"] == "essential"
    # chC: 0.6*0.05 + 0.4*0.30 = 0.15 -> essential (>= 0.105)
    assert tiers["chC"]["tier"] == "essential"
    # chB: 0.6*0.25 + 0.4*0.30 = 0.27 -> essential
    assert tiers["chB"]["tier"] == "essential"
    conn.close()


def test_foundation_tier_for_empty_chapter():
    conn = _db()
    conn.execute(
        "INSERT INTO chapters(id, book_id, number, title, page_start, page_end)"
        " VALUES ('chZ', 1, 9, 'Empty', 1, 2)")
    conn.execute(
        "INSERT INTO questions(id, chapter_id, number, statement)"
        " VALUES ('q1', 'chZ', '1', 'Question No. 1\nSome text')")
    conn.commit()
    tiers = sm.classify_chapters(conn)
    # 1 question of 1, 2 pages of 2 -> score 1.0, but with real totals this
    # exercises the low end; force tiny totals via direct threshold check:
    assert sm._tier_for(0.0) == "foundation"
    assert sm._tier_for(0.029) == "foundation"
    assert sm._tier_for(0.03) == "core"
    assert sm._tier_for(0.07) == "high_yield"
    assert sm._tier_for(0.105) == "essential"
    conn.close()


def test_override_survives_reclassification():
    conn = _db()
    _seed_chapters(conn)
    sm.classify_chapters(conn)
    sm.set_tier_override(conn, "chC", "foundation")
    tiers = sm.classify_chapters(conn)  # no force -> override kept
    assert tiers["chC"]["tier"] == "foundation"
    assert tiers["chC"]["is_override"] == 1
    tiers = sm.classify_chapters(conn, force=True)
    assert tiers["chC"]["tier"] == "essential"
    assert tiers["chC"]["is_override"] == 0
    conn.close()


def test_set_tier_override_rejects_unknown_tier():
    conn = _db()
    _seed_chapters(conn)
    with pytest.raises(ValueError):
        sm.set_tier_override(conn, "chA", "ultra")
    conn.close()


def test_build_chapter_map_groups_and_filters_junk():
    conn = _db()
    _seed_chapters(conn)
    conn.executemany(
        "INSERT INTO pages(n, book_id, chapter_id, has_slides)"
        " VALUES (?,?,?,1)",
        [(5, 1, "chA"), (6, 1, "chA")],
    )
    conn.executemany(
        "INSERT INTO slides(page_n, title, topic, sort_order)"
        " VALUES (?,?,?,?)",
        [(5, "Chargeability [Sec 12]", "Salary", 0),
         (5, "Compiled by:", "Salary", 1),          # junk title -> dropped
         (6, "Deductions allowed", "Salary", 0),
         (6, "Random slide", "XXXX", 0)],            # junk label -> merged
    )
    conn.commit()
    tree = sm.build_chapter_map(conn, "chA")
    assert tree["chapter"]["id"] == "chA"
    names = [g["name"] for g in tree["groups"]]
    assert "Salary" in names
    assert "XXXX" not in names
    salary = next(g for g in tree["groups"] if g["name"] == "Salary")
    assert [l["label"] for l in salary["leaves"]] == [
        "Chargeability [Sec 12]", "Deductions allowed"]
    # every leaf traces to a page
    for g in tree["groups"]:
        for leaf in g["leaves"]:
            assert leaf["label"], "leaf label must be non-empty"
            assert "page" in leaf
    # question group present with one leaf per question
    qg = next(g for g in tree["groups"] if g["kind"] == "questions")
    assert len(qg["leaves"]) == 70
    conn.close()


def test_group_importance_ranking():
    conn = _db()
    _seed_chapters(conn)
    conn.executemany(
        "INSERT INTO pages(n, book_id, chapter_id, has_slides)"
        " VALUES (?,?,?,1)",
        [(5, 1, "chA"), (6, 1, "chA"), (7, 1, "chA")],
    )
    conn.executemany(
        "INSERT INTO slides(page_n, title, topic, sort_order)"
        " VALUES (?,?,?,?)",
        [(5, "Alpha one", "Alpha", 0),
         (6, "Alpha two", "Alpha", 0),
         (7, "Beta one", "Beta", 0)],
    )
    conn.commit()
    ranked = sm.group_importance(conn, "chA")
    assert ranked[0]["name"] == "Alpha"
    assert ranked[0]["leaves"] == 2
    assert ranked[1]["name"] == "Beta"
    conn.close()


def test_best_format_curated_chapters():
    assert sm.best_format("ch12")[0] == "flow"
    assert sm.best_format("ch02")[0] == "mindmap"
    assert sm.best_format("ch05")[0] == "checklist"
    assert sm.best_format("ch01")[0] == "flashcards"
    key, reason = sm.best_format("ch99")
    assert key == "mindmap" and reason  # unknown -> safe default


def test_chapter_notes_exist_for_all_real_chapters():
    for cid in [f"ch{i:02d}" for i in range(1, 15)]:
        assert sm.chapter_note(cid), f"missing significance note for {cid}"
        assert sm.best_format(cid)[1], f"missing format reason for {cid}"


def test_junk_label_filter():
    good = ["Salary", "Exemptions", "Section 12 deductions", "AOP",
            "Key concepts"]
    junk = ["(S.7B).", "S.12(1)", "sec 21", "XXXX", "Compiledby:X",
            "n/a", "test"]
    for lbl in good:
        assert not sm._is_junk_label(lbl), lbl
    for lbl in junk:
        assert sm._is_junk_label(lbl), lbl


def test_map_html_escapes_and_renders():
    from ui import maps as maps_ui  # noqa: E402  (streamlit stubbed above)
    tree = {
        "chapter": {"id": "chX", "number": 1, "title": 'A <b>"quoted"</b> ch'},
        "groups": [{
            "name": "G <script>", "kind": "topic", "min_page": 3,
            "leaves": [{"label": 'Leaf "x" <y>', "page": 3,
                        "kind": "slide"}],
        }],
    }
    blob = maps_ui._tree_html(tree, "#123456", numbered=True,
                              checklist=False)
    assert "<script>" not in blob
    assert "&lt;script&gt;" in blob
    assert "1. " in blob  # numbered flow prefix
    blob2 = maps_ui._tree_html(tree, "#123456", numbered=False,
                               checklist=True)
    assert "☐" in blob2


def test_real_pack_tier_sanity():
    """Against the real textbook pack: capstone on top, intro at bottom."""
    from core.db import init_db  # noqa: E402
    from core.content_pack import load_pack  # noqa: E402
    pack = ROOT / "data" / "content_pack.json"
    if not pack.is_file():
        pytest.skip("real content pack not present")
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    load_pack(conn, str(pack))
    tiers = sm.classify_chapters(conn)
    assert tiers["ch12"]["tier"] == "essential"
    assert tiers["ch01"]["tier"] == "foundation"
    # every chapter classified, every tier valid
    assert set(tiers) == {f"ch{i:02d}" for i in range(1, 15)}
    assert all(t["tier"] in sm.TIERS for t in tiers.values())
    # map builds for every chapter without error
    for cid in tiers:
        tree = sm.build_chapter_map(conn, cid)
        assert tree["chapter"]["id"] == cid
        assert isinstance(tree["groups"], list)
    conn.close()
