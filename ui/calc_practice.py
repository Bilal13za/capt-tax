"""Calculation Practice: worked examples in Guided / Complete-it / Solve modes.

Pure helper (importable without streamlit):
    verify_arithmetic_steps(solution_text) -> list of dicts
        {"step": str, "check": "ok"|"mismatch"|"unparsed", "detail": str}
"""

import re as _re

try:
    import streamlit as st
except Exception:  # pragma: no cover - streamlit absent in tests
    st = None

try:
    from core import uihelpers as _uh
except Exception:  # pragma: no cover
    _uh = None


def _demo_banner(conn):
    if _uh is not None and hasattr(_uh, "demo_banner"):
        try:
            _uh.demo_banner(conn)
            return
        except Exception:
            pass
    if st is not None:
        st.warning("DEMO content — synthetic sample data, not from the textbook.")


_NUM = r"\(?-?[\d,]+(?:\.\d+)?\)?"
_OP = r"(?:x|×|\*|\+|-|/|÷)"
_ARITH_RE = _re.compile(
    rf"(?P<a>{_NUM})\s*(?P<op>{_OP})\s*(?P<b>{_NUM})\s*=\s*(?P<c>{_NUM})"
)


def _to_float(tok):
    tok = tok.strip().strip("()")
    neg = tok.startswith("-")
    tok = tok.lstrip("-").replace(",", "")
    v = float(tok)
    return -v if neg else v


def verify_arithmetic_steps(solution_text):
    """Check 'a op b = c' numeric lines in solution steps with real arithmetic.

    Returns a list of {"step", "check", "detail"}. "mismatch" steps are
    flagged as 'check this step' — never silently marked correct.
    """
    results = []
    for line in str(solution_text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        m = _ARITH_RE.search(line)
        if not m:
            results.append({"step": line, "check": "unparsed", "detail": ""})
            continue
        try:
            a = _to_float(m.group("a"))
            b = _to_float(m.group("b"))
            c = _to_float(m.group("c"))
            op = m.group("op")
            calc = {
                "x": a * b, "×": a * b, "*": a * b,
                "+": a + b, "-": a - b, "/": a / b if b != 0 else None,
                "÷": a / b if b != 0 else None,
            }[op]
        except Exception as e:
            results.append({"step": line, "check": "unparsed",
                            "detail": f"could not parse numbers: {e}"})
            continue
        if calc is None:
            results.append({"step": line, "check": "mismatch",
                            "detail": "division by zero — check this step"})
        elif abs(calc - c) <= max(0.01, abs(calc) * 1e-9):
            results.append({"step": line, "check": "ok",
                            "detail": f"verified: {a} {op} {b} = {calc}"})
        else:
            results.append({"step": line, "check": "mismatch",
                            "detail": f"check this step: {a} {op} {b} = {calc},"
                                      f" but the text says {c}"})
    return results


def _worked_items(conn):
    """Worked examples: items kind='example' + numerical questions w/ solutions."""
    out = []
    for r in conn.execute(
        "SELECT id, title, body, source_ref, page_start, page_end, origin,"
        " status FROM items WHERE kind='example' ORDER BY id"
    ).fetchall():
        out.append({"key": f"item:{r['id']}", "title": r["title"] or "Worked example",
                    "prompt": r["body"], "solution": r["body"],
                    "source": (r["source_ref"], r["page_start"], r["page_end"]),
                    "origin": r["origin"], "status": r["status"]})
    for r in conn.execute(
        "SELECT id, number, statement, solution, page_start, page_end, origin"
        " FROM questions WHERE qtype='numerical' AND has_solution=1 ORDER BY id"
    ).fetchall():
        out.append({"key": f"q:{r['id']}", "title": f"Q{r['number'] or ''} (numerical)",
                    "prompt": r["statement"], "solution": r["solution"],
                    "source": (None, r["page_start"], r["page_end"]),
                    "origin": r["origin"], "status": "verified"})
    return out


def _render_guided(item, key):
    steps = [s for s in str(item["solution"]).splitlines() if s.strip()]
    n_key = f"{key}_nsteps"
    shown = st.session_state.get(n_key, 1)
    st.write(f"**{item['title']}**")
    st.write(item["prompt"])
    for s in steps[:shown]:
        st.markdown(f"> {s}")
    checks = verify_arithmetic_steps("\n".join(steps[:shown]))
    for c in checks:
        if c["check"] == "mismatch":
            st.warning(f"⚠️ {c['detail']}")
    col1, col2 = st.columns(2)
    with col1:
        if shown < len(steps) and st.button("Next step", key=f"{key}_next"):
            st.session_state[n_key] = shown + 1
            st.rerun()
    with col2:
        if shown >= len(steps):
            st.success("All steps revealed.")


def _render_complete_it(item, key):
    steps = [s for s in str(item["solution"]).splitlines() if s.strip()]
    hide_idx = {i for i, s in enumerate(steps) if "[hide]" in s}
    if not hide_idx:
        hide_idx = {i for i in range(len(steps)) if i % 3 == 2}  # every 3rd step
    st.write(f"**{item['title']}**")
    st.write(item["prompt"])
    for i, s in enumerate(steps):
        if i in hide_idx:
            st.text_input(f"Step {i + 1} — fill in", key=f"{key}_fill_{i}",
                          placeholder="Type this step, then compare below")
        else:
            st.markdown(f"> {s}")
    if st.button("Compare with expected", key=f"{key}_cmp"):
        for i in sorted(hide_idx):
            expected = steps[i].replace("[hide]", "").strip()
            got = st.session_state.get(f"{key}_fill_{i}", "")
            st.markdown(f"**Step {i + 1} expected:** {expected}")
            st.caption("Compare — not marked. Your text is not scored.")
            checks = verify_arithmetic_steps(expected)
            for c in checks:
                if c["check"] == "mismatch":
                    st.warning(f"⚠️ {c['detail']}")
            if not got.strip():
                st.caption("(you left this blank)")


def _render_solve(item, key):
    st.write(f"**{item['title']}**")
    st.write(item["prompt"])
    st.text_area("Your working", key=f"{key}_work", height=150,
                 placeholder="Solve it here first — the solution stays hidden.")
    if st.button("Submit / reveal solution", key=f"{key}_rev"):
        st.session_state[f"{key}_revealed"] = True
    if st.session_state.get(f"{key}_revealed"):
        for s in str(item["solution"]).splitlines():
            if s.strip():
                st.markdown(f"> {s}")
        for c in verify_arithmetic_steps(item["solution"]):
            if c["check"] == "mismatch":
                st.warning(f"⚠️ {c['detail']}")
        st.caption("Compare your working — not marked. Method not verified by the app.")


def render(conn):
    """Calculation Practice workspace."""
    if st is None:  # pragma: no cover
        return
    st.header("Calculation Practice")
    _demo_banner(conn)

    items = _worked_items(conn)
    if not items:
        st.info("No worked examples yet. Import a content pack or add examples.")
        return
    sel = st.selectbox("Worked example",
                       [it["key"] for it in items],
                       format_func=lambda k: next(i["title"] for i in items
                                                  if i["key"] == k),
                       key="calc_sel")
    item = next(i for i in items if i["key"] == sel)
    ref, ps, pe = item["source"]
    st.caption(f"Source: {ref or ''} p. {ps}" + (f"–{pe}" if pe else "")
               + f" · origin: {item['origin']}")
    if item.get("status") == "auto_detected_unverified":
        st.warning("Unverified content — check against the source page.")

    mode = st.radio("Mode", ["Guided", "Complete-it", "Solve independently"],
                    horizontal=True, key="calc_mode")
    if mode == "Guided":
        _render_guided(item, sel)
    elif mode == "Complete-it":
        _render_complete_it(item, sel)
    else:
        _render_solve(item, sel)
