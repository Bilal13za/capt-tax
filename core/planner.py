"""Daily study-plan generator for the CAPT Taxation app.

generate_plan() builds a study_plans row plus one plan_items row per activity,
from tomorrow through the exam date, on the student's chosen study days.
Activity choice is deterministic and performance-driven: topics are ordered
weak-first using core/mastery.py when it is importable, otherwise by chapter
then topic order.

Activity catalogue (minutes are estimates used to respect hours_per_day):
    read            "Read topic X"                              30 min
    flashcards      "Review N due flashcards"                   20 min
    calculations    "Solve 3 calculation questions (chapter)"   45 min
    test            "Topic test (topic)"                        30 min
    reattempt       "Reattempt incorrect questions"             40 min
    examday         "Exam day — light review only"              30 min

No streamlit here — pure logic over a sqlite3 connection.
"""

import json
from datetime import date, datetime, timedelta

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

ACTIVITY_MINUTES = {
    "read": 30,
    "flashcards": 20,
    "calculations": 45,
    "test": 30,
    "reattempt": 40,
    "examday": 30,
}


def _q(conn, sql, params=()):
    cur = conn.execute(sql, params)
    cols = [c[0] for c in (cur.description or [])]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def _table_exists(conn, name):
    return bool(_q(conn, "SELECT name FROM sqlite_master WHERE type='table' "
                         "AND name=?", (name,)))


def _today():
    return date.today()


def _parse_date(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def _mastery_scores(conn):
    """{topic_id: score} weak-first; falls back to chapter/topic order."""
    try:
        from core import mastery as _mastery
    except Exception:
        _mastery = None
    topics = _q(conn, "SELECT t.id, t.name, t.chapter_id, t.sort_order, "
                      "c.number AS ch_no, c.title AS ch_title "
                      "FROM topics t LEFT JOIN chapters c ON c.id=t.chapter_id "
                      "ORDER BY c.number, t.sort_order")
    if _mastery is not None:
        scored = []
        for t in topics:
            try:
                m = _mastery.topic_mastery(conn, t["id"])
                scored.append((m["score"], t))
            except Exception:
                scored.append((0.0, t))
        scored.sort(key=lambda s: (s[0], s[1]["ch_no"] or 0,
                                   s[1]["sort_order"] or 0))
        return [t for _, t in scored]
    return topics


def _due_flashcards(conn, day):
    if not _table_exists(conn, "sr_reviews"):
        return 0
    rows = _q(conn, "SELECT COUNT(*) AS n FROM sr_reviews "
                    "WHERE date(next_due) <= date(?)", (day.isoformat(),))
    return int(rows[0]["n"]) if rows else 0


def _incorrect_count(conn):
    if not _table_exists(conn, "attempts"):
        return 0
    rows = _q(conn, "SELECT question_id, correct, id FROM attempts "
                    "WHERE question_id IS NOT NULL")
    latest = {}
    for r in rows:
        qid = r["question_id"]
        if qid not in latest or r["id"] > latest[qid]["id"]:
            latest[qid] = r
    return sum(1 for r in latest.values() if r["correct"] == 0)


def _numerical_chapters(conn):
    if not _table_exists(conn, "questions"):
        return []
    rows = _q(conn, "SELECT DISTINCT chapter_id FROM questions "
                    "WHERE qtype='numerical' AND chapter_id IS NOT NULL")
    return [r["chapter_id"] for r in rows]


def _chapter_title(conn, chapter_id):
    rows = _q(conn, "SELECT title FROM chapters WHERE id=?", (chapter_id,))
    return rows[0]["title"] if rows else chapter_id


def _add_item(conn, plan_id, day, kind, activity, detail):
    conn.execute("INSERT INTO plan_items (plan_id, day_date, activity, "
                 "detail_json, status, created_at) VALUES (?, ?, ?, ?, "
                 "'pending', ?)",
                 (plan_id, day.isoformat(), activity, json.dumps(detail),
                  datetime.now().isoformat(timespec="seconds")))


def generate_plan(conn, exam_date="2027-02-06", hours_per_day=2.0,
                  study_days=None, priorities=None, name=None):
    """Create a study plan and return its plan_id.

    priorities: {chapter_id: 1..3}; higher priority chapters get their
    topics scheduled earlier and calculation sessions sooner.
    """
    exam = _parse_date(exam_date)
    start = _today() + timedelta(days=1)
    if exam <= _today():
        raise ValueError("exam_date must be in the future")
    minutes_per_day = int(float(hours_per_day) * 60)
    if minutes_per_day <= 0:
        raise ValueError("hours_per_day must be positive")
    study_days = study_days or WEEKDAYS
    priorities = priorities or {}
    day_names = set(study_days)

    topics = _mastery_scores(conn)  # weak-first when mastery is available
    # priority ordering: higher priority chapters first (stable for the rest)
    indexed = list(enumerate(topics))
    indexed.sort(key=lambda it: (-int(priorities.get(it[1]["chapter_id"], 1)),
                                 it[0]))
    topics = [t for _, t in indexed]
    num_chapters = _numerical_chapters(conn)
    num_chapters.sort(key=lambda c: -int(priorities.get(c, 1)))
    incorrect_total = _incorrect_count(conn)

    cur = conn.execute("UPDATE study_plans SET active=0 WHERE active=1")
    plan_name = name or "Study plan to %s" % exam.isoformat()
    cur = conn.execute(
        "INSERT INTO study_plans (name, exam_date, hours_per_day, "
        "study_days_json, priorities_json, created_at, active) "
        "VALUES (?, ?, ?, ?, ?, ?, 1)",
        (plan_name, exam.isoformat(), float(hours_per_day),
         json.dumps(study_days), json.dumps(priorities),
         datetime.now().isoformat(timespec="seconds")))
    plan_id = cur.lastrowid

    topic_cycle = list(topics)
    ti = 0          # rotating index into topic_cycle
    calc_i = 0      # rotating index into num_chapters
    reattempt_done = set()

    day = start
    while day <= exam:
        if WEEKDAYS[day.weekday()] in day_names:
            if day == exam:
                _add_item(conn, plan_id, day, "examday",
                          "Exam day — light review only",
                          {"kind": "examday", "minutes": ACTIVITY_MINUTES["examday"]})
            else:
                budget = minutes_per_day
                # 1) due flashcards first
                due = _due_flashcards(conn, day)
                if due and budget >= ACTIVITY_MINUTES["flashcards"]:
                    n = min(due, 25)
                    _add_item(conn, plan_id, day, "flashcards",
                              "Review %d due flashcard%s" % (n, "" if n == 1 else "s"),
                              {"kind": "flashcards", "count": n,
                               "minutes": ACTIVITY_MINUTES["flashcards"]})
                    budget -= ACTIVITY_MINUTES["flashcards"]
                # 2) read weakest uncovered topic
                if topic_cycle and budget >= ACTIVITY_MINUTES["read"]:
                    t = topic_cycle[ti % len(topic_cycle)]
                    ti += 1
                    _add_item(conn, plan_id, day, "read",
                              "Read topic: %s" % t["name"],
                              {"kind": "read", "topic_id": t["id"],
                               "chapter_id": t["chapter_id"],
                               "minutes": ACTIVITY_MINUTES["read"]})
                    budget -= ACTIVITY_MINUTES["read"]
                # 3) calculation practice
                if num_chapters and budget >= ACTIVITY_MINUTES["calculations"]:
                    ch = num_chapters[calc_i % len(num_chapters)]
                    calc_i += 1
                    _add_item(conn, plan_id, day, "calculations",
                              "Solve 3 calculation questions (%s)"
                              % _chapter_title(conn, ch),
                              {"kind": "calculations", "chapter_id": ch,
                               "count": 3,
                               "minutes": ACTIVITY_MINUTES["calculations"]})
                    budget -= ACTIVITY_MINUTES["calculations"]
                # 4) topic test on the next weak topic
                if topic_cycle and budget >= ACTIVITY_MINUTES["test"]:
                    t = topic_cycle[ti % len(topic_cycle)]
                    ti += 1
                    _add_item(conn, plan_id, day, "test",
                              "Topic test: %s" % t["name"],
                              {"kind": "test", "topic_id": t["id"],
                               "chapter_id": t["chapter_id"],
                               "minutes": ACTIVITY_MINUTES["test"]})
                    budget -= ACTIVITY_MINUTES["test"]
                # 5) reattempt incorrect (at most every few days)
                if (incorrect_total and day not in reattempt_done
                        and budget >= ACTIVITY_MINUTES["reattempt"]
                        and (day - start).days % 3 == 0):
                    reattempt_done.add(day)
                    _add_item(conn, plan_id, day, "reattempt",
                              "Reattempt incorrect questions",
                              {"kind": "reattempt",
                               "minutes": ACTIVITY_MINUTES["reattempt"]})
                    budget -= ACTIVITY_MINUTES["reattempt"]
        day += timedelta(days=1)

    conn.commit()
    return plan_id


def mark_item(conn, item_id, status, new_date=None):
    """Set a plan item's status.

    status: completed | missed | rescheduled.
    For rescheduled, new_date ("YYYY-MM-DD") moves the item; when omitted
    the item moves to the next day.
    """
    if status not in ("completed", "missed", "rescheduled", "pending"):
        raise ValueError("status must be completed|missed|rescheduled|pending")
    rows = _q(conn, "SELECT * FROM plan_items WHERE id=?", (item_id,))
    if not rows:
        raise ValueError("No plan item with id %r" % (item_id,))
    if status == "rescheduled":
        target = new_date or (_parse_date(rows[0]["day_date"]) +
                              timedelta(days=1)).isoformat()
        _parse_date(target)  # validate
        conn.execute("UPDATE plan_items SET status='rescheduled', "
                     "day_date=? WHERE id=?", (target, item_id))
    else:
        conn.execute("UPDATE plan_items SET status=? WHERE id=?",
                     (status, item_id))
    conn.commit()
    return _q(conn, "SELECT * FROM plan_items WHERE id=?", (item_id,))[0]


def today_items(conn):
    """Today's items for the active plan (all statuses, in schedule order)."""
    plans = _q(conn, "SELECT id FROM study_plans WHERE active=1 "
                     "ORDER BY id DESC LIMIT 1")
    if not plans:
        return []
    return _q(conn, "SELECT * FROM plan_items WHERE plan_id=? AND "
                    "day_date=? ORDER BY id",
              (plans[0]["id"], _today().isoformat()))


def plan_items_for_day(conn, plan_id, day):
    if isinstance(day, date):
        day = day.isoformat()
    return _q(conn, "SELECT * FROM plan_items WHERE plan_id=? AND "
                    "day_date=? ORDER BY id", (plan_id, day))


def active_plan(conn):
    plans = _q(conn, "SELECT * FROM study_plans WHERE active=1 "
                     "ORDER BY id DESC LIMIT 1")
    return plans[0] if plans else None


def next_pending_item(conn):
    """The next pending item on/after today for the active plan."""
    plan = active_plan(conn)
    if not plan:
        return None
    rows = _q(conn, "SELECT * FROM plan_items WHERE plan_id=? AND "
                    "status='pending' AND day_date>=? ORDER BY day_date, id "
                    "LIMIT 1", (plan["id"], _today().isoformat()))
    return rows[0] if rows else None
