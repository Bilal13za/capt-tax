"""Transparent topic/chapter mastery scoring for the CAPT Taxation app.

MASTER FORMULA (shown verbatim in the UI — analytics + revision screens):

    score = 0.40 * recent_accuracy
          + 0.25 * flashcard_recall
          + 0.20 * calculation_success
          + 0.15 * application_success

All components are 0..100. Components with no evidence are EXCLUDED and the
remaining weights are renormalised, so a topic the student only practised
with flashcards is not punished for having no numerical attempts.

Components
----------
* recent_accuracy      — mean(correct) over the LAST 10 question attempts on
                         the topic (correct is 0/1; rows with correct NULL
                         are ignored). Weight 0.40.
* flashcard_recall     — share of the topic's flashcards whose last SM-2
                         review rating was 'good' or 'easy'
                         (sr_reviews.last_rating). Weight 0.25.
* calculation_success  — mean(correct) over attempts on topic questions with
                         qtype='numerical'. Weight 0.20.
* application_success  — mean(correct) over attempts on topic questions with
                         qtype in ('scenario', 'theory', 'long'). Weight 0.15.

Guards
------
* <3 question attempts on the topic -> final score is CAPPED at 40 and the
  reason "insufficient evidence" is added (a lucky guess must not look like
  mastery).
* No evidence at all -> score 0, band 'weak', reason "no evidence".

Bands: score < 45 -> 'weak'; 45..74 -> 'developing'; >= 75 -> 'strong'.

No streamlit here — pure logic over a sqlite3 connection.
"""

APP_QTYPES = ("scenario", "theory", "long")

RECENT_N = 10
MIN_ATTEMPTS = 3
CAP_LOW_EVIDENCE = 40

WEIGHTS = {
    "recent_accuracy": 0.40,
    "flashcard_recall": 0.25,
    "calculation_success": 0.20,
    "application_success": 0.15,
}

FORMULA_TEXT = (
    "score = 0.40 x recent_accuracy + 0.25 x flashcard_recall "
    "+ 0.20 x calculation_success + 0.15 x application_success"
)


def _q(conn, sql, params=()):
    cur = conn.execute(sql, params)
    cols = [c[0] for c in (cur.description or [])]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _table_exists(conn, name):
    rows = _q(conn, "SELECT name FROM sqlite_master WHERE type='table' AND "
                    "name=?", (name,))
    return bool(rows)


def _mean_correct(rows):
    vals = [r["correct"] for r in rows
            if r.get("correct") in (0, 1)]
    if not vals:
        return None
    return 100.0 * sum(vals) / len(vals)


def _topic_attempts(conn, topic_id):
    if not _table_exists(conn, "attempts") or not _table_exists(conn, "questions"):
        return []
    return _q(conn,
              "SELECT a.id, a.correct, a.qtype, a.created_at "
              "FROM attempts a JOIN questions q ON q.id = a.question_id "
              "WHERE q.topic_id = ? AND a.question_id IS NOT NULL "
              "ORDER BY a.created_at DESC, a.id DESC", (topic_id,))


def _topic_flashcard_recall(conn, topic_id):
    """0..100 or None when no reviewed cards exist for the topic."""
    if not _table_exists(conn, "flashcards") or not _table_exists(conn, "sr_reviews"):
        return None, 0
    rows = _q(conn,
              "SELECT r.last_rating AS rating "
              "FROM flashcards f JOIN sr_reviews r ON r.card_id = f.id "
              "WHERE f.topic_id = ? AND r.last_rating IS NOT NULL",
              (topic_id,))
    if not rows:
        return None, 0
    good = sum(1 for r in rows if str(r["rating"]).lower() in ("good", "easy"))
    return 100.0 * good / len(rows), len(rows)


def topic_mastery(conn, topic_id):
    """Return {"score", "band", "reasons", "components"} for one topic."""
    attempts = _topic_attempts(conn, topic_id)
    n_attempts = len(attempts)

    recent = _mean_correct(attempts[:RECENT_N])
    calc_rows = [r for r in attempts
                 if (r.get("qtype") or "").lower() == "numerical"]
    calc = _mean_correct(calc_rows)
    app_rows = [r for r in attempts
                if (r.get("qtype") or "").lower() in APP_QTYPES]
    app = _mean_correct(app_rows)
    recall, n_cards = _topic_flashcard_recall(conn, topic_id)

    components = {
        "recent_accuracy": None if recent is None else round(recent, 1),
        "flashcard_recall": None if recall is None else round(recall, 1),
        "calculation_success": None if calc is None else round(calc, 1),
        "application_success": None if app is None else round(app, 1),
    }

    present = {k: v for k, v in components.items() if v is not None}
    reasons = []

    if not present:
        return {"score": 0.0, "band": "weak",
                "reasons": ["no evidence: no attempts or flashcard reviews "
                            "recorded for this topic yet"],
                "components": components}

    weight_sum = sum(WEIGHTS[k] for k in present)
    score = sum(present[k] * WEIGHTS[k] for k in present) / weight_sum

    missing = [k for k in WEIGHTS if k not in present]
    if missing:
        reasons.append("no data yet for: %s (weights renormalised over the "
                       "rest)" % ", ".join(missing))

    capped = False
    if n_attempts < MIN_ATTEMPTS:
        if score > CAP_LOW_EVIDENCE:
            score = float(CAP_LOW_EVIDENCE)
            capped = True
        reasons.append("insufficient evidence: only %d question attempt(s) "
                       "(need %d); score capped at %d"
                       % (n_attempts, MIN_ATTEMPTS, CAP_LOW_EVIDENCE))

    if not capped:
        weakest = min(present, key=lambda k: present[k])
        if present[weakest] < 60:
            reasons.append("weakest component: %s at %.0f%%"
                           % (weakest.replace("_", " "), present[weakest]))
    reasons.append("%d question attempt(s), %d flashcard review(s) considered"
                   % (n_attempts, n_cards))

    score = round(score, 1)
    band = "weak" if score < 45 else ("developing" if score < 75 else "strong")
    return {"score": score, "band": band, "reasons": reasons,
            "components": components}


def chapter_mastery(conn, chapter_id):
    """Aggregate topic_mastery over a chapter's topics (simple mean)."""
    if not _table_exists(conn, "topics"):
        return {"score": 0.0, "band": "weak",
                "reasons": ["no topics found for this chapter"],
                "components": {}, "topics": {}}
    topics = _q(conn, "SELECT id, name FROM topics WHERE chapter_id=? "
                      "ORDER BY sort_order, name", (chapter_id,))
    if not topics:
        return {"score": 0.0, "band": "weak",
                "reasons": ["no topics found for this chapter"],
                "components": {}, "topics": {}}
    per_topic = {}
    for t in topics:
        per_topic[t["id"]] = {"name": t["name"],
                              **topic_mastery(conn, t["id"])}
    scores = [v["score"] for v in per_topic.values()]
    score = round(sum(scores) / len(scores), 1)
    band = "weak" if score < 45 else ("developing" if score < 75 else "strong")
    reasons = []
    weak = [(v["name"], v["score"]) for v in per_topic.values()
            if v["band"] == "weak"]
    if weak:
        reasons.append("weak topics: %s"
                       % ", ".join("%s (%.0f)" % w for w in weak))
    else:
        reasons.append("no weak topics in this chapter")
    reasons.append("mean of %d topic score(s)" % len(scores))
    return {"score": score, "band": band, "reasons": reasons,
            "components": {"topic_mean": score}, "topics": per_topic}


def all_topic_mastery(conn):
    """{topic_id: mastery_dict} for every topic with chapter info."""
    if not _table_exists(conn, "topics"):
        return {}
    rows = _q(conn, "SELECT t.id, t.name, t.chapter_id, c.title AS chapter_title "
                    "FROM topics t LEFT JOIN chapters c "
                    "ON c.id = t.chapter_id ORDER BY c.number, t.sort_order")
    out = {}
    for r in rows:
        m = topic_mastery(conn, r["id"])
        m["name"] = r["name"]
        m["chapter_id"] = r["chapter_id"]
        m["chapter_title"] = r["chapter_title"]
        out[r["id"]] = m
    return out
