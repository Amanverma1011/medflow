"""Operational metrics. Every number the dashboards show is computed here from the database."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.clock import now, today_start

WAIT = "EXTRACT(EPOCH FROM (a.started_at - a.checked_in_at)) / 60.0"
CONSULT = "EXTRACT(EPOCH FROM (a.completed_at - a.started_at)) / 60.0"
FILTER = (" AND (CAST(:dept AS int) IS NULL OR a.department_id = :dept)"
          " AND (CAST(:doctor AS int) IS NULL OR a.doctor_id = :doctor)")


@dataclass
class Scope:
    start: datetime
    end: datetime
    dept: int | None = None
    doctor: int | None = None

    @classmethod
    def last_days(cls, days: int, dept: int | None = None, doctor: int | None = None) -> "Scope":
        return cls(today_start() - timedelta(days=days - 1), now(), dept, doctor)

    @property
    def params(self) -> dict:
        return {"start": self.start, "end": self.end, "dept": self.dept, "doctor": self.doctor}

    @property
    def previous(self) -> "Scope":
        span = self.end - self.start
        return Scope(self.start - span, self.start, self.dept, self.doctor)

    @property
    def label(self) -> str:
        return f"{self.start:%d %b} – {self.end:%d %b %Y}"


def rows(db: Session, sql: str, **params) -> list[dict]:
    return [dict(r) for r in db.execute(text(sql), params).mappings()]


def scalar(db: Session, sql: str, **params):
    return db.execute(text(sql), params).scalar()


def change(current: float | None, previous: float | None) -> float | None:
    """Percent change vs the previous period; None when there is no baseline."""
    if current is None or not previous:
        return None
    return round((current - previous) / previous * 100, 1)


def headline(value, previous, unit: str = "", lower_is_better: bool = False, digits: int = 1) -> dict:
    v = None if value is None else round(float(value), digits)
    return {"value": v, "unit": unit, "trend": change(value and float(value), previous and float(previous)),
            "lower_is_better": lower_is_better}


# --------------------------------------------------------------------------- overview cards
def avg_wait(db: Session, s: Scope) -> float | None:
    return scalar(db, f"SELECT AVG({WAIT})::float FROM appointments a WHERE a.started_at >= :start "
                      f"AND a.started_at < :end AND a.checked_in_at IS NOT NULL {FILTER}", **s.params)


def bed_summary(db: Session) -> dict:
    counts = {r["status"]: r["n"] for r in rows(db, "SELECT status, COUNT(*) AS n FROM beds GROUP BY status")}
    total = sum(counts.values())
    return {"total": total, **counts,
            "occupancy_rate": round(counts.get("occupied", 0) / total * 100, 1) if total else 0.0}


def emergency_load(db: Session) -> dict:
    """Today's emergency arrivals so far vs the same hours averaged over the last 7 days."""
    t0, current = today_start(), now()
    r = rows(db, """
        SELECT COUNT(*) FILTER (WHERE a.scheduled_at >= :t0)::float AS today,
               (COUNT(*) FILTER (WHERE a.scheduled_at < :t0) / 7.0)::float AS baseline,
               COUNT(*) FILTER (WHERE a.status IN ('waiting', 'checked_in')) AS waiting
        FROM appointments a JOIN departments d ON d.id = a.department_id
        WHERE d.name = 'Emergency' AND a.status <> 'cancelled'
          AND a.scheduled_at >= :t0 - INTERVAL '7 days' AND a.scheduled_at::time <= CAST(:clock AS time)
          AND a.scheduled_at <= :now""", t0=t0, now=current, clock=current.time())[0]
    ratio = (r["today"] / r["baseline"]) if r["baseline"] else 1.0
    level = "High" if ratio >= 1.12 else "Elevated" if ratio >= 1.04 else "Normal" if ratio >= 0.8 else "Low"
    return {"level": level, "ratio": round(ratio, 2), "today": int(r["today"]), "baseline": round(r["baseline"], 1),
            "waiting": r["waiting"], "vs_baseline_pct": round((ratio - 1) * 100, 1)}


def overview(db: Session) -> dict:
    t0, current = today_start(), now()
    today = Scope(t0, t0 + timedelta(days=1))
    yesterday = Scope(t0 - timedelta(days=1), t0)
    count = "SELECT COUNT(*) FROM appointments a WHERE a.scheduled_at >= :start AND a.scheduled_at < :end " \
            "AND a.status <> 'cancelled'" + FILTER
    patients_today, patients_yesterday = scalar(db, count, **today.params), scalar(db, count, **yesterday.params)
    completion = """
        SELECT (COUNT(*) FILTER (WHERE a.status = 'completed') * 100.0 / NULLIF(COUNT(*), 0))::float
        FROM appointments a WHERE a.scheduled_at >= :start AND a.scheduled_at < :end
          AND a.status IN ('completed', 'no_show', 'cancelled')""" + FILTER
    week = Scope(current - timedelta(days=7), current)
    satisfaction = "SELECT AVG(overall)::float FROM feedback WHERE created_at >= :start AND created_at < :end"
    month = Scope(current - timedelta(days=30), current)
    doctors = rows(db, """
        SELECT COUNT(*) FILTER (WHERE is_available AND :hour >= shift_start AND :hour < shift_end) AS on_shift,
               COUNT(*) AS total FROM doctors""", hour=current.hour)[0]
    return {
        "generated_at": current.isoformat(),
        "patients_today": {**headline(patients_today, patients_yesterday, digits=0), "compare": "vs yesterday"},
        "avg_wait_minutes": {**headline(avg_wait(db, Scope(t0, current)), avg_wait(db, yesterday), "min", True, 0),
                             "compare": "vs yesterday"},
        "bed_occupancy": bed_summary(db),
        "emergency_load": emergency_load(db),
        "appointment_completion": {**headline(scalar(db, completion, **week.params),
                                              scalar(db, completion, **week.previous.params), "%"),
                                   "compare": "vs previous 7 days"},
        "patient_satisfaction": {**headline(scalar(db, satisfaction, start=month.start, end=month.end),
                                            scalar(db, satisfaction, start=month.previous.start,
                                                   end=month.previous.end), "/ 5", digits=2),
                                 "compare": "vs previous 30 days"},
        "doctors_available": doctors,
        "waiting_now": scalar(db, "SELECT COUNT(*) FROM appointments WHERE status IN ('waiting', 'checked_in') "
                                  "AND scheduled_at >= :t0", t0=t0),
        "critical_alerts": scalar(db, "SELECT COUNT(*) FROM ai_insights WHERE status = 'active' "
                                      "AND severity IN ('high', 'critical')"),
    }


# --------------------------------------------------------------------------- operations
def patient_flow(db: Session, dept: int | None = None) -> list[dict]:
    """Hourly check-ins, consultations started, discharges, and patients waiting at each hour's end."""
    t0, current = today_start(), now()
    data = rows(db, "SELECT a.checked_in_at, a.started_at, a.completed_at FROM appointments a "
                    "WHERE a.checked_in_at >= :t0 AND a.checked_in_at < :t1"
                    " AND (CAST(:dept AS int) IS NULL OR a.department_id = :dept)",
                t0=t0, t1=t0 + timedelta(days=1), dept=dept)
    out = []
    for hour in range(current.hour + 1):
        lo, hi = t0 + timedelta(hours=hour), min(current, t0 + timedelta(hours=hour + 1))
        out.append({
            "hour": f"{hour:02d}:00",
            "check_in": sum(1 for r in data if lo <= r["checked_in_at"] < hi),
            "consultation": sum(1 for r in data if r["started_at"] and lo <= r["started_at"] < hi),
            "discharge": sum(1 for r in data if r["completed_at"] and lo <= r["completed_at"] < hi),
            "waiting": sum(1 for r in data if r["checked_in_at"] < hi
                           and (r["started_at"] is None or r["started_at"] >= hi)),
        })
    return out


def department_load(db: Session) -> list[dict]:
    t0 = today_start()
    return rows(db, f"""
        SELECT d.id, d.name,
               COUNT(a.id) FILTER (WHERE a.status <> 'cancelled') AS patients,
               COUNT(a.id) FILTER (WHERE a.status IN ('waiting', 'checked_in')) AS waiting,
               COUNT(a.id) FILTER (WHERE a.status = 'in_consultation') AS in_consultation,
               COUNT(a.id) FILTER (WHERE a.status = 'completed') AS completed,
               COUNT(a.id) FILTER (WHERE a.status = 'scheduled') AS scheduled,
               ROUND(AVG({WAIT}) FILTER (WHERE a.started_at IS NOT NULL))::int AS avg_wait
        FROM departments d
        LEFT JOIN appointments a ON a.department_id = d.id AND a.scheduled_at >= :t0 AND a.scheduled_at < :t1
        GROUP BY d.id, d.name ORDER BY d.id""", t0=t0, t1=t0 + timedelta(days=1))


def hourly_heatmap(db: Session, s: Scope) -> list[dict]:
    """Average patients per hour for each weekday (ISO: 1 = Monday)."""
    return rows(db, f"""
        WITH per_day AS (
            SELECT a.scheduled_at::date AS day, EXTRACT(HOUR FROM a.scheduled_at)::int AS hour, COUNT(*) AS n
            FROM appointments a
            WHERE a.scheduled_at >= :start AND a.scheduled_at < :end AND a.status <> 'cancelled' {FILTER}
            GROUP BY 1, 2)
        SELECT EXTRACT(ISODOW FROM day)::int AS weekday, hour, ROUND(AVG(n), 1)::float AS value
        FROM per_day GROUP BY 1, 2 ORDER BY 1, 2""", **s.params)


def wait_distribution(db: Session, s: Scope) -> list[dict]:
    data = rows(db, f"""
        SELECT LEAST(FLOOR(({WAIT}) / 10), 6)::int AS bucket, COUNT(*) AS patients
        FROM appointments a
        WHERE a.started_at >= :start AND a.started_at < :end AND a.checked_in_at IS NOT NULL {FILTER}
        GROUP BY 1 ORDER BY 1""", **s.params)
    by_bucket = {r["bucket"]: r["patients"] for r in data}
    return [{"range": f"{b * 10}–{b * 10 + 10}" if b < 6 else "60+", "patients": by_bucket.get(b, 0)}
            for b in range(7)]


def beds_by_ward(db: Session) -> list[dict]:
    return rows(db, """
        SELECT w.id, w.name,
               COUNT(*) FILTER (WHERE b.status = 'occupied') AS occupied,
               COUNT(*) FILTER (WHERE b.status = 'available') AS available,
               COUNT(*) FILTER (WHERE b.status = 'cleaning') AS cleaning,
               COUNT(*) FILTER (WHERE b.status = 'maintenance') AS maintenance,
               COUNT(*) FILTER (WHERE b.status = 'reserved') AS reserved,
               COUNT(*) AS total
        FROM wards w JOIN beds b ON b.ward_id = w.id GROUP BY w.id, w.name ORDER BY w.id""")


def doctor_utilization(db: Session, s: Scope) -> list[dict]:
    """Scheduled vs consultation hours per doctor. Idle = scheduled - consulting; overtime = work past shift end."""
    return rows(db, f"""
        SELECT doc.id, u.full_name AS doctor, d.name AS department,
               COUNT(*) AS patients,
               ROUND((COUNT(DISTINCT a.scheduled_at::date) * (doc.shift_end - doc.shift_start))::numeric, 1)::float
                   AS scheduled_hours,
               ROUND((SUM({CONSULT}) / 60)::numeric, 1)::float AS consultation_hours,
               ROUND((SUM(GREATEST(0, EXTRACT(EPOCH FROM (a.completed_at - (date_trunc('day', a.scheduled_at)
                     + doc.shift_end * INTERVAL '1 hour'))))) / 3600)::numeric, 1)::float AS overtime_hours,
               ROUND(AVG({CONSULT})::numeric, 1)::float AS avg_consult_minutes
        FROM appointments a
        JOIN doctors doc ON doc.id = a.doctor_id JOIN users u ON u.id = doc.user_id
        JOIN departments d ON d.id = doc.department_id
        WHERE a.status = 'completed' AND a.started_at >= :start AND a.started_at < :end {FILTER}
        GROUP BY doc.id, u.full_name, d.name
        ORDER BY consultation_hours DESC""", **s.params)


def with_utilization(doctors: list[dict]) -> list[dict]:
    for d in doctors:
        scheduled = d["scheduled_hours"] or 0
        d["idle_hours"] = round(max(0.0, scheduled - d["consultation_hours"]), 1)
        d["utilization"] = round(d["consultation_hours"] / scheduled * 100, 1) if scheduled else 0.0
    return doctors


def operations(db: Session, s: Scope) -> dict:
    flow = patient_flow(db, s.dept)
    load = department_load(db)
    waits = wait_distribution(db, s)
    wait_now, wait_prev = avg_wait(db, s), avg_wait(db, s.previous)
    doctors = with_utilization(doctor_utilization(db, s))
    beds = beds_by_ward(db)
    total_patients = sum(d["patients"] for d in load)
    busiest = max(load, key=lambda d: d["patients"]) if load else None
    util = [d["utilization"] for d in doctors]
    return {
        "range": s.label,
        "patient_flow": {"data": flow, "range": "Today, by hour",
                         "metric": {"value": sum(f["check_in"] for f in flow), "unit": "check-ins today"}},
        "department_load": {"data": load, "range": "Today",
                            "metric": {"value": busiest["name"] if busiest else None,
                                       "unit": f"busiest · {busiest['patients']} of {total_patients} patients"
                                       if busiest else ""}},
        "hourly_volume": {"data": hourly_heatmap(db, s), "range": s.label},
        "wait_distribution": {"data": waits, "range": s.label,
                              "metric": headline(wait_now, wait_prev, "min avg", True, 0)},
        "bed_occupancy": {"data": beds, "range": "Right now",
                          "metric": {"value": bed_summary(db)["occupancy_rate"], "unit": "% occupied"}},
        "doctor_utilization": {"data": doctors[:12], "range": s.label,
                               "metric": {"value": round(sum(util) / len(util), 1) if util else None,
                                          "unit": "% avg utilization"}},
    }


# --------------------------------------------------------------------------- patients
def patients(db: Session, s: Scope) -> dict:
    weekly = rows(db, """
        SELECT to_char(date_trunc('week', created_at), 'DD Mon') AS week, COUNT(*) AS patients
        FROM patients WHERE created_at >= :start GROUP BY date_trunc('week', created_at)
        ORDER BY date_trunc('week', created_at)""", start=now() - timedelta(weeks=12))
    ages = rows(db, """
        SELECT band, COUNT(*) AS patients FROM (
            SELECT CASE WHEN age < 18 THEN '0–17' WHEN age < 35 THEN '18–34' WHEN age < 50 THEN '35–49'
                        WHEN age < 65 THEN '50–64' ELSE '65+' END AS band
            FROM (SELECT EXTRACT(YEAR FROM age(date_of_birth))::int AS age FROM patients
                  WHERE CAST(:dept AS int) IS NULL OR primary_department_id = :dept) p) b
        GROUP BY band ORDER BY band""", dept=s.dept)
    gender = rows(db, "SELECT gender AS name, COUNT(*) AS value FROM patients "
                      "WHERE CAST(:dept AS int) IS NULL OR primary_department_id = :dept GROUP BY gender", dept=s.dept)
    by_type = rows(db, f"""
        SELECT a.appointment_type AS name, COUNT(*) AS value FROM appointments a
        WHERE a.scheduled_at >= :start AND a.scheduled_at < :end AND a.status = 'completed' {FILTER}
        GROUP BY 1 ORDER BY 2 DESC""", **s.params)
    status = rows(db, "SELECT status AS name, COUNT(*) AS value FROM patients GROUP BY status")
    visits = "SELECT COUNT(DISTINCT a.patient_id) FROM appointments a WHERE a.status = 'completed' " \
             "AND a.started_at >= :start AND a.started_at < :end" + FILTER
    return {
        "range": s.label,
        "registrations": {"data": weekly, "range": "Last 12 weeks",
                          "metric": {"value": sum(w["patients"] for w in weekly), "unit": "new patients"}},
        "age_bands": {"data": ages, "range": "All registered patients"},
        "gender": {"data": gender, "range": "All registered patients"},
        "visit_types": {"data": by_type, "range": s.label},
        "status": {"data": status, "range": "Right now"},
        "unique_patients_seen": headline(scalar(db, visits, **s.params), scalar(db, visits, **s.previous.params),
                                         "patients seen", digits=0),
    }


# --------------------------------------------------------------------------- appointments
def appointments(db: Session, s: Scope) -> dict:
    past = "a.scheduled_at >= :start AND a.scheduled_at < :end"
    status = rows(db, f"SELECT a.status AS name, COUNT(*) AS value FROM appointments a WHERE {past} {FILTER} "
                      "GROUP BY 1 ORDER BY 2 DESC", **s.params)
    daily = rows(db, f"""
        SELECT to_char(a.scheduled_at::date, 'DD Mon') AS day,
               COUNT(*) FILTER (WHERE a.status = 'completed') AS completed,
               COUNT(*) FILTER (WHERE a.status = 'no_show') AS no_show,
               COUNT(*) FILTER (WHERE a.status = 'cancelled') AS cancelled
        FROM appointments a WHERE {past} {FILTER}
        GROUP BY a.scheduled_at::date ORDER BY a.scheduled_at::date""", **s.params)
    lead = rows(db, f"""
        SELECT bucket AS lead_time, ROUND(AVG(missed) * 100, 1)::float AS no_show_rate, COUNT(*) AS appointments
        FROM (SELECT CASE WHEN days < 1 THEN '1 · Same day' WHEN days < 4 THEN '2 · 1–3 days'
                          WHEN days < 8 THEN '3 · 4–7 days' WHEN days < 15 THEN '4 · 8–14 days'
                          ELSE '5 · 15+ days' END AS bucket,
                     (status = 'no_show')::int AS missed
              FROM (SELECT a.status, EXTRACT(EPOCH FROM (a.scheduled_at - a.created_at)) / 86400 AS days
                    FROM appointments a
                    WHERE {past} AND a.status IN ('completed', 'no_show') AND a.appointment_type <> 'emergency'
                    {FILTER}) x) y
        GROUP BY bucket ORDER BY bucket""", **s.params)
    for r in lead:
        r["lead_time"] = r["lead_time"].split(" · ")[1]
    no_show = f"SELECT (AVG((a.status = 'no_show')::int) * 100)::float FROM appointments a WHERE {past} " \
              f"AND a.status IN ('completed', 'no_show') {FILTER}"
    total = sum(r["value"] for r in status)
    done = next((r["value"] for r in status if r["name"] == "completed"), 0)
    return {
        "range": s.label,
        "status_breakdown": {"data": status, "range": s.label,
                             "metric": {"value": round(done / total * 100, 1) if total else None,
                                        "unit": "% completed"}},
        "daily_outcomes": {"data": daily, "range": s.label, "metric": {"value": total, "unit": "appointments"}},
        "no_show_by_lead_time": {"data": lead, "range": s.label,
                                 "metric": headline(scalar(db, no_show, **s.params),
                                                    scalar(db, no_show, **s.previous.params), "% no-show", True)},
    }


# --------------------------------------------------------------------------- doctors
def doctors(db: Session, s: Scope) -> dict:
    util = with_utilization(doctor_utilization(db, s))
    ratings = {r["doctor_id"]: r["rating"] for r in rows(db, """
        SELECT doctor_id, ROUND(AVG(doctor)::numeric, 2)::float AS rating FROM feedback
        WHERE doctor_id IS NOT NULL AND created_at >= :start GROUP BY doctor_id""", start=s.start)}
    for d in util:
        d["rating"] = ratings.get(d["id"])
    values = [d["utilization"] for d in util]
    return {
        "range": s.label,
        "utilization": {"data": util, "range": s.label,
                        "metric": {"value": round(sum(values) / len(values), 1) if values else None,
                                   "unit": "% avg utilization"}},
        "pace_vs_volume": {"data": [{"doctor": d["doctor"], "patients": d["patients"],
                                     "avg_consult_minutes": d["avg_consult_minutes"],
                                     "department": d["department"]} for d in util], "range": s.label},
    }


# --------------------------------------------------------------------------- beds
def beds(db: Session) -> dict:
    current = now()
    total = scalar(db, "SELECT COUNT(*) FROM beds") or 1
    trend = rows(db, """
        SELECT to_char(day, 'DD Mon') AS day,
               ROUND((COUNT(ba.id) * 100.0 / :total)::numeric, 1)::float AS occupancy
        FROM generate_series(CAST(:start AS timestamp), CAST(:end AS timestamp), INTERVAL '1 day') AS day
        LEFT JOIN bed_assignments ba ON ba.assigned_at <= day AND (ba.released_at IS NULL OR ba.released_at > day)
        GROUP BY day ORDER BY day""", start=current - timedelta(days=29), end=current, total=total)
    wards = rows(db, """
        SELECT w.name AS ward,
               ROUND((AVG(EXTRACT(EPOCH FROM (ba.released_at - ba.assigned_at)) / 86400))::numeric, 1)::float
                   AS avg_stay_days,
               COUNT(ba.id) AS admissions,
               ROUND((COUNT(ba.id)::numeric / NULLIF(COUNT(DISTINCT b.id), 0)), 1)::float AS turnover
        FROM wards w JOIN beds b ON b.ward_id = w.id
        LEFT JOIN bed_assignments ba ON ba.bed_id = b.id AND ba.assigned_at >= :start AND ba.released_at IS NOT NULL
        GROUP BY w.id, w.name ORDER BY w.id""", start=current - timedelta(days=30))
    discharge = rows(db, """
        SELECT to_char(released_at::date, 'DD Mon') AS day,
               ROUND((AVG(EXTRACT(EPOCH FROM (released_at - discharge_ordered_at)) / 3600))::numeric, 2)::float
                   AS hours
        FROM bed_assignments WHERE released_at >= :start AND discharge_ordered_at IS NOT NULL
        GROUP BY released_at::date ORDER BY released_at::date""", start=current - timedelta(days=21))
    summary = bed_summary(db)
    stays = [w["avg_stay_days"] for w in wards if w["avg_stay_days"]]
    return {
        "range": "Last 30 days",
        "summary": summary,
        "by_ward": {"data": beds_by_ward(db), "range": "Right now",
                    "metric": {"value": summary["occupancy_rate"], "unit": "% occupied"}},
        "occupancy_trend": {"data": trend, "range": "Last 30 days",
                            "metric": headline(trend[-1]["occupancy"] if trend else None,
                                               trend[-8]["occupancy"] if len(trend) > 7 else None, "%")},
        "ward_stats": {"data": wards, "range": "Last 30 days",
                       "metric": {"value": round(sum(stays) / len(stays), 1) if stays else None,
                                  "unit": "days avg stay"}},
        "discharge_processing": {"data": discharge, "range": "Last 21 days",
                                 "metric": {"value": discharge[-1]["hours"] if discharge else None,
                                            "unit": "h order-to-release"}},
    }


# --------------------------------------------------------------------------- patient experience
DIMENSIONS = ("overall", "wait_time", "staff", "doctor", "cleanliness", "communication", "appointment_experience")


def experience(db: Session, s: Scope) -> dict:
    where = "f.created_at >= :start AND f.created_at < :end AND (CAST(:dept AS int) IS NULL OR f.department_id = :dept)"
    p = {"start": s.start, "end": s.end, "dept": s.dept}
    prev = {"start": s.previous.start, "end": s.previous.end, "dept": s.dept}
    averages = f"SELECT {', '.join(f'ROUND(AVG({d})::numeric, 2)::float AS {d}' for d in DIMENSIONS)}, " \
               f"COUNT(*) AS responses FROM feedback f WHERE {where}"
    current, previous = rows(db, averages, **p)[0], rows(db, averages, **prev)[0]
    nps_sql = f"""
        SELECT COUNT(*) FILTER (WHERE nps >= 9) AS promoters, COUNT(*) FILTER (WHERE nps BETWEEN 7 AND 8) AS passives,
               COUNT(*) FILTER (WHERE nps <= 6) AS detractors, COUNT(*) AS total FROM feedback f WHERE {where}"""

    def nps(params: dict) -> dict:
        r = rows(db, nps_sql, **params)[0]
        r["score"] = round((r["promoters"] - r["detractors"]) / r["total"] * 100) if r["total"] else None
        return r

    nps_now, nps_prev = nps(p), nps(prev)
    sentiment = rows(db, f"SELECT sentiment AS name, COUNT(*) AS value FROM feedback f WHERE {where} GROUP BY 1", **p)
    total = sum(r["value"] for r in sentiment) or 1
    for r in sentiment:
        r["percent"] = round(r["value"] / total * 100)
    categories = rows(db, f"""
        SELECT category, COUNT(*) AS total, COUNT(*) FILTER (WHERE sentiment = 'negative') AS negative,
               COUNT(*) FILTER (WHERE sentiment = 'positive') AS positive
        FROM feedback f WHERE {where} GROUP BY 1 ORDER BY negative DESC, total DESC""", **p)
    weekly = rows(db, f"""
        SELECT to_char(date_trunc('week', f.created_at), 'DD Mon') AS week,
               ROUND(AVG(overall)::numeric, 2)::float AS satisfaction, COUNT(*) AS responses,
               COUNT(*) FILTER (WHERE sentiment = 'negative') AS negative
        FROM feedback f WHERE {where} GROUP BY date_trunc('week', f.created_at)
        ORDER BY date_trunc('week', f.created_at)""", **p)
    themes = rows(db, f"""
        SELECT theme, category, COUNT(*) AS mentions,
               COUNT(*) FILTER (WHERE urgency = 'high') AS high_urgency
        FROM feedback f WHERE {where} AND sentiment = 'negative'
        GROUP BY theme, category HAVING COUNT(*) >= 2 ORDER BY mentions DESC LIMIT 6""", **p)
    complaints = rows(db, """
        SELECT status AS name, COUNT(*) AS value FROM complaints c
        WHERE c.created_at >= :start AND c.created_at < :end
          AND (CAST(:dept AS int) IS NULL OR c.department_id = :dept) GROUP BY 1""", **p)
    complaint_total = sum(c["value"] for c in complaints)
    previous_complaints = scalar(db, "SELECT COUNT(*) FROM complaints c WHERE c.created_at >= :start AND "
                                     "c.created_at < :end AND (CAST(:dept AS int) IS NULL OR c.department_id = :dept)",
                                 **prev)
    return {
        "range": s.label,
        "responses": current["responses"],
        "dimensions": {"data": [{"dimension": d.replace("_", " ").title(), "score": current[d],
                                 "previous": previous[d]} for d in DIMENSIONS if d != "overall"],
                       "range": s.label,
                       "metric": headline(current["overall"], previous["overall"], "/ 5 overall", digits=2)},
        "nps": {**nps_now, "range": s.label,
                "trend": None if nps_now["score"] is None or nps_prev["score"] is None
                else nps_now["score"] - nps_prev["score"]},
        "sentiment": {"data": sentiment, "range": s.label},
        "categories": {"data": categories, "range": s.label},
        "weekly": {"data": weekly, "range": s.label},
        "themes": themes,
        "complaints": {"data": complaints, "range": s.label,
                       "metric": headline(complaint_total, previous_complaints, "complaints", True, 0)},
    }
