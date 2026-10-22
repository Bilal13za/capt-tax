"""Tests for core/variants.py — deterministic numeric variants. No streamlit."""

import json
import sqlite3

import pytest

from core import variants
from core.variants import UnsafeExpression, safe_eval


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    return c


TEMPLATE = {
    "params": {
        "M": {"min": 10000, "max": 20000, "step": 1000},
        "N": {"min": 1, "max": 12, "step": 1},
    },
    "formula": "M * N",
    "constraints": ["M > 5000", "N >= 1"],
    "statement_template": "Monthly allowance Rs {M} for {N} months.",
    "answer_note": "Annual = monthly x months",
}


def test_safe_eval_arithmetic():
    assert safe_eval("M * N + (M - 100) ** 2 / 4", {"M": 10000, "N": 12}) == pytest.approx(
        10000 * 12 + (10000 - 100) ** 2 / 4
    )
    assert safe_eval("not (M > 5) and M < 10 or M == 3", {"M": 3}) is True


def test_safe_eval_rejects_malicious():
    bad = [
        "__import__('os')",
        "open('f')",
        "M.attr",
        "f(1)",
        "[1, 2][0]",
        "{'a': 1}",
        "M if M else 2",
        "lambda x: x",
        "().__class__",
        "(lambda: 1)()",
    ]
    for expr in bad:
        with pytest.raises(UnsafeExpression):
            safe_eval(expr, {"M": 1})


def test_safe_eval_rejects_unknown_name():
    with pytest.raises(UnsafeExpression):
        safe_eval("Q * 2", {"M": 1})


def test_register_template_validates(conn):
    with pytest.raises(ValueError):
        variants.register_template(conn, "q1", {"params": {}, "formula": "1"})
    with pytest.raises(ValueError):
        variants.register_template(
            conn, "q1",
            {"params": {"M": {"min": 1, "max": 2, "step": 1}},
             "formula": "__import__('os')"},
        )
    vid = variants.register_template(conn, "q1", TEMPLATE)
    assert vid is not None
    tpl = variants.get_template(conn, "q1")
    assert tpl["formula"] == "M * N"


def test_generate_variant_deterministic(conn):
    variants.register_template(conn, "q1", TEMPLATE)
    a = variants.generate_variant(conn, "q1", "seed-42")
    b = variants.generate_variant(conn, "q1", "seed-42")
    assert a["params"] == b["params"]
    assert a["answer"] == b["answer"]
    c = variants.generate_variant(conn, "q1", "other-seed")
    # different seed may legitimately collide; params must still be in range
    assert 10000 <= c["params"]["M"] <= 20000
    assert c["params"]["M"] % 1000 == 0
    assert c["answer"] == pytest.approx(c["params"]["M"] * c["params"]["N"])


def test_generate_variant_constraints_enforced(conn):
    variants.register_template(conn, "q1", TEMPLATE)
    for seed in ("s1", "s2", "s3", "s4", "s5"):
        v = variants.generate_variant(conn, "q1", seed)
        assert v["params"]["M"] > 5000
        assert v["params"]["N"] >= 1


def test_generate_variant_labelled_generated(conn):
    variants.register_template(conn, "q1", TEMPLATE)
    v = variants.generate_variant(conn, "q1", "lbl")
    assert v["answer_note"] == "generated practice — not from textbook"
    rows = variants.list_generated(conn, "q1")
    assert len(rows) >= 1
    assert rows[0]["label"] == "generated practice"
    ans = json.loads(rows[0]["answer_json"])
    assert ans["note"] == "generated practice — not from textbook"


def test_generate_variant_statement_rendered(conn):
    variants.register_template(conn, "q1", TEMPLATE)
    v = variants.generate_variant(conn, "q1", "stmt")
    assert "{M}" not in v["statement"]
    assert str(int(v["params"]["M"])) in v["statement"]


def test_generate_variant_no_template_raises(conn):
    with pytest.raises(ValueError):
        variants.generate_variant(conn, "nope", "seed")
