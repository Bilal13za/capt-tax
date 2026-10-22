"""Answer approaches — guided exam workflows. Pure logic, streamlit-free.

Each chapter gets one deterministic step checklist for attempting exam
questions. The steps are *structural exam technique* (read the requirement,
classify, apply the chapter's own branches in order, present in the
computation format) derived from the chapter's real topic structure — the
book's own "completeness criteria" for heads of income and the slide titles
actually in the chapter. No step invents tax law; steps that name a section
use the section references printed in the book.

Seeded workflows are labelled "suggested workflow — verify against the book"
and are fully student-editable; every edit is logged in ``approach_edits``.
Checklist progress is tracked per walkthrough session
(``approach_sessions`` / ``approach_checks``).
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

INTRO_TMPL = (
    "Suggested workflow for {title} questions. This is exam technique, not "
    "tax law — verify every step against the book before relying on it."
)

_REQ_FIRST = (
    "Read the requirement first; underline the verb (compute, discuss, "
    "distinguish, state) and the marks. The verb decides the answer's shape: "
    "'discuss' wants the conclusion *plus* the basis or reason, not the "
    "conclusion alone (examiner: Autumn 2023)."
)
_REQ_LAST = (
    "Re-read the requirement and cut anything it did not ask for. Examiners "
    "repeatedly penalise irrelevant material — e.g. debating residence when "
    "the question already states the persons are resident (Autumn 2022)."
)


def _s(title: str, detail: str, link=None):
    """Step tuple: (title, detail, (link_kind, match_substring) | None)."""
    return (title, detail, link)


# Hand-authored workflows, keyed by chapter id. Link hints are
# (link_kind, title-substring) resolved against real DB rows at seed time;
# a hint that matches nothing simply leaves the step unlinked.
SEED_WORKFLOWS = {
    "ch01": [
        _s("Read the requirement; note the verb and the marks",
           _REQ_FIRST),
        _s("Map the question to its chapter",
           "Use the syllabus analysis in this chapter (income-tax laws vs "
           "administration vs chargeability blocks) to decide which chapter's "
           "rules the question draws on before you start writing."),
        _s("Secure the sure marks first",
           "Attempt questions in an order that banks certain marks early; "
           "leave the heavy computation for when you are warmed up."),
        _s("Watch the paper's own composition signals",
           "The book's paper-composition charts show the MCQ / computation / "
           "scenario / theory mix shifting every attempt — do not assume this "
           "paper looks like the last one."),
        _s("Re-read the requirement before you stop", _REQ_LAST),
    ],
    "ch02": [
        _s("Read the requirement; note the verb and the marks", _REQ_FIRST),
        _s("Name the exact term being tested",
           "Person, income, tax year, head of income — pin down which defined "
           "term the question turns on before applying anything else.",
           ("definition", None)),
        _s("State the definition precisely",
           "Write the definition in full. Note whether it is exclusive "
           "('means') or inclusive ('includes') — the examiner tests that "
           "distinction.", ("definition", None)),
        _s("Apply the charging logic in order",
           "Is there a person? Is there income? Does the charging section "
           "catch it? Work the three questions in sequence; a 'no' anywhere "
           "stops the charge."),
        _s("Classify into the correct head of income",
           "Run the book's completeness criteria: amount chargeable, basis of "
           "chargeability, allowable deductions, treatment of losses, "
           "exemptions, Pakistan-source vs foreign-source."),
        _s("Split the confusable pairs",
           "Permanent establishment is not residential status; a wealth "
           "statement is not a wealth reconciliation statement (examiner "
           "comments, Spring 2025 / Autumn 2024). State the difference "
           "explicitly.", ("definition", None)),
        _s("Re-read the requirement before you stop", _REQ_LAST),
    ],
    "ch03": [
        _s("Read the requirement; note the verb and the marks", _REQ_FIRST),
        _s("Confirm the tax year; list every receipt and benefit",
           "Any salary received by an employee in a tax year, other than "
           "exempt salary, is chargeable under the head 'Salary' [Sec. 12(1)]. "
           "List everything first — omissions are the classic salary error.",
           ("definition", "Salary")),
        _s("Classify each item",
           "Sort every receipt into: basic salary, allowance, perquisite, "
           "special amount (e.g. employee share scheme [Sec. 14]), or "
           "retirement benefit. The tax treatment follows the classification."),
        _s("Tax allowances and perquisites by their own rules",
           "Work the 'Taxation of Allowances and Perquisites' branch item by "
           "item — concessional loans, tax-on-tax and golden-handshake style "
           "items each have their own measure."),
        _s("Apply head-specific exemptions",
           "Run the 'Other Exemptions' branch before you compute anything; "
           "exempt salary never enters the computation."),
        _s("Deduct allowable deductions [Sec. 12(4)]",
           "Only the deductions this head allows. Do not import deductions "
           "from other heads."),
        _s("Check Pakistan-source vs foreign-source; withholding [Sec. 149]",
           "Apply the source rules, and touch withholding tax only if the "
           "question asks for it."),
        _s("Present in the salary computation format and cross-check",
           "Total the chargeable amounts, subtract the allowable deductions, "
           "and re-add the components to catch arithmetic slips."),
        _s("Re-read the requirement before you stop", _REQ_LAST),
    ],
    "ch04": [
        _s("Read the requirement; note the verb and the marks", _REQ_FIRST),
        _s("Establish the chargeable amount [Sec. 15]",
           "Confirm the property produces an amount chargeable under the head "
           "'Income from Property' and arrive at the gross figure using the "
           "section's own measure.", ("rule", "15")),
        _s("Deduct only this head's allowable deductions",
           "Work the deductions branch that belongs to this head; test every "
           "expense against it."),
        _s("Apply the head's exemptions",
           "Exempt property income is removed before computation, not after."),
        _s("Check Pakistan-source vs foreign-source",
           "Apply the source criteria for this head."),
        _s("Present the property computation and cross-check",
           "Gross less allowable deductions; re-add to verify."),
        _s("Re-read the requirement before you stop", _REQ_LAST),
    ],
    "ch05": [
        _s("Read the requirement; note the verb and the marks", _REQ_FIRST),
        _s("Is it an asset for tax purposes?",
           "Identify the asset first. Classification errors are punished: a "
           "gray parrot is a personal asset, an executive table at a "
           "residence is not a capital asset (examiner: Autumn 2024, Spring "
           "2024).", ("definition", "Asset")),
        _s("Pin down acquisition [Sec. 75]",
           "When and how was the asset acquired? The acquisition facts drive "
           "everything downstream.", ("rule", "75")),
        _s("Determine cost [Sec. 76]; check the banking-channel rule [Sec. 75A]",
           "Build cost strictly under section 76, and verify any purchase "
           "meets the banking-channel requirement of section 75A where it "
           "applies.", ("rule", "76")),
        _s("Has a disposal occurred [Sec. 75]?",
           "A gift of a coin collection *is* a disposal — overlooking it "
           "loses the whole capital-gain computation (examiner: Spring "
           "2024). Name the disposal event explicitly.", ("rule", "75")),
        _s("Measure consideration received [Sec. 77]",
           "Quantify what was received on disposal under section 77.",
           ("rule", "77")),
        _s("Re-read the requirement before you stop", _REQ_LAST),
    ],
    "ch06": [
        _s("Read the requirement; note the verb and the marks", _REQ_FIRST),
        _s("Is it a capital asset [Sec. 37(5)]?",
           "Exclude non-capital assets first — the examiner's executive-table "
           "trap (Spring 2024) lives or dies here.", ("definition", "Capital Asset")),
        _s("Has a disposal occurred?",
           "No disposal, no capital gain. Name the disposal event."),
        _s("Compute consideration vs cost → gain or loss [Sec. 37(1)]",
           "The core arithmetic of the chapter; show every working.",
           ("rule", "37")),
        _s("Apply the special regimes where triggered",
           "Immovable property [Sec. 37(1A)] and sale of securities [Sec. 37A] "
           "have their own measures — check whether the facts trigger them "
           "before using the general rule.", ("rule", "37A")),
        _s("Set off and carry forward capital losses correctly",
           "Use the chapter's set-off and carry-forward branch; capital "
           "losses have their own ordering."),
        _s("Withholding implications only if asked",
           "Note them separately; they do not change the gain computation."),
        _s("Re-read the requirement before you stop", _REQ_LAST),
    ],
    "ch07": [
        _s("Read the requirement; note the verb and the marks", _REQ_FIRST),
        _s("Identify the accounting method in play",
           "Name the method the question uses before touching any figure — "
           "the method decides *when* each item is recognised."),
        _s("Apply the method consistently",
           "Run every receipt and expense through the same method; mixing "
           "methods inside one computation is the standard error."),
        _s("Adjust pre-commencement expenditure per the chapter",
           "Isolate these items and treat them under the chapter's own "
           "rules, not the general deduction rules."),
        _s("Tie each adjustment back to the requirement",
           "State which requirement each adjustment answers."),
        _s("Re-read the requirement before you stop", _REQ_LAST),
    ],
    "ch08": [
        _s("Read the requirement; note the verb and the marks", _REQ_FIRST),
        _s("Is the receipt business income [Sec. 18]?",
           "Test chargeability first; exclude anything belonging to another "
           "head before you start adding.", ("rule", "18")),
        _s("List all business receipts completely",
           "An incomplete gross is unrecoverable later — list first, compute "
           "second."),
        _s("Deduct allowable deductions; test each expense",
           "Run every expense against the deduction conditions in sections "
           "18–21; an expense that fails the conditions is added back."),
        _s("Add back disallowances explicitly",
           "Show each add-back as its own line so the examiner can follow "
           "it."),
        _s("Apply adjustments in the examined order",
           "Adjust brought-forward losses *before* deducting depreciation "
           "and amortization — reversing them was penalised (examiner: "
           "Autumn 2024)."),
        _s("Compute taxable business income in the chapter's format",
           "Present gross, deductions, add-backs and the final figure in "
           "order; re-add to cross-check."),
        _s("Re-read the requirement before you stop", _REQ_LAST),
    ],
    "ch09": [
        _s("Read the requirement; note the verb and the marks", _REQ_FIRST),
        _s("Identify each receipt and test this head",
           "Dividends, profit on debt, royalty and similar receipts each have "
           "their own treatment — first confirm the receipt actually falls "
           "under this head and not another."),
        _s("Apply each receipt type's own tax treatment",
           "Do not blend treatments across receipt types; work them one by "
           "one."),
        _s("Separate out anything belonging to other heads",
           "Mis-head classification is a repeated examiner complaint "
           "(Autumn 2024)."),
        _s("Compute and present head-wise",
           "Show each receipt's treatment, then the head total."),
        _s("Re-read the requirement before you stop", _REQ_LAST),
    ],
    "ch10": [
        _s("Read the requirement; note the verb and the marks", _REQ_FIRST),
        _s("Locate the exact schedule, part and clause",
           "Second Schedule Parts I–IV do different jobs (exemption from "
           "total income / reduction in rate / reduction in liability / "
           "exemption from specific provisions). Cite the exact location."),
        _s("Verify every condition of the exemption or concession",
           "Exemptions are strictly construed — list each condition and tick "
           "it against the facts."),
        _s("Keep the three concessions distinct",
           "An exemption from total income, a rate reduction and a liability "
           "reduction hit the computation at different stages; mixing them "
           "up breaks the answer."),
        _s("Apply tax credits after computing tax liability",
           "Credits reduce the tax, not the income — apply them at the "
           "liability stage."),
        _s("Re-read the requirement before you stop", _REQ_LAST),
    ],
    "ch11": [
        _s("Read the requirement; note the verb and the marks", _REQ_FIRST),
        _s("Identify each loss and its head",
           "A loss can only travel the routes its head allows — label every "
           "loss before moving it."),
        _s("Set off within the year in the correct order",
           "Apply the intra-year set-off sequence from the chapter; order "
           "matters."),
        _s("Carry forward only what the rules permit",
           "State the maximum carry-forward period for each loss (examiner: "
           "Spring 2023 tested exactly this) and carry only the balance."),
        _s("Respect the ordering trap",
           "Brought-forward losses are adjusted *before* depreciation and "
           "amortization are deducted (examiner: Autumn 2024)."),
        _s("Re-read the requirement before you stop", _REQ_LAST),
    ],
    "ch12": [
        _s("Read the requirement; note the verb and the marks", _REQ_FIRST),
        _s("List every income element; classify into heads",
           "This is where most marks are lost — in Spring 2025 Q.4(a) many "
           "could not correctly compute total and taxable income from a "
           "given set of income elements. Write the head against each "
           "element before computing anything."),
        _s("Compute each head with its own chapter workflow",
           "Salary, property, business, capital gains, other sources — each "
           "head keeps its own computation logic."),
        _s("Aggregate to total income, then taxable income",
           "Combine the heads, then apply losses and deductible allowances "
           "in the right order."),
        _s("Apply the rate schedule for the tax year",
           "Compute gross tax on taxable income using the chapter's rate "
           "structure."),
        _s("Subtract tax credits; add any applicable surcharge",
           "Credits reduce liability; surcharges increase it — keep them "
           "separate and labelled."),
        _s("Deduct withholding and advance tax → net payable / refundable",
           "The final reconciliation: gross tax less credits plus surcharge "
           "less tax already paid."),
        _s("Present in the book's computation format; cross-check",
           "Follow the chapter's master computation format line by line; "
           "re-add every column."),
        _s("Re-read the requirement before you stop", _REQ_LAST),
    ],
    "ch13": [
        _s("Read the requirement; note the verb and the marks", _REQ_FIRST),
        _s("Confirm it is an AOP and identify the members",
           "The AOP is a separate taxable unit — establish membership before "
           "computing anything."),
        _s("Compute the AOP's total income",
           "Work the AOP's income like an individual's: classify into heads "
           "and compute each head."),
        _s("Apply the AOP's own tax treatment",
           "The AOP is taxed under its own provisions, not as a collection "
           "of individuals."),
        _s("Allocate shares to members per the chapter's rules",
           "Show each member's share separately with its tax treatment."),
        _s("Re-read the requirement before you stop", _REQ_LAST),
    ],
    "ch14": [
        _s("Read the requirement; note the verb and the marks", _REQ_FIRST),
        _s("Name the concept being tested",
           "This is a grab-bag chapter — write down which concept the "
           "question targets before reaching for any rule."),
        _s("Pull that concept's exact definition or rule only",
           "Apply narrowly. Do not drag in unrelated chapters' material."),
        _s("Apply it to the facts step by step",
           "Short questions still want the reasoning shown, not just the "
           "conclusion."),
        _s("Re-read the requirement before you stop", _REQ_LAST),
    ],
}

_SUGGESTED_LABEL = "Suggested workflow — verify against the book."


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _q(conn: sqlite3.Connection, sql: str, params=()):
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _book_is_demo(conn: sqlite3.Connection, chapter_id: str) -> bool:
    row = conn.execute(
        """SELECT b.is_demo FROM books b JOIN chapters c ON c.book_id = b.id
           WHERE c.id = ?""",
        (chapter_id,)).fetchone()
    return bool(row and row["is_demo"])


def _chapter_title(conn: sqlite3.Connection, chapter_id: str) -> str:
    row = conn.execute("SELECT number, title FROM chapters WHERE id = ?",
                       (chapter_id,)).fetchone()
    if not row:
        return chapter_id
    return f"Ch {row['number']}: {row['title']}"


def _resolve_link(conn: sqlite3.Connection, chapter_id: str, hint):
    """Resolve a (link_kind, title-substring) hint to (kind, ref_id|None)."""
    if not hint:
        return ("none", None)
    kind, substr = hint
    if kind == "definition":
        sql = ("SELECT id, title FROM items WHERE chapter_id=? "
               "AND kind='definition'")
        for r in _q(conn, sql, (chapter_id,)):
            if substr is None or substr.lower() in (r["title"] or "").lower():
                return ("definition", str(r["id"]))
    elif kind == "rule":
        sql = ("SELECT id, rule_code, title FROM tax_rules WHERE chapter_id=?")
        for r in _q(conn, sql, (chapter_id,)):
            hay = f"{r['rule_code'] or ''} {r['title'] or ''}"
            if substr is None or substr in hay:
                return ("rule", str(r["id"]))
    elif kind == "question":
        rows = _q(conn, "SELECT id FROM questions WHERE chapter_id=? LIMIT 1",
                  (chapter_id,))
        if rows:
            return ("question", rows[0]["id"])
    return ("none", None)


def _generic_steps(conn: sqlite3.Connection, chapter_id: str) -> list:
    """Fallback workflow for chapters without a hand-authored template."""
    steps = [
        ("Read the requirement; note the verb and the marks", _REQ_FIRST, None),
    ]
    try:
        tree = __import__("core.studymaps", fromlist=["x"]).build_chapter_map(
            conn, chapter_id)
        topics = [g["name"] for g in tree["groups"]
                  if g["kind"] == "topic"][:6]
    except Exception:
        topics = []
    if topics:
        steps.append((
            "Map the question onto the chapter's topics",
            "This chapter covers: " + "; ".join(topics)
            + ". Decide which topic each part of the requirement belongs to "
              "before you start writing.", None))
    steps += [
        ("Work each topic's own rules in order",
         "Every topic has its own chargeability, exemptions and deductions — "
         "apply them topic by topic, not all at once.", None),
        ("Present the answer in the chapter's format",
         "Follow the computation or answer structure used in the chapter; "
         "re-add every column to cross-check.", None),
        ("Re-read the requirement before you stop", _REQ_LAST, None),
    ]
    return steps


def ensure_approach(conn: sqlite3.Connection, chapter_id: str) -> int:
    """Seed the chapter's workflow if missing. Returns the approach id."""
    row = conn.execute("SELECT id FROM approaches WHERE chapter_id = ?",
                       (chapter_id,)).fetchone()
    if row:
        return row["id"]
    title_bits = _chapter_title(conn, chapter_id)
    demo = _book_is_demo(conn, chapter_id)
    raw = None if demo else SEED_WORKFLOWS.get(chapter_id)
    steps = []
    if raw is None:
        for t, d, _h in _generic_steps(conn, chapter_id):
            steps.append((t, d, ("none", None)))
    else:
        for t, d, hint in raw:
            steps.append((t, d, _resolve_link(conn, chapter_id, hint)))
    now = _utcnow()
    cur = conn.execute(
        """INSERT INTO approaches(chapter_id, title, intro, origin, updated_at)
           VALUES (?,?,?,?,?)""",
        (chapter_id, f"Answer approach — {title_bits}",
         INTRO_TMPL.format(title=title_bits),
         "seeded", now),
    )
    aid = cur.lastrowid
    for i, (t, d, (lk, lr)) in enumerate(steps, 1):
        conn.execute(
            """INSERT INTO approach_steps(approach_id, step_no, title, detail,
                                          link_kind, link_ref, sort_order)
               VALUES (?,?,?,?,?,?,?)""",
            (aid, i, t, d, lk, lr, i),
        )
    conn.commit()
    return aid


def seed_approaches(conn: sqlite3.Connection) -> dict:
    """Seed workflows for every chapter. Returns {chapter_id: approach_id}."""
    out = {}
    for r in _q(conn, "SELECT id FROM chapters ORDER BY number"):
        out[r["id"]] = ensure_approach(conn, r["id"])
    return out


def get_approach(conn: sqlite3.Connection, chapter_id: str):
    row = conn.execute("SELECT * FROM approaches WHERE chapter_id = ?",
                       (chapter_id,)).fetchone()
    return dict(row) if row else None


def get_steps(conn: sqlite3.Connection, approach_id: int) -> list:
    return _q(conn,
              "SELECT * FROM approach_steps WHERE approach_id=? "
              "ORDER BY sort_order, step_no", (approach_id,))


def _log_edit(conn, approach_id, step_id, field, old, new):
    conn.execute(
        """INSERT INTO approach_edits(approach_id, step_id, field, old_value,
                                      new_value, created_at)
           VALUES (?,?,?,?,?,?)""",
        (approach_id, step_id, field, old, new, _utcnow()))


def update_step(conn: sqlite3.Connection, approach_id: int, step_id: int,
                field: str, value: str) -> None:
    """Edit a step's title/detail; the old value is logged."""
    if field not in ("title", "detail"):
        raise ValueError("field must be 'title' or 'detail'")
    row = conn.execute("SELECT title, detail FROM approach_steps WHERE id=? "
                       "AND approach_id=?", (step_id, approach_id)).fetchone()
    if not row:
        raise ValueError("step not found")
    old = row[field]
    if old == value:
        return
    conn.execute(f"UPDATE approach_steps SET {field}=? WHERE id=?",
                 (value, step_id))
    _log_edit(conn, approach_id, step_id, field, old, value)
    conn.commit()


def add_step(conn: sqlite3.Connection, approach_id: int, title: str,
             detail: str = "", link_kind: str = "none",
             link_ref: str | None = None) -> int:
    mx = conn.execute("SELECT MAX(sort_order) m FROM approach_steps "
                      "WHERE approach_id=?", (approach_id,)).fetchone()["m"]
    nxt = (mx or 0) + 1
    cur = conn.execute(
        """INSERT INTO approach_steps(approach_id, step_no, title, detail,
                                      link_kind, link_ref, sort_order)
           VALUES (?,?,?,?,?,?,?)""",
        (approach_id, nxt, title, detail, link_kind, link_ref, nxt))
    sid = cur.lastrowid
    _log_edit(conn, approach_id, sid, "added", "", title)
    conn.commit()
    return sid


def delete_step(conn: sqlite3.Connection, approach_id: int, step_id: int) -> None:
    row = conn.execute("SELECT title FROM approach_steps WHERE id=? "
                       "AND approach_id=?", (step_id, approach_id)).fetchone()
    if not row:
        raise ValueError("step not found")
    conn.execute("DELETE FROM approach_checks WHERE step_id=?", (step_id,))
    conn.execute("DELETE FROM approach_steps WHERE id=?", (step_id,))
    _log_edit(conn, approach_id, step_id, "deleted", row["title"], "")
    conn.commit()


# ---------------------------------------------------------------------------
# Walkthrough sessions (interactive checklist state)
# ---------------------------------------------------------------------------

def start_session(conn: sqlite3.Connection, approach_id: int,
                  label: str | None = None) -> int:
    if not label:
        label = "Walkthrough " + datetime.now().strftime("%Y-%m-%d %H:%M")
    cur = conn.execute(
        """INSERT INTO approach_sessions(approach_id, label, status, created_at)
           VALUES (?,?, 'open', ?)""",
        (approach_id, label, _utcnow()))
    conn.commit()
    return cur.lastrowid


def list_sessions(conn: sqlite3.Connection, approach_id: int) -> list:
    return _q(conn,
              "SELECT * FROM approach_sessions WHERE approach_id=? "
              "ORDER BY id DESC", (approach_id,))


def set_check(conn: sqlite3.Connection, session_id: int, step_id: int,
              done: bool) -> None:
    conn.execute(
        """INSERT INTO approach_checks(session_id, step_id, done, updated_at)
           VALUES (?,?,?,?)
           ON CONFLICT(session_id, step_id) DO UPDATE SET
               done=excluded.done, updated_at=excluded.updated_at""",
        (session_id, step_id, 1 if done else 0, _utcnow()))
    conn.commit()


def session_progress(conn: sqlite3.Connection, session_id: int) -> dict:
    sess = conn.execute("SELECT * FROM approach_sessions WHERE id=?",
                        (session_id,)).fetchone()
    if not sess:
        return {"done": 0, "total": 0}
    steps = _q(conn, "SELECT id FROM approach_steps WHERE approach_id=?",
               (sess["approach_id"],))
    checks = {r["step_id"]: r["done"]
              for r in _q(conn, "SELECT step_id, done FROM approach_checks "
                                "WHERE session_id=?", (session_id,))}
    done = sum(1 for s in steps if checks.get(s["id"]))
    return {"done": done, "total": len(steps)}


def close_session(conn: sqlite3.Connection, session_id: int) -> None:
    conn.execute("UPDATE approach_sessions SET status='done' WHERE id=?",
                 (session_id,))
    conn.commit()
