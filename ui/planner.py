"""Daily Study Planner UI.

render(conn): plan inputs (exam date default 2027-02-06, hours/day, study
days, per-chapter priorities 1-3) -> generate -> daily session list with
complete / miss / reschedule controls. Today's items are highlighted.
No streaks, no gamification.
"""

from datetime import date

from core.planner import (generate_plan, mark_item, today_items, active_plan,
                          plan_items_for_day, WEEKDAYS)

try:
    from core import uihelpers as _uihelpers
except Exception:
    _uihelpers = None

DEFAULT_EXAM_DATE = "2027-02-06"


def json_loads(value):
    import json
    try:
        return json.loads(value) if isinstance(value, str) else (value or [])
    except (ValueError, TypeError):
        return []


def _q(conn, sql, params=()):
    cur = conn.execute(sql, params)
    cols = [c[0] for c in (cur.description or [])]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _chapters(conn):
    try:
        return _q(conn, "SELECT id, number, title FROM chapters ORDER BY number")
    except Exception:
        return []


def _render_item_row(conn, st, item, highlight=False):
    box = st.info if highlight else st.container
    with box():
        cols = st.columns([5, 2, 2, 2])
        cols[0].write("**%s**" % item["activity"])
        cols[0].caption("Status: %s" % item["status"])
        if cols[1].button("Complete", key="done_%s" % item["id"]):
            mark_item(conn, item["id"], "completed")
            st.rerun()
        if cols[2].button("Miss", key="miss_%s" % item["id"]):
            mark_item(conn, item["id"], "missed")
            st.rerun()
        with cols[3].popover("Reschedule"):
            new_date = st.date_input("New date", value=date.today(),
                                     key="rs_%s" % item["id"])
            if st.button("Move", key="mv_%s" % item["id"]):
                mark_item(conn, item["id"], "rescheduled",
                          new_date.isoformat())
                st.rerun()


def render(conn):
    import streamlit as st
    st.header("Daily Study Planner")
    st.caption("Generates a day-by-day plan from tomorrow to your exam "
               "date, weakest topics first. No streaks — just the plan.")

    plan = active_plan(conn)

    with st.expander("Plan settings", expanded=(plan is None)):
        with st.form("plan_inputs"):
            exam_date = st.date_input("Exam date",
                                      value=date(2027, 2, 6),
                                      min_value=date.today())
            hours = st.number_input("Hours per day", min_value=0.5,
                                    max_value=12.0, value=2.0, step=0.5)
            st.write("Study days")
            day_cols = st.columns(7)
            study_days = [d for i, d in enumerate(WEEKDAYS)
                          if day_cols[i].checkbox(d, value=True, key="sd_%s" % d)]
            st.write("Chapter priorities (3 = highest)")
            priorities = {}
            for ch in _chapters(conn):
                priorities[ch["id"]] = st.selectbox(
                    "Ch %s — %s" % (ch["number"], ch["title"]),
                    [1, 2, 3], index=1, key="pr_%s" % ch["id"])
            generate = st.form_submit_button("Generate plan")
        if generate:
            if not study_days:
                st.error("Pick at least one study day.")
            else:
                try:
                    plan_id = generate_plan(
                        conn, exam_date=exam_date.isoformat(),
                        hours_per_day=float(hours),
                        study_days=study_days, priorities=priorities)
                except ValueError as e:
                    st.error(str(e))
                else:
                    st.success("Plan generated (id %d)." % plan_id)
                    st.rerun()

    plan = active_plan(conn)
    if plan is None:
        st.info("No active plan yet — set your inputs above and generate one.")
        return

    st.subheader(plan["name"])
    st.caption("Exam %s · %.1f h/day · days: %s" %
               (plan["exam_date"], plan["hours_per_day"],
                ", ".join(json_loads(plan["study_days_json"]))))

    todays = today_items(conn)
    st.subheader("Today (%s)" % date.today().isoformat())
    if not todays:
        st.caption("Nothing scheduled for today.")
    for item in todays:
        _render_item_row(conn, st, item, highlight=True)

    st.subheader("Upcoming")
    days = _q(conn, "SELECT DISTINCT day_date FROM plan_items "
                    "WHERE plan_id=? AND day_date>? ORDER BY day_date LIMIT 14",
              (plan["id"], date.today().isoformat()))
    if not days:
        st.caption("No upcoming items.")
    for d in days:
        with st.expander(d["day_date"]):
            for item in plan_items_for_day(conn, plan["id"], d["day_date"]):
                _render_item_row(conn, st, item)

    if st.button("Deactivate this plan"):
        conn.execute("UPDATE study_plans SET active=0 WHERE id=?", (plan["id"],))
        conn.commit()
        st.rerun()
