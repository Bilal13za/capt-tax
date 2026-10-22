"""Deterministic numeric question variants. No streamlit, no eval().

Contract
--------
A variant *template* is stored as a question_variants row with
label='template' and variant_json::

    {
      "params": {
        "P1": {"min": 1000, "max": 5000, "step": 100},
        ...
      },
      "formula": "P1 * 12",
      "constraints": ["P1 < P2"],          # optional, each must be truthy
      "statement_template": "An employee receives Rs {P1} per month ...",
      "answer_note": "Annual = monthly x 12"
    }

``register_template(conn, question_id, template_json)`` stores it.
``generate_variant(conn, question_id, rng_seed)`` deterministically picks
parameter values from the seed, evaluates the formula with a safe
AST-based evaluator (arithmetic + comparisons + boolean ops only —
no function calls, no attribute access, no imports), checks constraints,
computes the answer and stores a new question_variants row with
label='generated practice'. Every generated variant is labelled
"generated practice — not from textbook" in answer_json.

Statement rendering substitutes {PARAM} placeholders from params.
"""

from __future__ import annotations

import ast
import datetime as _dt
import json as _json
import operator as _op
import random as _random

GENERATED_LABEL = "generated practice"
GENERATED_NOTE = "generated practice — not from textbook"


# ---------------------------------------------------------------------------
# Safe evaluator (AST-based, arithmetic only)
# ---------------------------------------------------------------------------

_BINOPS = {
    ast.Add: _op.add,
    ast.Sub: _op.sub,
    ast.Mult: _op.mul,
    ast.Div: _op.truediv,
    ast.FloorDiv: _op.floordiv,
    ast.Mod: _op.mod,
    ast.Pow: _op.pow,
}
_UNARYOPS = {ast.UAdd: _op.pos, ast.USub: _op.neg}
_CMPOPS = {
    ast.Lt: _op.lt,
    ast.LtE: _op.le,
    ast.Gt: _op.gt,
    ast.GtE: _op.ge,
    ast.Eq: _op.eq,
    ast.NotEq: _op.ne,
}
_BOOLOPS = {ast.And: all, ast.Or: any}


class UnsafeExpression(ValueError):
    """Raised when an expression uses anything beyond safe arithmetic."""


def safe_eval(expr, params):
    """Evaluate ``expr`` using only numbers, named params and safe operators.

    Allowed: + - * / // % **, parentheses, unary +/-, comparisons
    (< <= > >= == !=), boolean and/or/not, numeric literals and names found
    in ``params``. Anything else (calls, attributes, subscripts, imports,
    comprehensions, ...) raises UnsafeExpression.
    """
    try:
        tree = ast.parse(str(expr), mode="eval")
    except SyntaxError as e:
        raise UnsafeExpression(f"syntax error: {e}")

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(
                node.value, (int, float)
            ):
                raise UnsafeExpression(
                    f"only numeric literals allowed, got {node.value!r}"
                )
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in params:
                raise UnsafeExpression(f"unknown name {node.id!r}")
            v = params[node.id]
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise UnsafeExpression(f"param {node.id!r} is not numeric")
            return v
        if isinstance(node, ast.BinOp):
            fn = _BINOPS.get(type(node.op))
            if fn is None:
                raise UnsafeExpression(
                    f"operator {type(node.op).__name__} not allowed"
                )
            return fn(_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return not _eval(node.operand)
            fn = _UNARYOPS.get(type(node.op))
            if fn is None:
                raise UnsafeExpression(
                    f"unary operator {type(node.op).__name__} not allowed"
                )
            return fn(_eval(node.operand))
        if isinstance(node, ast.Compare):
            left = _eval(node.left)
            result = True
            for op, comp in zip(node.ops, node.comparators):
                fn = _CMPOPS.get(type(op))
                if fn is None:
                    raise UnsafeExpression(
                        f"comparison {type(op).__name__} not allowed"
                    )
                right = _eval(comp)
                result = result and bool(fn(left, right))
                left = right
            return result
        if isinstance(node, ast.BoolOp):
            if not isinstance(node.op, (ast.And, ast.Or)):
                raise UnsafeExpression(
                    f"boolean operator {type(node.op).__name__} not allowed"
                )
            vals = [bool(_eval(v)) for v in node.values]
            return all(vals) if isinstance(node.op, ast.And) else any(vals)
        raise UnsafeExpression(
            f"expression element {type(node).__name__} not allowed"
        )

    return _eval(tree)


# ---------------------------------------------------------------------------
# Templates & variant generation
# ---------------------------------------------------------------------------

def _ensure_schema(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS question_variants(
            id INTEGER PRIMARY KEY, question_id TEXT, variant_json TEXT,
            answer_json TEXT, label TEXT, created_at TEXT)"""
    )


def register_template(conn, question_id, template_json):
    """Store a variant template (label='template') for a question.

    ``template_json`` is a dict (or JSON string) with keys: params, formula,
    constraints (optional), statement_template (optional), answer_note.
    Returns the new row id.
    """
    _ensure_schema(conn)
    if isinstance(template_json, dict):
        template_json = _json.dumps(template_json)
    # Validate eagerly: params spec + formula must parse safely.
    spec = _json.loads(template_json)
    _validate_template(spec)
    cur = conn.execute(
        """INSERT INTO question_variants(question_id, variant_json,
                                          answer_json, label, created_at)
           VALUES (?,?,?,?,?)""",
        (
            question_id,
            template_json,
            _json.dumps({"note": "variant template (not a practice variant)"}),
            "template",
            _dt.datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return cur.lastrowid


def _validate_template(spec):
    if not isinstance(spec, dict):
        raise ValueError("template must be a JSON object")
    params = spec.get("params")
    if not isinstance(params, dict) or not params:
        raise ValueError("template.params must be a non-empty object")
    for name, pspec in params.items():
        if not isinstance(pspec, dict):
            raise ValueError(f"param {name!r} spec must be an object")
        for key in ("min", "max", "step"):
            if key not in pspec:
                raise ValueError(f"param {name!r} missing {key!r}")
        lo, hi, step = pspec["min"], pspec["max"], pspec["step"]
        if not all(isinstance(v, (int, float)) for v in (lo, hi, step)):
            raise ValueError(f"param {name!r} min/max/step must be numeric")
        if hi < lo or step <= 0:
            raise ValueError(f"param {name!r} has invalid range/step")
    formula = spec.get("formula")
    if not isinstance(formula, str) or not formula.strip():
        raise ValueError("template.formula must be a non-empty string")
    # Dry-run the evaluator with dummy params to catch unsafe expressions now.
    dummy = {name: 1.0 for name in params}
    try:
        safe_eval(formula, dummy)
    except UnsafeExpression as e:
        raise ValueError(f"template.formula rejected: {e}")
    for c in spec.get("constraints", []) or []:
        try:
            safe_eval(c, dummy)
        except UnsafeExpression as e:
            raise ValueError(f"template constraint {c!r} rejected: {e}")


def get_template(conn, question_id):
    """Return the latest template dict for a question, or None."""
    _ensure_schema(conn)
    row = conn.execute(
        """SELECT variant_json FROM question_variants
           WHERE question_id = ? AND label = 'template'
           ORDER BY id DESC LIMIT 1""",
        (question_id,),
    ).fetchone()
    if not row:
        return None
    return _json.loads(row["variant_json"])


def _pick_params(spec, rng):
    values = {}
    for name, pspec in spec["params"].items():
        lo, hi, step = pspec["min"], pspec["max"], pspec["step"]
        steps = int(round((hi - lo) / step))
        values[name] = lo + step * rng.randint(0, max(steps, 0))
    return values


def generate_variant(conn, question_id, rng_seed):
    """Deterministically generate a practice variant for a question.

    Same (question_id, rng_seed) always yields the same variant. Raises
    ValueError if no template is registered or constraints cannot be met.
    Returns {"variant_id", "params", "statement", "answer", "answer_note"}.
    """
    _ensure_schema(conn)
    spec = get_template(conn, question_id)
    if spec is None:
        raise ValueError(f"no variant template registered for {question_id!r}")

    base = _random.Random(f"{question_id}:{rng_seed}")
    params = None
    for attempt in range(200):
        rng = _random.Random(f"{question_id}:{rng_seed}:{attempt}")
        candidate = _pick_params(spec, rng)
        ok = True
        for c in spec.get("constraints", []) or []:
            try:
                if not safe_eval(c, candidate):
                    ok = False
                    break
            except UnsafeExpression:
                ok = False
                break
        if ok:
            params = candidate
            break
    if params is None:
        raise ValueError("could not satisfy template constraints after 200 tries")

    answer = safe_eval(spec["formula"], params)

    statement_template = spec.get("statement_template") or ""
    try:
        statement = statement_template.format(**{k: _fmt_num(v) for k, v in params.items()})
    except (KeyError, ValueError):
        statement = statement_template

    answer_json = {
        "answer": answer,
        "params": params,
        "formula": spec["formula"],
        "note": GENERATED_NOTE,
    }
    cur = conn.execute(
        """INSERT INTO question_variants(question_id, variant_json,
                                          answer_json, label, created_at)
           VALUES (?,?,?,?,?)""",
        (
            question_id,
            _json.dumps({"params": params, "statement": statement}),
            _json.dumps(answer_json),
            GENERATED_LABEL,
            _dt.datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    return {
        "variant_id": cur.lastrowid,
        "params": params,
        "statement": statement,
        "answer": answer,
        "answer_note": GENERATED_NOTE,
    }


def _fmt_num(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


def list_generated(conn, question_id):
    """Return generated-practice variants for a question (newest last)."""
    _ensure_schema(conn)
    rows = conn.execute(
        """SELECT * FROM question_variants
           WHERE question_id = ? AND label = ?
           ORDER BY id""",
        (question_id, GENERATED_LABEL),
    ).fetchall()
    return [dict(r) for r in rows]
