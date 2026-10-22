"""Chapter maps + importance classification — pure logic, streamlit-free.

Importance tiers are computed from data that actually exists in the app's
database (this book's practice-question distribution and chapter sizes), with
the formula shown verbatim in the UI. They are study-guidance labels, NOT
ICAP's official syllabus weightage — the UI says so explicitly.

Mind-map trees are built from slide titles, slide footer topic labels,
definitions and question records. Every leaf traces back to a page number;
nothing is invented.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Importance tiers
# ---------------------------------------------------------------------------

TIERS = {
    "essential": {
        "stars": "★★★",
        "label": "Essential",
        "color": "#b03a2e",
        "blurb": "Highest practice-question weightage in the book. Master first.",
    },
    "high_yield": {
        "stars": "★★",
        "label": "High-yield",
        "color": "#ca6f1e",
        "blurb": "Heavy practice coverage. Core exam territory.",
    },
    "core": {
        "stars": "★",
        "label": "Core",
        "color": "#2471a3",
        "blurb": "Solid coverage — needed for complete preparation.",
    },
    "foundation": {
        "stars": "○",
        "label": "Foundation",
        "color": "#7f8c8d",
        "blurb": "Introductory or narrow scope. Cover after the tiers above.",
    },
}
TIER_ORDER = ["essential", "high_yield", "core", "foundation"]

# score = 0.6 * question_share + 0.4 * page_share
W_QUESTIONS = 0.6
W_PAGES = 0.4
THRESHOLDS = [("essential", 0.105), ("high_yield", 0.07), ("core", 0.03)]
# anything below the last threshold -> "foundation"

FORMULA_TEXT = (
    "score = 0.6 × (chapter questions ÷ all questions) "
    "+ 0.4 × (chapter pages ÷ all pages). "
    "Tiers: ★★★ Essential ≥ 0.105 · ★★ High-yield ≥ 0.07 · "
    "★ Core ≥ 0.03 · ○ Foundation below 0.03."
)

# Qualitative significance notes — study guidance, shown next to the tier.
# These are the author's (curated) reading of each chapter's role; the tier
# itself stays purely data-driven.
CHAPTER_NOTES = {
    "ch01": "Sets up the course map. Light practice weight — read once, move on.",
    "ch02": "Concept bedrock: person, income, heads of income. Everything later builds on this.",
    "ch03": "First major computation head. Section 12 mechanics recur in exams.",
    "ch04": "Computation head with its own deduction logic (Sections 15–15B).",
    "ch05": "Short but rule-dense (Sections 75–77, 75A). Quick marks if memorised precisely.",
    "ch06": "Computation head; holding-period and cost rules are classic exam traps.",
    "ch07": "Small chapter — accounting methods that underpin business income.",
    "ch08": "Largest chapter by pages; Sections 18–21 are the heart of business taxation.",
    "ch09": "Smaller head — dividends, profit on debt, royalty. Often tested inside bigger questions.",
    "ch10": "Exemptions, concessions and credits — high mark density per page.",
    "ch11": "Short chapter, but loss set-off and carry-forward feed directly into computation questions (Ch 12) — don't skip.",
    "ch12": "Capstone: pulls every head of income into one computation. Highest question count in the book.",
    "ch13": "AOP as a separate taxable unit — self-contained and very examinable.",
    "ch14": "Grab-bag of examinable concepts. High question count for its size.",
}

# Suggested study format per chapter: "mindmap" | "flow" | "checklist" | "flashcards".
# A suggestion, not a fact — the UI shows the reason and lets the student switch.
CHAPTER_FORMATS = {
    "ch01": ("flashcards", "Brief intro chapter — lock in the key terms with flashcards."),
    "ch02": ("mindmap", "Concept web: person → income → heads of income. Map it, then flashcard the definitions."),
    "ch03": ("flow", "Computation chapter — walk the Section 12 chargeability flow step by step."),
    "ch04": ("mindmap", "Two halves: what is chargeable, then what is deductible. Map both branches."),
    "ch05": ("checklist", "Rule-list chapter (Sections 75–77, 75A) — a checklist keeps every condition visible."),
    "ch06": ("flow", "Computation chapter — cost, holding period and exemptions form a strict sequence."),
    "ch07": ("flashcards", "Small, definition-led chapter — flashcards first."),
    "ch08": ("flow", "The biggest computation: chargeability → deductions → disallowances, in order."),
    "ch09": ("mindmap", "Classification is the skill here — map each receipt to its correct head."),
    "ch10": ("checklist", "Lists of exemptions, concessions and credits — checklist them one by one."),
    "ch11": ("flow", "Set-off and carry-forward follow strict ordering rules — learn the flow."),
    "ch12": ("flow", "The master computation flow that pulls every head together."),
    "ch13": ("flow", "AOP computation mirrors the individual flow with its own twists — follow the steps."),
    "ch14": ("mindmap", "Many small topics — one map to see them all at a glance."),
}
FORMATS = {
    "mindmap": {"icon": "🧠", "label": "Mind map"},
    "flow": {"icon": "🧮", "label": "Computation flow"},
    "checklist": {"icon": "🗂", "label": "Checklist map"},
    "flashcards": {"icon": "🃏", "label": "Flashcards first"},
}

_JUNK_TITLES = re.compile(
    r"^(compiled\s*by|in this (chapter|part)|thank you|question(s)?|agenda|contents?)\b",
    re.IGNORECASE,
)
_JUNK_LABELS = re.compile(
    r"^\(?(s\.?|sec\.?|section)\s*\d[\d\w.\-–()]*\.?\)?$"
    r"|^(x+|test|untitled|n/?a|none|compiled\s*by.*)$",
    re.IGNORECASE)


def _is_junk_label(label: str) -> bool:
    t = (label or "").strip()
    if _JUNK_LABELS.match(t):
        return True
    # variants with trailing punctuation, e.g. "(S.7B)."
    t2 = re.sub(r"[().\s]+$", "", t)
    return t2 != t and bool(_JUNK_LABELS.match(t2))


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _q(conn: sqlite3.Connection, sql: str, params=()):
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def ensure_importance_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS chapter_importance(
            chapter_id TEXT PRIMARY KEY REFERENCES chapters(id),
            tier TEXT NOT NULL,
            score REAL NOT NULL,
            question_count INT NOT NULL,
            page_count INT NOT NULL,
            rationale TEXT,
            is_override INT NOT NULL DEFAULT 0,
            updated_at TEXT
        )"""
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Chapter statistics + classification
# ---------------------------------------------------------------------------

def chapter_stats(conn: sqlite3.Connection) -> dict:
    """Per-chapter counts from real DB content. Keys are chapter ids."""
    chapters = _q(
        conn,
        "SELECT id, number, title, page_start, page_end FROM chapters ORDER BY number",
    )
    stats = {}
    for ch in chapters:
        cid = ch["id"]
        pages = (ch["page_end"] or 0) - (ch["page_start"] or 0) + 1
        pages = max(pages, 0)
        q = _q(
            conn, "SELECT COUNT(*) AS c FROM questions WHERE chapter_id=?", (cid,)
        )[0]["c"]
        d = 0
        if _table_exists(conn, "items"):
            # definitions live in the definitions JSON / items table; count via
            # items of kind definition when present, else 0
            try:
                d = _q(
                    conn,
                    "SELECT COUNT(*) AS c FROM items "
                    "WHERE chapter_id=? AND kind='definition'",
                    (cid,),
                )[0]["c"]
            except sqlite3.Error:
                d = 0
        s = 0
        if _table_exists(conn, "slides"):
            try:
                s = _q(
                    conn,
                    "SELECT COUNT(*) AS c FROM slides "
                    "WHERE page_n IN (SELECT n FROM pages WHERE chapter_id=?)",
                    (cid,),
                )[0]["c"]
            except sqlite3.Error:
                s = 0
        stats[cid] = {
            "id": cid,
            "number": ch["number"],
            "title": ch["title"],
            "page_start": ch["page_start"],
            "page_end": ch["page_end"],
            "page_count": pages,
            "question_count": q,
            "definition_count": d,
            "slide_count": s,
        }
    return stats


def _tier_for(score: float) -> str:
    for tier, cutoff in THRESHOLDS:
        if score >= cutoff:
            return tier
    return "foundation"


def classify_chapters(conn: sqlite3.Connection, force: bool = False) -> dict:
    """Compute tiers for every chapter and persist them.

    Existing student overrides (is_override=1) are never overwritten unless
    ``force`` is True. Returns {chapter_id: row-dict}.
    """
    ensure_importance_table(conn)
    stats = chapter_stats(conn)
    total_q = sum(s["question_count"] for s in stats.values()) or 1
    total_p = sum(s["page_count"] for s in stats.values()) or 1
    out = {}
    for cid, s in stats.items():
        score = W_QUESTIONS * (s["question_count"] / total_q) + W_PAGES * (
            s["page_count"] / total_p
        )
        tier = _tier_for(score)
        rationale = (
            f"{s['question_count']}/{total_q} practice questions "
            f"({s['question_count']/total_q:.0%}), "
            f"{s['page_count']}/{total_p} pages ({s['page_count']/total_p:.0%}) "
            f"→ score {score:.3f}"
        )
        existing = _q(
            conn, "SELECT * FROM chapter_importance WHERE chapter_id=?", (cid,)
        )
        if existing and existing[0]["is_override"] and not force:
            out[cid] = existing[0]
            continue
        conn.execute(
            """INSERT INTO chapter_importance(
                   chapter_id, tier, score, question_count, page_count,
                   rationale, is_override, updated_at)
               VALUES (?,?,?,?,?,?,0,?)
               ON CONFLICT(chapter_id) DO UPDATE SET
                   tier=excluded.tier, score=excluded.score,
                   question_count=excluded.question_count,
                   page_count=excluded.page_count,
                   rationale=excluded.rationale,
                   is_override=0, updated_at=excluded.updated_at""",
            (cid, tier, round(score, 4), s["question_count"], s["page_count"],
             rationale, _utcnow()),
        )
        out[cid] = {
            "chapter_id": cid, "tier": tier, "score": round(score, 4),
            "question_count": s["question_count"], "page_count": s["page_count"],
            "rationale": rationale, "is_override": 0,
        }
    conn.commit()
    return out


def get_classification(conn: sqlite3.Connection) -> dict:
    """{chapter_id: importance-row}; computes on first use."""
    ensure_importance_table(conn)
    rows = _q(conn, "SELECT * FROM chapter_importance")
    if not rows:
        return classify_chapters(conn)
    return {r["chapter_id"]: r for r in rows}


def set_tier_override(conn: sqlite3.Connection, chapter_id: str, tier: str) -> None:
    """Student manually sets a chapter's tier (recorded as an override)."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier: {tier}")
    ensure_importance_table(conn)
    get_classification(conn)  # make sure a row exists
    conn.execute(
        "UPDATE chapter_importance SET tier=?, is_override=1, updated_at=? "
        "WHERE chapter_id=?",
        (tier, _utcnow(), chapter_id),
    )
    conn.commit()


def best_format(chapter_id: str) -> tuple:
    """(format_key, reason) — curated study-format suggestion per chapter."""
    return CHAPTER_FORMATS.get(
        chapter_id,
        ("mindmap", "Default view — a topic map of the chapter."),
    )


def chapter_note(chapter_id: str) -> str:
    return CHAPTER_NOTES.get(chapter_id, "")


# ---------------------------------------------------------------------------
# Mind-map tree builder
# ---------------------------------------------------------------------------

def _clean_title(title: str) -> str:
    t = re.sub(r"\s+", " ", (title or "").strip())
    return t


def _is_junk(title: str) -> bool:
    t = title.strip()
    return not t or len(t) < 4 or bool(_JUNK_TITLES.match(t))


def build_chapter_map(conn: sqlite3.Connection, chapter_id: str) -> dict:
    """Build a chapter → groups → leaves tree from real content.

    Groups come from slide footer topic labels (in page order), then key
    definitions, then the chapter's practice questions. Every leaf carries
    its page number so the UI can jump to the source.
    """
    ch = _q(conn, "SELECT * FROM chapters WHERE id=?", (chapter_id,))
    if not ch:
        return {"chapter": {}, "groups": []}
    ch = ch[0]
    groups: dict = {}
    order: list = []

    def _group(name: str, kind: str):
        if name not in groups:
            groups[name] = {"name": name, "kind": kind, "leaves": [],
                            "min_page": 10**9}
            order.append(name)
        return groups[name]

    # 1) slides grouped by footer topic label, in page order
    slides = _q(
        conn,
        """SELECT s.title, s.topic, s.page_n FROM slides s
           JOIN pages p ON p.n = s.page_n
           WHERE p.chapter_id=? ORDER BY s.page_n, s.sort_order""",
        (chapter_id,),
    )
    for s in slides:
        title = _clean_title(s["title"])
        if _is_junk(title):
            continue
        label = (s["topic"] or "").strip() or "Chapter content"
        if _is_junk_label(label):
            label = "Chapter content"
        g = _group(label, "topic")
        if not any(l["label"] == title for l in g["leaves"]):
            g["leaves"].append({"label": title, "page": s["page_n"],
                                "kind": "slide"})
        g["min_page"] = min(g["min_page"], s["page_n"] or 10**9)

    # 2) key definitions
    if _table_exists(conn, "items"):
        try:
            defs = _q(
                conn,
                "SELECT title, body, page_start FROM items "
                "WHERE chapter_id=? AND kind='definition' "
                "ORDER BY page_start",
                (chapter_id,),
            )
        except sqlite3.Error:
            defs = []
        for drow in defs:
            term = _clean_title(drow["title"])
            if not term:
                continue
            g = _group("Key definitions", "definitions")
            g["leaves"].append({
                "label": term,
                "detail": (drow["body"] or "")[:160],
                "page": drow["page_start"],
                "kind": "definition",
            })

    # 3) practice questions
    questions = _q(
        conn,
        "SELECT id, number, statement, page_start FROM questions "
        "WHERE chapter_id=? ORDER BY CAST(number AS INT)",
        (chapter_id,),
    )
    for qrow in questions:
        stmt = qrow["statement"] or ""
        lines = [ln.strip() for ln in stmt.splitlines() if ln.strip()]
        # skip the "Question No. X" header line
        label_lines = [ln for ln in lines
                       if not re.match(r"(?i)^question\s*no\.?", ln)]
        label = _clean_title(label_lines[0] if label_lines else stmt[:80])
        if len(label) > 110:
            label = label[:107] + "…"
        g = _group(f"Practice questions ({len(questions)})", "questions")
        g["leaves"].append({
            "label": f"Q{qrow['number']}: {label}",
            "page": qrow["page_start"],
            "kind": "question",
            "ref": qrow["id"],
        })

    grouped = []
    for name in sorted(order,
                       key=lambda n: groups[n]["min_page"]):
        g = groups[name]
        if g["min_page"] == 10**9:
            g["min_page"] = None
        grouped.append(g)
    return {
        "chapter": {"id": ch["id"], "number": ch["number"],
                    "title": ch["title"], "page_start": ch["page_start"],
                    "page_end": ch["page_end"]},
        "groups": grouped,
    }


def group_importance(conn: sqlite3.Connection, chapter_id: str) -> list:
    """Rank a chapter's topic groups by slide count (best-effort importance)."""
    tree = build_chapter_map(conn, chapter_id)
    rows = []
    for g in tree["groups"]:
        if g["kind"] == "questions":
            continue
        rows.append({
            "name": g["name"],
            "kind": g["kind"],
            "leaves": len(g["leaves"]),
            "min_page": g["min_page"],
        })
    rows.sort(key=lambda r: (-r["leaves"], r["min_page"] or 0))
    total = sum(r["leaves"] for r in rows) or 1
    for r in rows:
        r["share"] = r["leaves"] / total
    return rows
