"""Operations Copilot: natural language -> intent -> SQL -> validation -> read-only query -> explanation.

With no LLM configured, intent detection is pattern-based and SQL comes from
reviewed templates. With an LLM configured, unmatched questions fall through to
LLM-generated SQL. Either way the SQL goes through sql_guard and runs as the
SELECT-only database role, and the answer always shows the query and its rows.
"""
import re
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.ai.providers import Prompt, get_llm
from app.analytics import predictions
from app.analytics.metrics import emergency_load
from app.analytics.sql_guard import ALLOWED_TABLES, UnsafeSQL, run_readonly
from app.core.clock import now, today_start
from app.core.config import settings

WAIT = "EXTRACT(EPOCH FROM (a.started_at - a.checked_in_at)) / 60.0"
SUGGESTIONS = ["Why did waiting time increase today?", "Which department is overloaded?",
               "What are the top patient complaints this week?", "Which doctors have the highest utilization?",
               "Predict tomorrow's patient volume.", "Which department should receive additional staff?",
               "Why is the emergency department overloaded?",
               "Which department had the highest average waiting time this month?"]


def _period(question: str) -> tuple[datetime, datetime, str]:
    q, current, t0 = question.lower(), now(), today_start()
    if "yesterday" in q:
        return t0 - timedelta(days=1), t0, "yesterday"
    if "today" in q or "right now" in q or "currently" in q:
        return t0, current, "today"
    if "week" in q:
        return current - timedelta(days=7), current, "the last 7 days"
    return current - timedelta(days=30), current, "the last 30 days"


def _result(intent: str, answer: str, queries: list[dict], chart: dict | None = None, data: list[dict] | None = None,
            mode: str = "template") -> dict:
    return {"intent": intent, "answer": answer, "queries": queries, "chart": chart,
            "data": data if data is not None else (queries[0]["rows"] if queries else []), "mode": mode,
            "note": "AI-generated analysis of hospital data. Recommendations are for human review."}


def _query(title: str, sql: str, **params) -> dict:
    sql = re.sub(r"\n\s+", "\n", sql.strip())
    return {"title": title, "sql": sql, "params": {k: str(v) for k, v in params.items()},
            "rows": run_readonly(sql, params)}


# --------------------------------------------------------------------------- intents
def wait_by_department(db: Session, question: str) -> dict:
    start, end, label = _period(question)
    q = _query("Average wait by department", f"""
        SELECT d.name AS department, ROUND(AVG({WAIT})::numeric, 1)::float AS avg_wait_minutes,
               COUNT(*) AS consultations
        FROM appointments a JOIN departments d ON d.id = a.department_id
        WHERE a.started_at >= :start AND a.started_at < :end AND a.checked_in_at IS NOT NULL
        GROUP BY d.name ORDER BY avg_wait_minutes DESC""", start=start, end=end)
    if not q["rows"]:
        return _result("wait_by_department", f"There are no completed consultations for {label} yet.", [q])
    top = q["rows"][0]
    total = sum(r["consultations"] for r in q["rows"])
    hospital = sum(r["avg_wait_minutes"] * r["consultations"] for r in q["rows"]) / total
    answer = (f"**{top['department']}** had the highest average waiting time over {label}.\n\n"
              f"- Average wait: **{top['avg_wait_minutes']:.0f} minutes**\n"
              f"- Compared with hospital average ({hospital:.0f} min): **{top['avg_wait_minutes'] - hospital:+.0f} "
              f"minutes**\n- Based on {top['consultations']} consultations")
    return _result("wait_by_department", answer, [q],
                   {"type": "bar", "x": "department", "series": [{"key": "avg_wait_minutes", "label": "Avg wait (min)"}]})


def why_wait_changed(db: Session, question: str) -> dict:
    t0, current = today_start(), now()
    q = _query("Today's wait and volume vs the 7-day baseline, by department", f"""
        SELECT d.name AS department,
               ROUND((AVG({WAIT}) FILTER (WHERE a.started_at >= :t0))::numeric, 1)::float AS wait_today,
               ROUND((AVG({WAIT}) FILTER (WHERE a.started_at < :t0))::numeric, 1)::float AS wait_baseline,
               COUNT(*) FILTER (WHERE a.started_at >= :t0) AS seen_today,
               ROUND((COUNT(*) FILTER (WHERE a.started_at < :t0 AND a.started_at::time <= CAST(:clock AS time))
                      / 7.0)::numeric, 1)::float AS seen_baseline
        FROM appointments a JOIN departments d ON d.id = a.department_id
        WHERE a.started_at >= :start AND a.checked_in_at IS NOT NULL
        GROUP BY d.name ORDER BY d.name""", t0=t0, start=t0 - timedelta(days=7), clock=current.time())
    live = [r for r in q["rows"] if r["wait_today"] is not None and r["wait_baseline"]]
    if not live:
        return _result("why_wait_changed", "There isn't enough activity today yet to compare against the baseline.",
                       [q])
    for r in live:
        r["wait_change"] = round(r["wait_today"] - r["wait_baseline"], 1)
    live.sort(key=lambda r: -r["wait_change"])
    today = sum(r["wait_today"] * r["seen_today"] for r in live) / max(1, sum(r["seen_today"] for r in live))
    base = sum(r["wait_baseline"] * r["seen_today"] for r in live) / max(1, sum(r["seen_today"] for r in live))
    gap = round(today - base)
    versus = "in line with" if gap == 0 else f"{abs(gap)} minutes {'above' if gap > 0 else 'below'}"
    lines = [f"Today's average wait is **{today:.0f} minutes**, {versus} the 7-day baseline for the same "
             f"departments ({base:.0f} min).", ""]
    drivers = [r for r in live if r["wait_change"] > 1][:3]
    if drivers:
        lines.append("Largest contributors:")
        for i, r in enumerate(drivers, 1):
            volume = ""
            if r["seen_baseline"]:
                volume = f", with volume {(r['seen_today'] / r['seen_baseline'] - 1) * 100:+.0f}% vs baseline"
            lines.append(f"{i}. **{r['department']}**: {r['wait_today']:.0f} min today vs "
                         f"{r['wait_baseline']:.0f} min ({r['wait_change']:+.0f} min){volume}")
        lines += ["", f"**Suggested action:** review staffing in {drivers[0]['department']} for the rest of today."]
    else:
        lines.append("No department is running materially above its own baseline today.")
    return _result("why_wait_changed", "\n".join(lines), [q],
                   {"type": "bar", "x": "department", "series": [{"key": "wait_today", "label": "Today (min)"},
                                                                 {"key": "wait_baseline", "label": "7-day baseline"}]},
                   data=live)


def _pressure(question: str) -> dict:
    return _query("Today's load per department", """
        SELECT d.name AS department,
               COUNT(a.id) FILTER (WHERE a.status <> 'cancelled') AS patients_today,
               COUNT(a.id) FILTER (WHERE a.status IN ('waiting', 'checked_in')) AS waiting_now,
               (SELECT COUNT(*) FROM doctors doc WHERE doc.department_id = d.id AND doc.is_available
                    AND :hour >= doc.shift_start AND :hour < doc.shift_end) AS doctors_on_shift
        FROM departments d
        LEFT JOIN appointments a ON a.department_id = d.id AND a.scheduled_at >= :t0 AND a.scheduled_at < :t1
        GROUP BY d.id, d.name ORDER BY waiting_now DESC, patients_today DESC""",
                  t0=today_start(), t1=today_start() + timedelta(days=1), hour=now().hour)


def overloaded_department(db: Session, question: str) -> dict:
    q = _pressure(question)
    for r in q["rows"]:
        r["waiting_per_doctor"] = round(r["waiting_now"] / max(1, r["doctors_on_shift"]), 1)
    ranked = sorted(q["rows"], key=lambda r: (-r["waiting_per_doctor"], -r["patients_today"]))
    top = ranked[0]
    if top["waiting_now"] == 0:
        busiest = max(ranked, key=lambda r: r["patients_today"])
        answer = (f"No department has patients waiting right now. **{busiest['department']}** has the highest "
                  f"volume today with {busiest['patients_today']} patients.")
    else:
        answer = (f"**{top['department']}** is under the most pressure right now.\n\n"
                  f"- Waiting now: **{top['waiting_now']} patients**\n"
                  f"- Doctors on shift: **{top['doctors_on_shift']}** "
                  f"({top['waiting_per_doctor']} waiting per doctor)\n"
                  f"- Patients today: {top['patients_today']}")
    return _result("overloaded_department", answer, [q],
                   {"type": "bar", "x": "department", "series": [{"key": "waiting_now", "label": "Waiting now"},
                                                                 {"key": "patients_today", "label": "Patients today"}]},
                   data=ranked)


def staffing_recommendation(db: Session, question: str) -> dict:
    result = overloaded_department(db, question)
    ranked = result["data"]
    top = ranked[0]
    forecast = predictions.wait_time_predictions(db)
    predicted = next((f for f in forecast if f["department"] == top["department"]), None)
    lines = [f"**{top['department']}** would benefit most from additional staff right now.", "",
             f"- {top['waiting_now']} patients waiting across {top['doctors_on_shift']} doctor(s) on shift",
             f"- {top['patients_today']} patients scheduled today"]
    if predicted:
        lines.append(f"- Estimated wait for a new arrival: about {predicted['value']} minutes "
                     f"(confidence {predicted['confidence'] * 100:.0f}%)")
    lines += ["", "**Suggested action:** consider moving one available clinician to this department. "
                  "This is a recommendation for the duty manager to review, not an automatic change."]
    result.update(intent="staffing_recommendation", answer="\n".join(lines))
    return result


def emergency_overload(db: Session, question: str) -> dict:
    t0, current = today_start(), now()
    load = emergency_load(db)
    hourly = _query("Emergency arrivals by hour: today vs 7-day average", """
        SELECT EXTRACT(HOUR FROM a.scheduled_at)::int AS hour,
               COUNT(*) FILTER (WHERE a.scheduled_at >= :t0) AS today,
               ROUND((COUNT(*) FILTER (WHERE a.scheduled_at < :t0) / 7.0)::numeric, 1)::float AS average_7d
        FROM appointments a JOIN departments d ON d.id = a.department_id
        WHERE d.name = 'Emergency' AND a.status <> 'cancelled' AND a.scheduled_at >= :start AND a.scheduled_at <= :now
        GROUP BY 1 ORDER BY 1""", t0=t0, start=t0 - timedelta(days=7), now=current)
    physicians = _query("Emergency physicians: consultations completed today", """
        SELECT u.full_name AS doctor, doc.shift_start, doc.shift_end, doc.avg_consult_minutes,
               COUNT(a.id) FILTER (WHERE a.status = 'completed') AS completed_today
        FROM doctors doc JOIN users u ON u.id = doc.user_id JOIN departments d ON d.id = doc.department_id
        LEFT JOIN appointments a ON a.doctor_id = doc.id AND a.scheduled_at >= :t0 AND a.scheduled_at <= :now
        WHERE d.name = 'Emergency' GROUP BY u.full_name, doc.shift_start, doc.shift_end, doc.avg_consult_minutes
        ORDER BY doctor""", t0=t0, now=current)
    discharge = _query("Discharge processing time: last 7 days vs prior 3 weeks", """
        SELECT ROUND((AVG(EXTRACT(EPOCH FROM (released_at - discharge_ordered_at)) / 3600)
                      FILTER (WHERE released_at >= :recent))::numeric, 2)::float AS recent_hours,
               ROUND((AVG(EXTRACT(EPOCH FROM (released_at - discharge_ordered_at)) / 3600)
                      FILTER (WHERE released_at < :recent))::numeric, 2)::float AS baseline_hours
        FROM bed_assignments WHERE released_at >= :start AND discharge_ordered_at IS NOT NULL""",
                       recent=current - timedelta(days=7), start=current - timedelta(days=28))

    factors = []
    evening = [r for r in hourly["rows"] if 17 <= r["hour"] < 20]
    rest = [r for r in hourly["rows"] if not 17 <= r["hour"] < 20 and r["average_7d"]]
    if evening and rest:
        peak = sum(r["average_7d"] for r in evening) / len(evening)
        normal = sum(r["average_7d"] for r in rest) / len(rest)
        if peak > normal * 1.2:
            factors.append(f"Higher patient arrivals between 17:00 and 20:00 "
                           f"({peak:.1f}/hour vs {normal:.1f}/hour at other times)")
    below = []
    for p in physicians["rows"]:
        on_shift_hours = min(current.hour + current.minute / 60, p["shift_end"]) - p["shift_start"]
        if on_shift_hours >= 1:
            capacity = on_shift_hours * 60 / (p["avg_consult_minutes"] + 14)  # consult + turnaround
            if p["completed_today"] < 0.75 * capacity:
                below.append(p["doctor"])
    if below:
        factors.append(f"{len(below)} physician{'s' if len(below) != 1 else ''} operating below scheduled capacity "
                       f"today ({', '.join(below)})")
    d = discharge["rows"][0] if discharge["rows"] else {}
    if d.get("recent_hours") and d.get("baseline_hours") and d["recent_hours"] > d["baseline_hours"] * 1.1:
        factors.append(f"Longer-than-normal discharge processing ({d['recent_hours']:.1f} h vs "
                       f"{d['baseline_hours']:.1f} h), which slows bed release")

    word = "above" if load["vs_baseline_pct"] >= 0 else "below"
    lines = [f"Emergency department volume is **{abs(load['vs_baseline_pct']):.0f}% {word}** the 7-day average for "
             f"this time of day ({load['today']} arrivals vs {load['baseline']:.0f}). Current load: "
             f"**{load['level']}**, with {load['waiting']} patients waiting.", ""]
    if factors:
        lines.append(f"{len(factors)} contributing factor{'s' if len(factors) != 1 else ''} detected:")
        lines += [f"{i}. {f}" for i, f in enumerate(factors, 1)]
        lines += ["", "**Suggested action:** review staffing allocation between 17:00 and 20:00."]
    else:
        lines.append("No single contributing factor stands out in today's data.")
    return _result("emergency_overload", "\n".join(lines), [hourly, physicians, discharge],
                   {"type": "line", "x": "hour", "series": [{"key": "today", "label": "Today"},
                                                            {"key": "average_7d", "label": "7-day average"}]},
                   data=hourly["rows"])


def top_complaints(db: Session, question: str) -> dict:
    start, end, label = _period(question)
    q = _query("Negative feedback by category", """
        SELECT REPLACE(category, '_', ' ') AS category, COUNT(*) AS negative_feedback,
               COUNT(*) FILTER (WHERE urgency = 'high') AS high_urgency,
               MODE() WITHIN GROUP (ORDER BY theme) AS most_common_theme
        FROM feedback WHERE sentiment = 'negative' AND created_at >= :start AND created_at < :end
        GROUP BY category ORDER BY negative_feedback DESC""", start=start, end=end)
    if not q["rows"]:
        return _result("top_complaints", f"No negative feedback was recorded for {label}.", [q])
    lines = [f"Top patient complaints over {label}:", ""]
    for i, r in enumerate(q["rows"][:3], 1):
        urgent = f" ({r['high_urgency']} high urgency)" if r["high_urgency"] else ""
        noun = "entry" if r["negative_feedback"] == 1 else "entries"
        lines.append(f"{i}. **{r['category'].capitalize()}**: {r['negative_feedback']} negative {noun}{urgent}; "
                     f"most common theme: {r['most_common_theme']}")
    return _result("top_complaints", "\n".join(lines), [q],
                   {"type": "bar", "x": "category", "series": [{"key": "negative_feedback", "label": "Negative entries"}]})


def doctor_utilization(db: Session, question: str) -> dict:
    start, end, label = _period(question)
    q = _query("Doctor utilization", """
        SELECT u.full_name AS doctor, d.name AS department, COUNT(*) AS patients,
               ROUND((SUM(EXTRACT(EPOCH FROM (a.completed_at - a.started_at))) / 3600)::numeric, 1)::float
                   AS consultation_hours,
               (COUNT(DISTINCT a.scheduled_at::date) * (doc.shift_end - doc.shift_start))::float AS scheduled_hours
        FROM appointments a JOIN doctors doc ON doc.id = a.doctor_id JOIN users u ON u.id = doc.user_id
        JOIN departments d ON d.id = doc.department_id
        WHERE a.status = 'completed' AND a.started_at >= :start AND a.started_at < :end
        GROUP BY u.full_name, d.name, doc.shift_end, doc.shift_start""", start=start, end=end)
    for r in q["rows"]:
        r["utilization_pct"] = round(r["consultation_hours"] / r["scheduled_hours"] * 100, 1) \
            if r["scheduled_hours"] else 0.0
    ranked = sorted(q["rows"], key=lambda r: -r["utilization_pct"])[:10]
    if not ranked:
        return _result("doctor_utilization", f"No completed consultations were found for {label}.", [q])
    lines = [f"Doctors with the highest utilization over {label} (consultation hours ÷ scheduled hours):", ""]
    lines += [f"{i}. **{r['doctor']}** ({r['department']}): {r['utilization_pct']:.0f}% · "
              f"{r['patients']} patients" for i, r in enumerate(ranked[:5], 1)]
    return _result("doctor_utilization", "\n".join(lines), [q],
                   {"type": "bar", "x": "doctor", "series": [{"key": "utilization_pct", "label": "Utilization %"}]},
                   data=ranked)


def volume_forecast(db: Session, question: str) -> dict:
    f = predictions.volume_forecast(db)
    lines = [f"Tomorrow's predicted patient volume is **{f['next_day']} patients** "
             f"(confidence {f['confidence'] * 100:.0f}%).", "",
             f"- Next hour: about {f['next_hour']} patients", f"- Next 7 days: about {f['next_week']} patients", "",
             "Main contributing factors:"]
    lines += [f"- {x['name']}: {x['detail']}" for x in f["factors"]]
    lines += ["", f"_{f['label']}._"]
    return _result("volume_forecast", "\n".join(lines), [],
                   {"type": "line", "x": "day", "series": [{"key": "actual", "label": "Actual"},
                                                           {"key": "predicted", "label": "Predicted"}]},
                   data=f["series"], mode="forecast_model")


def no_show_rate(db: Session, question: str) -> dict:
    start, end, label = _period(question)
    q = _query("No-show rate by department", """
        SELECT d.name AS department,
               ROUND((AVG((a.status = 'no_show')::int) * 100)::numeric, 1)::float AS no_show_rate_pct,
               COUNT(*) AS appointments
        FROM appointments a JOIN departments d ON d.id = a.department_id
        WHERE a.status IN ('completed', 'no_show') AND a.scheduled_at >= :start AND a.scheduled_at < :end
        GROUP BY d.name ORDER BY no_show_rate_pct DESC""", start=start, end=end)
    if not q["rows"]:
        return _result("no_show_rate", f"No attended or missed appointments were found for {label}.", [q])
    top = q["rows"][0]
    return _result("no_show_rate", f"**{top['department']}** has the highest no-show rate over {label}: "
                                   f"**{top['no_show_rate_pct']:.1f}%** of {top['appointments']} appointments.", [q],
                   {"type": "bar", "x": "department", "series": [{"key": "no_show_rate_pct", "label": "No-show %"}]})


def bed_occupancy(db: Session, question: str) -> dict:
    q = _query("Bed occupancy by ward", """
        SELECT w.name AS ward, COUNT(*) AS beds, COUNT(*) FILTER (WHERE b.status = 'occupied') AS occupied,
               ROUND((COUNT(*) FILTER (WHERE b.status = 'occupied') * 100.0 / COUNT(*))::numeric, 1)::float
                   AS occupancy_pct
        FROM wards w JOIN beds b ON b.ward_id = w.id GROUP BY w.name ORDER BY occupancy_pct DESC""")
    top = q["rows"][0]
    total, occupied = sum(r["beds"] for r in q["rows"]), sum(r["occupied"] for r in q["rows"])
    return _result("bed_occupancy", f"Hospital bed occupancy is **{occupied / total * 100:.0f}%** "
                                    f"({occupied} of {total} beds). **{top['ward']}** is the fullest ward at "
                                    f"**{top['occupancy_pct']:.0f}%**.", [q],
                   {"type": "bar", "x": "ward", "series": [{"key": "occupancy_pct", "label": "Occupancy %"}]})


def satisfaction(db: Session, question: str) -> dict:
    start, end, label = _period(question)
    q = _query("Patient satisfaction by department", """
        SELECT d.name AS department, ROUND(AVG(f.overall)::numeric, 2)::float AS satisfaction,
               COUNT(*) AS responses
        FROM feedback f JOIN departments d ON d.id = f.department_id
        WHERE f.created_at >= :start AND f.created_at < :end
        GROUP BY d.name ORDER BY satisfaction""", start=start, end=end)
    if not q["rows"]:
        return _result("satisfaction", f"No feedback was recorded for {label}.", [q])
    low, high = q["rows"][0], q["rows"][-1]
    return _result("satisfaction", f"Over {label}, **{high['department']}** has the highest satisfaction "
                                   f"({high['satisfaction']:.2f} / 5) and **{low['department']}** the lowest "
                                   f"({low['satisfaction']:.2f} / 5).", [q],
                   {"type": "bar", "x": "department", "series": [{"key": "satisfaction", "label": "Satisfaction / 5"}]})


INTENTS: list[tuple[str, Callable[[Session, str], dict]]] = [
    (r"emergency.*(overload|busy|load|crowd|why|pressure)|(overload|why).*emergency", emergency_overload),
    (r"(predict|forecast|expect|tomorrow|next week).*(volume|patients|visits)|patient volume", volume_forecast),
    (r"(additional|more|extra) staff|staffing|should receive", staffing_recommendation),
    (r"why.*(wait|delay)|(wait|delay).*(increase|longer|worse|up\b)", why_wait_changed),
    (r"(highest|longest|average|worst|most).*(wait)|wait.*(by|per|each) department", wait_by_department),
    (r"overload|busiest|under pressure|most (patients|loaded)|which department is", overloaded_department),
    (r"complain|negative feedback|top .*feedback|unhappy", top_complaints),
    (r"utili[sz]|busiest doctor|doctor.*(workload|hours)", doctor_utilization),
    (r"no[- ]?show|missed appointment", no_show_rate),
    (r"\bbeds?\b|occupancy|\bicu\b|ward", bed_occupancy),
    (r"satisf|rating|\bnps\b|happy", satisfaction),
]

_SCHEMA_HINT = """Tables (PostgreSQL; timestamps are hospital-local, naive):
departments(id, name) · doctors(id, user_id, department_id, shift_start, shift_end, avg_consult_minutes)
users(id, full_name) · patients(id, gender, date_of_birth, primary_department_id, status, created_at)
appointments(id, patient_id, doctor_id, department_id, scheduled_at, status, appointment_type, checked_in_at,
  started_at, completed_at, created_at)  -- status: scheduled|checked_in|waiting|in_consultation|completed|cancelled|no_show
wards(id, name) · beds(id, ward_id, status) · bed_assignments(id, bed_id, assigned_at, released_at)
feedback(id, department_id, doctor_id, overall, wait_time, nps, sentiment, category, urgency, theme, created_at)
complaints(id, department_id, category, urgency, status, created_at)"""


async def _llm_sql(question: str) -> dict:
    llm = get_llm()
    sql = await llm.generate(Prompt(
        system="You write a single read-only PostgreSQL SELECT statement that answers the user's question about "
               "hospital operations. Return only SQL, with no commentary and no code fences. Never select personal "
               f"identifiers. Use only these tables.\n\n{_SCHEMA_HINT}\n\nThe current time is {now().isoformat()}.",
        user=question, question=question))
    sql = re.sub(r"^```(?:sql)?|```$", "", sql.strip(), flags=re.M).strip().rstrip(";")
    query = {"title": "Generated query", "sql": sql, "params": {}, "rows": run_readonly(sql)}
    summary = await llm.generate(Prompt(
        system="Summarise the query result for a hospital operations manager in at most 80 words. State only what "
               "the rows show. If the rows are empty, say so.",
        user=f"Question: {question}\n\nRows: {query['rows'][:30]}", question=question))
    return _result("generated_sql", summary, [query], None, mode="llm")


async def ask(db: Session, question: str) -> dict:
    q = question.lower()
    for pattern, handler in INTENTS:
        if re.search(pattern, q):
            return handler(db, question)
    if settings.llm_enabled:
        try:
            return await _llm_sql(question)
        except UnsafeSQL as exc:
            return _result("rejected", f"I generated a query for that, but it failed safety validation and was not "
                                       f"run: {exc}", [], mode="llm")
        except Exception:
            return _result("failed", "I couldn't answer that from the hospital data. Try rephrasing the question.",
                           [], mode="llm")
    return _result("unsupported",
                   "I can't answer that yet. In demo mode I can analyse waiting times, department load, staffing, "
                   "doctor utilization, complaints, no-shows, bed occupancy, satisfaction and volume forecasts.\n\n"
                   "Try one of the suggested questions.", [])


__all__ = ["ask", "SUGGESTIONS", "ALLOWED_TABLES"]
