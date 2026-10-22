"""Tests for mind-map flashcards (core/mapcards.py)."""

import re

from core import mapcards as mc
from core import sr as _sr
from core import studymaps as _sm


def _page_of(source_ref):
    m = re.search(r"p\. (\d+)", source_ref or "")
    return int(m.group(1)) if m else None


def test_generate_counts_and_idempotent(conn):
    n1 = mc.generate_map_cards(conn, "ch01")
    assert n1 > 0
    n2 = mc.generate_map_cards(conn, "ch01")
    assert n2 == 0  # idempotent: no duplicates on re-run
    assert mc.map_card_count(conn, "ch01") == n1


def test_counts_match_map_tree(conn):
    mc.generate_map_cards(conn, "ch01")
    tree = _sm.build_chapter_map(conn, "ch01")
    expected_leaves = sum(len(g["leaves"]) for g in tree["groups"])
    expected_groups = sum(
        1 for g in tree["groups"]
        if not (g["kind"] == "topic" and len(g["leaves"]) <= 1))
    assert mc.map_card_count(conn, "ch01") == expected_leaves + expected_groups


def test_breadcrumb_correctness(conn):
    mc.generate_map_cards(conn, "ch01")
    rows = conn.execute(
        "SELECT question_text, answer_text FROM flashcards "
        "WHERE origin='map'").fetchall()
    assert rows
    for r in rows:
        combined = (r["question_text"] or "") + "\n" + (r["answer_text"] or "")
        assert "Ch 1" in combined
        assert "→" in combined  # breadcrumb present (front or back)


def test_every_card_links_to_real_page(conn):
    mc.generate_map_cards(conn, "ch01")
    cards = conn.execute(
        "SELECT id, chapter_id, source_ref FROM flashcards "
        "WHERE origin='map'").fetchall()
    assert cards
    for c in cards:
        pg = _page_of(c["source_ref"])
        if pg is None:
            continue
        row = conn.execute(
            "SELECT chapter_id FROM pages WHERE n=?", (pg,)).fetchone()
        assert row is not None, f"card {c['id']} refs missing page {pg}"
        assert row["chapter_id"] == c["chapter_id"]


def test_definition_cards_carry_full_body(conn):
    mc.generate_map_cards(conn, "ch01")
    cards = conn.execute(
        "SELECT question_text, answer_text, item_id FROM flashcards "
        "WHERE origin='map'").fetchall()
    def_cards = [c for c in cards if c["item_id"] is not None]
    # sample pack has definitions as items; map definition leaves link to them
    for c in def_cards:
        assert len(c["answer_text"]) > 20


def test_question_cards_point_to_bank_not_answers(conn):
    mc.generate_map_cards(conn, "ch01")
    cards = conn.execute(
        "SELECT question_text, answer_text FROM flashcards "
        "WHERE origin='map'").fetchall()
    q_cards = [c for c in cards
               if "No answer is pre-filled here" in (c["answer_text"] or "")]
    # sample pack ch01 has practice questions -> question-leaf cards exist
    assert q_cards, "expected question-pointer cards from the map"
    for c in q_cards:
        assert "Question Bank" in c["answer_text"]
        assert "p." in c["answer_text"]  # real page pointer present


def test_map_cards_reviewable_via_sr(conn):
    mc.generate_map_cards(conn, "ch01")
    due = _sr.due_cards(conn, chapter_id="ch01", deck_tag="map")
    assert len(due) == mc.map_card_count(conn, "ch01")
    card = due[0]
    state = _sr.review_card(conn, card["id"], "good")
    assert state["reps"] == 1
