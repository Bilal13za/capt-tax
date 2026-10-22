"""Tax Rule Library UI.

render(conn): filterable list of tax rules, each rendered as an
IF / THEN / UNLESS block, with verification badges, the tax-year context
banner, editable student notes, and an "add rule" form.

Textbook rules are NEVER presented as current law — a persistent caption
says so on this screen.

Dismissal/override choice: student notes live on the tax_rules row itself
(student_notes column); rule additions use origin='student' /
verification_status='student'. Dismissed revision recommendations (a
different feature) are stored in settings key 'dismissed_recs' — see
ui/revision.py.
"""

import json

try:
    from core import uihelpers as _uihelpers
except Exception:
    _uihelpers = None

VERIFICATION_MEANING = {
    "textbook": "From the textbook as printed — not independently verified.",
    "verified": "Verified against a primary source (see source ref).",
    "student": "Added by the student — personal note, not a source.",
    "ocr_unverified": "Came from OCR — not yet checked. Verify before trusting.",
}


def _get_setting(conn, key, default=None):
    if _uihelpers is not None and hasattr(_uihelpers, "get_setting"):
        return _uihelpers.get_setting(conn, key, default)
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?",
                           (key,)).fetchone()
        return row[0] if row else default
    except Exception:
        return default


def _set_setting(conn, key, value):
    if _uihelpers is not None and hasattr(_uihelpers, "set_setting"):
        _uihelpers.set_setting(conn, key, value)
        return
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, value))
    conn.commit()


def _is_demo(conn):
    title = str(_get_setting(conn, "book_title", "") or "")
    note = str(_get_setting(conn, "tax_context_note", "") or "")
    return "DEMO" in title.upper() or "SYNTHETIC DEMO" in note.upper()


def _parse_json(value, default=None):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def _as_lines(value):
    """conditions/exceptions/exclusions JSON -> list of display lines."""
    data = _parse_json(value, [])
    if isinstance(data, dict):
        return ["%s: %s" % (k, v) for k, v in data.items()]
    if isinstance(data, list):
        return [str(x) for x in data]
    if data:
        return [str(data)]
    return []


def _rule_rows(conn, category, vstatus, chapter_id):
    sql = "SELECT * FROM tax_rules WHERE 1=1"
    params = []
    if category and category != "All":
        sql += " AND category=?"
        params.append(category)
    if vstatus and vstatus != "All":
        sql += " AND verification_status=?"
        params.append(vstatus)
    if chapter_id and chapter_id != "All":
        sql += " AND chapter_id=?"
        params.append(chapter_id)
    sql += " ORDER BY category, title"
    cur = conn.execute(sql, params)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _distinct(conn, column):
    try:
        return [r[0] for r in conn.execute(
            "SELECT DISTINCT %s FROM tax_rules WHERE %s IS NOT NULL "
            "ORDER BY %s" % (column, column, column)).fetchall()]
    except Exception:
        return []


def _chapter_options(conn):
    try:
        return [("All", "All chapters")] + [
            (r[0], "Ch %s — %s" % (r[1], r[2])) for r in conn.execute(
                "SELECT id, number, title FROM chapters ORDER BY number"
            ).fetchall()]
    except Exception:
        return [("All", "All chapters")]


def render(conn):
    import streamlit as st
    if _is_demo(conn):
        st.warning("DEMO content pack — synthetic data for development, "
                   "not real tax material.")
    st.header("Tax Rule Library")

    tax_note = _get_setting(conn, "tax_context_note", "")
    if tax_note:
        st.info("**Tax-year context:** %s" % tax_note)
    st.caption("Rules below come from the textbook for its tax year. They "
               "are study material — not current law. Always verify against "
               "the applicable statute before relying on a rule.")

    f1, f2, f3 = st.columns(3)
    categories = ["All"] + _distinct(conn, "category")
    vstatuses = ["All", "textbook", "verified", "student", "ocr_unverified"]
    ch_opts = _chapter_options(conn)
    category = f1.selectbox("Category", categories)
    vstatus = f2.selectbox("Verification", vstatuses,
                           format_func=lambda v: v if v == "All"
                           else "%s — %s" % (v, VERIFICATION_MEANING.get(v, "")))
    chapter_id = f3.selectbox("Chapter", [c[0] for c in ch_opts],
                              format_func=lambda c: dict(ch_opts).get(c, c))

    rules = _rule_rows(conn, category, vstatus, chapter_id)
    if not rules:
        st.caption("No rules match these filters.")
    for r in rules:
        badge = r.get("verification_status") or "?"
        with st.expander("**%s**  ·  %s" % (r.get("title") or r.get("rule_code"),
                                            badge)):
            st.caption("Verification: **%s** — %s" % (
                badge, VERIFICATION_MEANING.get(badge, "Unknown status.")))
            st.write("**IF** (applies when)")
            for line in _as_lines(r.get("conditions_json")) or ["—"]:
                st.write("- " + line)
            st.write("**THEN**")
            st.write(r.get("explanation") or r.get("title") or "—")
            if r.get("rate_or_threshold"):
                st.write("Rate / threshold: %s" % r["rate_or_threshold"])
            if r.get("calc_method"):
                st.write("Calculation: %s" % r["calc_method"])
            unless = _as_lines(r.get("exceptions_json")) + _as_lines(
                r.get("exclusions_json"))
            st.write("**UNLESS** (exceptions / exclusions)")
            for line in unless or ["—"]:
                st.write("- " + line)
            if r.get("evidence_required"):
                st.write("**Evidence required:** %s" % r["evidence_required"])
            meta = []
            if r.get("tax_year"):
                meta.append("Tax year: %s" % r["tax_year"])
            if r.get("taxpayer_category"):
                meta.append("Taxpayer: %s" % r["taxpayer_category"])
            if r.get("source_ref"):
                meta.append("Source: %s" % r["source_ref"])
            ps, pe = r.get("page_start"), r.get("page_end")
            if ps:
                meta.append("pp. %s%s" % (ps, "–%s" % pe if pe and pe != ps else ""))
            if meta:
                st.caption(" · ".join(meta))
            notes = st.text_area("Student notes", value=r.get("student_notes") or "",
                                 key="notes_%s" % r["id"])
            if st.button("Save notes", key="savenotes_%s" % r["id"]):
                conn.execute("UPDATE tax_rules SET student_notes=? WHERE id=?",
                             (notes, r["id"]))
                conn.commit()
                st.success("Notes saved.")

    st.subheader("Add a rule")
    st.caption("Added rules are stored with origin='student' and "
               "verification_status='student'.")
    with st.form("add_rule"):
        title = st.text_input("Title")
        category_new = st.text_input("Category")
        explanation = st.text_area("Explanation (THEN)")
        conditions = st.text_area("Conditions, one per line (IF)")
        exceptions = st.text_area("Exceptions / exclusions, one per line (UNLESS)")
        rate = st.text_input("Rate or threshold (optional)")
        chapter_new = st.selectbox("Chapter (optional)", [c[0] for c in ch_opts],
                                   format_func=lambda c: dict(ch_opts).get(c, c))
        ok = st.form_submit_button("Add rule")
    if ok:
        if not title.strip():
            st.error("Title is required.")
        else:
            conn.execute(
                "INSERT INTO tax_rules (title, category, explanation, "
                "conditions_json, exceptions_json, rate_or_threshold, "
                "verification_status, origin, chapter_id) "
                "VALUES (?, ?, ?, ?, ?, ?, 'student', 'student', ?)",
                (title.strip(), category_new.strip() or None,
                 explanation.strip() or None,
                 json.dumps([l.strip() for l in conditions.splitlines()
                             if l.strip()]),
                 json.dumps([l.strip() for l in exceptions.splitlines()
                             if l.strip()]),
                 rate.strip() or None,
                 None if chapter_new == "All" else chapter_new))
            conn.commit()
            st.success("Rule added as a student note.")
            st.rerun()
