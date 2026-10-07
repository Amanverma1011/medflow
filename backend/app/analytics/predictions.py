"""Explainable demo predictions. Each returns a value, a confidence and the factors behind it.

These are deliberately simple, inspectable statistical models fitted to the
hospital's own history on every call. They are estimates, never guarantees.
"""
import math
import statistics
from collections import defaultdict
from datetime import timedelta

from sqlalchemy.orm import Session

from app.analytics.metrics import bed_summary, rows, scalar
from app.core.clock import now, today_start

LABEL = "AI-generated estimate, not a guaranteed outcome"
HISTORY_DAYS = 28
NO_SHOW_ALERT = 0.2


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _logit(p: float) -> float:
    return math.log(p / (1 - p))


# --------------------------------------------------------------------------- patient volume
def volume_forecast(db: Session, dept: int | None = None) -> dict:
    """Seasonal-naive forecast: mean volume for the same weekday/hour, scaled by the recent trend."""
    t0, current = today_start(), now()
    history = rows(db, """
        SELECT a.scheduled_at::date AS day, EXTRACT(HOUR FROM a.scheduled_at)::int AS hour, COUNT(*) AS n
        FROM appointments a
        WHERE a.scheduled_at >= :start AND a.scheduled_at < :t0 AND a.status NOT IN ('cancelled', 'no_show')
          AND (CAST(:dept AS int) IS NULL OR a.department_id = :dept)
        GROUP BY 1, 2""", start=t0 - timedelta(days=HISTORY_DAYS), t0=t0, dept=dept)
    daily: dict = defaultdict(int)
    hourly: dict = defaultdict(list)  # (weekday, hour) -> counts
    for r in history:
        daily[r["day"]] += r["n"]
        hourly[(r["day"].weekday(), r["hour"])].append(r["n"])
    by_weekday: dict = defaultdict(list)
    for day, n in daily.items():
        by_weekday[day.weekday()].append(n)
    days = sorted(daily)
    recent = sum(daily[d] for d in days[-7:])
    prior = sum(daily[d] for d in days[-14:-7])
    trend = _clip(recent / prior, 0.85, 1.2) if prior else 1.0

    def day_estimate(weekday: int) -> float:
        return statistics.mean(by_weekday[weekday]) * trend if by_weekday[weekday] else 0.0

    next_hour = (current + timedelta(hours=1))
    hour_values = hourly.get((next_hour.weekday(), next_hour.hour), [])
    week = [{"day": f"{(t0 + timedelta(days=i)):%a %d}", "predicted": round(day_estimate((t0 + timedelta(days=i))
                                                                                         .weekday()))}
            for i in range(1, 8)]
    tomorrow = (t0 + timedelta(days=1)).weekday()
    samples = by_weekday[tomorrow]
    spread = statistics.pstdev(samples) / statistics.mean(samples) if len(samples) > 1 and statistics.mean(samples) \
        else 0.3
    confidence = round(_clip(0.92 - spread * 1.5, 0.5, 0.92), 2)
    actual = [{"day": f"{d:%a %d}", "actual": daily[d]} for d in days[-7:]]
    return {
        "kind": "patient_volume", "label": LABEL, "confidence": confidence,
        "next_hour": round(statistics.mean(hour_values) * trend) if hour_values else 0,
        "next_day": round(day_estimate(tomorrow)),
        "next_week": sum(w["predicted"] for w in week),
        "series": actual + week,
        "factors": [
            {"name": "Same-weekday history", "detail": f"mean of the last {len(samples)} "
                                                       f"{(t0 + timedelta(days=1)):%A}s"},
            {"name": "Recent trend", "detail": f"last 7 days are {(trend - 1) * 100:+.0f}% vs the 7 before"},
            {"name": "Day-to-day variability", "detail": f"±{spread * 100:.0f}% around the weekday mean"},
        ],
    }


# --------------------------------------------------------------------------- no-show risk
_FEATURES = ("lead", "daypart", "kind", "history")
_FEATURE_NAMES = {"lead": "Appointment lead time", "daypart": "Time of day", "kind": "Appointment type",
                  "history": "Previous attendance"}
_NO_SHOW_SQL = """
    SELECT a.id, a.status, a.scheduled_at, a.patient_id, a.doctor_id,
           CASE WHEN a.scheduled_at - a.created_at < INTERVAL '1 day' THEN 'same day'
                WHEN a.scheduled_at - a.created_at < INTERVAL '4 days' THEN '1-3 days ahead'
                WHEN a.scheduled_at - a.created_at < INTERVAL '8 days' THEN '4-7 days ahead'
                ELSE 'more than a week ahead' END AS lead,
           CASE WHEN EXTRACT(HOUR FROM a.scheduled_at) < 12 THEN 'morning'
                WHEN EXTRACT(HOUR FROM a.scheduled_at) < 16 THEN 'afternoon' ELSE 'late afternoon' END AS daypart,
           a.appointment_type AS kind,
           CASE COALESCE(SUM((a.status = 'no_show')::int) OVER (
                    PARTITION BY a.patient_id ORDER BY a.scheduled_at
                    ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING), 0)
                WHEN 0 THEN 'no missed visits' WHEN 1 THEN '1 missed visit' ELSE '2+ missed visits' END AS history
    FROM appointments a
    WHERE a.appointment_type <> 'emergency' AND a.status IN ('completed', 'no_show', 'scheduled')
      AND a.scheduled_at >= :start AND a.scheduled_at < :end"""


def no_show_risk(db: Session, hours_ahead: int = 48) -> dict:
    """Naive-Bayes log-odds model over four categorical features, fitted to past attendance."""
    current = now()
    data = rows(db, _NO_SHOW_SQL, start=current - timedelta(days=60), end=current + timedelta(hours=hours_ahead))
    past = [r for r in data if r["status"] != "scheduled"]
    upcoming = [r for r in data if r["status"] == "scheduled" and r["scheduled_at"] > current]
    if len(past) < 50:
        return {"kind": "no_show", "label": LABEL, "base_rate": None, "elevated": 0, "appointments": [],
                "confidence": 0.0, "factors": []}
    base = _clip(sum(r["status"] == "no_show" for r in past) / len(past), 0.005, 0.5)
    weights: dict[tuple[str, str], float] = {}
    for feature in _FEATURES:
        groups: dict[str, list[int]] = defaultdict(list)
        for r in past:
            groups[r[feature]].append(r["status"] == "no_show")
        for value, outcomes in groups.items():
            rate = (sum(outcomes) + 5 * base) / (len(outcomes) + 5)  # shrink small groups toward the base rate
            weights[(feature, value)] = _logit(_clip(rate, 0.001, 0.999)) - _logit(base)

    scored = []
    for r in upcoming:
        contributions = {f: weights.get((f, r[f]), 0.0) for f in _FEATURES}
        probability = 1 / (1 + math.exp(-(_logit(base) + sum(contributions.values()))))
        if probability >= NO_SHOW_ALERT:
            top = sorted(contributions.items(), key=lambda kv: -kv[1])[:3]
            scored.append({"appointment_id": r["id"], "patient_id": r["patient_id"], "doctor_id": r["doctor_id"],
                           "scheduled_at": r["scheduled_at"].isoformat(), "probability": round(probability, 2),
                           "factors": [{"name": _FEATURE_NAMES[f], "detail": r[f], "weight": round(w, 2)}
                                       for f, w in top if w > 0]})
    scored.sort(key=lambda r: -r["probability"])
    strongest = sorted(weights.items(), key=lambda kv: -kv[1])[:3]
    return {
        "kind": "no_show", "label": LABEL, "base_rate": round(base, 3), "upcoming": len(upcoming),
        "elevated": len(scored), "threshold": NO_SHOW_ALERT, "appointments": scored[:25],
        "confidence": round(_clip(0.55 + len(past) / 20000, 0.55, 0.85), 2),
        "factors": [{"name": _FEATURE_NAMES[f], "detail": f"“{v}” raises the odds", "weight": round(w, 2)}
                    for (f, v), w in strongest if w > 0],
    }


# --------------------------------------------------------------------------- wait time
def wait_time_predictions(db: Session) -> list[dict]:
    """Per department: blend the live queue against the historical wait for this hour of day."""
    current = now()
    live = rows(db, """
        SELECT d.id, d.name,
               (SELECT COUNT(*) FROM appointments a WHERE a.department_id = d.id AND a.scheduled_at >= :t0
                    AND a.status IN ('waiting', 'checked_in')) AS waiting,
               (SELECT COUNT(*) FROM doctors doc WHERE doc.department_id = d.id AND doc.is_available
                    AND :hour >= doc.shift_start AND :hour < doc.shift_end) AS doctors_on_shift,
               (SELECT AVG(doc.avg_consult_minutes)::float FROM doctors doc WHERE doc.department_id = d.id)
                   AS consult_minutes
        FROM departments d ORDER BY d.id""", t0=today_start(), hour=current.hour)
    historical = {r["department_id"]: r for r in rows(db, """
        SELECT a.department_id, AVG(EXTRACT(EPOCH FROM (a.started_at - a.checked_in_at)) / 60)::float AS wait,
               COUNT(*) AS samples
        FROM appointments a
        WHERE a.started_at >= :start AND a.checked_in_at IS NOT NULL
          AND EXTRACT(HOUR FROM a.scheduled_at) = :hour
        GROUP BY a.department_id""", start=current - timedelta(days=HISTORY_DAYS), hour=current.hour)}
    out = []
    for d in live:
        hist = historical.get(d["id"], {"wait": None, "samples": 0})
        doctors = d["doctors_on_shift"]
        queue_based = d["waiting"] * d["consult_minutes"] / max(1, doctors)
        if hist["wait"] is None:
            value, weight = queue_based, 1.0
        else:
            weight = 0.6 if d["waiting"] else 0.3  # an empty queue says little; lean on history
            value = weight * queue_based + (1 - weight) * hist["wait"]
        out.append({
            "kind": "wait_time", "label": LABEL, "department_id": d["id"], "department": d["name"],
            "value": round(value), "unit": "min",
            "confidence": round(_clip(0.6 + min(hist["samples"], 200) / 800 - (0.1 if doctors == 0 else 0), 0.5, 0.88),
                                2),
            "factors": [
                {"name": "Queue length", "detail": f"{d['waiting']} waiting now"},
                {"name": "Doctor availability", "detail": f"{doctors} on shift · ~{d['consult_minutes']:.0f} min "
                                                          "per consultation"},
                {"name": "Historical department load",
                 "detail": f"{hist['wait']:.0f} min typical at {current:%H}:00 over {HISTORY_DAYS} days"
                 if hist["wait"] is not None else "no history for this hour"},
            ],
        })
    return out


# --------------------------------------------------------------------------- bed occupancy
def bed_forecast(db: Session, hours: int = 6) -> list[dict]:
    """Per ward: current occupancy - expected discharges + expected admissions over the horizon."""
    current = now()
    wards = rows(db, """
        SELECT w.id, w.name, COUNT(DISTINCT b.id) AS beds,
               COUNT(DISTINCT b.id) FILTER (WHERE b.status = 'occupied') AS occupied,
               COUNT(DISTINCT ba.id) FILTER (WHERE ba.released_at IS NULL AND ba.expected_discharge_at <= :horizon)
                   AS due_out,
               COUNT(DISTINCT ba.id) FILTER (WHERE ba.assigned_at >= :start) AS admissions_14d
        FROM wards w JOIN beds b ON b.ward_id = w.id
        LEFT JOIN bed_assignments ba ON ba.bed_id = b.id
        GROUP BY w.id, w.name ORDER BY w.id""",
                 horizon=current + timedelta(hours=hours), start=current - timedelta(days=14))
    out = []
    for w in wards:
        admissions = w["admissions_14d"] / (14 * 24) * hours
        discharges = w["due_out"] * 0.7  # not every planned discharge happens on time
        free = w["beds"] - w["occupied"]
        predicted = _clip(w["occupied"] - discharges + min(admissions, free + discharges), 0, w["beds"])
        now_pct, pred_pct = w["occupied"] / w["beds"] * 100, predicted / w["beds"] * 100
        out.append({
            "kind": "bed_occupancy", "label": LABEL, "ward_id": w["id"], "ward": w["name"], "horizon_hours": hours,
            "current": round(now_pct), "value": round(pred_pct), "unit": "%",
            "confidence": round(_clip(0.85 - abs(pred_pct - now_pct) / 100, 0.6, 0.85), 2),
            "factors": [
                {"name": "Current occupancy", "detail": f"{w['occupied']} of {w['beds']} beds"},
                {"name": "Expected discharges", "detail": f"{w['due_out']} due within {hours} h "
                                                          "(70% assumed on time)"},
                {"name": "Recent admission rate", "detail": f"~{admissions:.1f} admissions per {hours} h "
                                                            "(14-day average)"},
            ],
        })
    return out


def all_predictions(db: Session) -> dict:
    return {
        "label": LABEL,
        "generated_at": now().isoformat(),
        "patient_volume": volume_forecast(db),
        "no_show": no_show_risk(db),
        "wait_time": wait_time_predictions(db),
        "bed_occupancy": bed_forecast(db),
        "beds": bed_summary(db),
        "history_days": HISTORY_DAYS,
        "appointments_in_history": scalar(db, "SELECT COUNT(*) FROM appointments WHERE scheduled_at >= :s",
                                          s=now() - timedelta(days=HISTORY_DAYS)),
    }
