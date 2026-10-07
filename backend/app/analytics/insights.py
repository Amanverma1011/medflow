"""InsightEngine: rule-based detectors over live hospital data.

Each detector returns evidence-backed *recommendations* for a human to review.
Nothing here acts on the hospital autonomously.
"""
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.analytics import predictions
from app.analytics.metrics import (Scope, avg_wait, doctor_utilization, emergency_load, rows, scalar,
                                   with_utilization)
from app.core.clock import now, today_start
from app.models import AIInsight, AIPrediction
from app.services.notifications import emit, notify_roles

ICU_ALERT, DISCHARGE_ALERT, UTILIZATION_ALERT = 85, 0.15, 95
PEAK_RATIO = 1.3  # an hour is "unusually busy" at 1.3x the average hourly arrivals
PEAK_SHOULDER = 0.82  # neighbouring hours join the surge at 82% of the busiest hour


def _confidence(effect: float, full_at: float, floor: float = 0.6, ceiling: float = 0.93) -> float:
    """Confidence grows with effect size, saturating at `full_at`."""
    return round(floor + (ceiling - floor) * max(0.0, min(1.0, effect / full_at)), 2)


class InsightEngine:
    def __init__(self, db: Session):
        self.db = db
        self.now = now()

    # ------------------------------------------------------------------ detectors
    def emergency_inflow(self) -> dict | None:
        hourly = rows(self.db, """
            SELECT EXTRACT(HOUR FROM a.scheduled_at)::int AS hour, COUNT(*) / 7.0 AS arrivals,
                   AVG(EXTRACT(EPOCH FROM (a.started_at - a.checked_in_at)) / 60)::float AS wait
            FROM appointments a JOIN departments d ON d.id = a.department_id
            WHERE d.name = 'Emergency' AND a.status = 'completed'
              AND a.scheduled_at >= :start AND a.scheduled_at < :end
            GROUP BY 1 ORDER BY 1""", start=today_start() - timedelta(days=7), end=today_start())
        if len(hourly) < 6:
            return None
        mean = sum(float(h["arrivals"]) for h in hourly) / len(hourly)
        busiest = max(hourly, key=lambda h: h["arrivals"])
        if float(busiest["arrivals"]) < PEAK_RATIO * mean:
            return None
        # The surge is the unbroken run of hours around the busiest one that stay close to its level.
        floor = max(PEAK_RATIO * mean, PEAK_SHOULDER * float(busiest["arrivals"]))
        by_hour = {h["hour"]: h for h in hourly}
        hours = [busiest["hour"]]
        while by_hour.get(hours[0] - 1) and float(by_hour[hours[0] - 1]["arrivals"]) >= floor:
            hours.insert(0, hours[0] - 1)
        while by_hour.get(hours[-1] + 1) and float(by_hour[hours[-1] + 1]["arrivals"]) >= floor:
            hours.append(hours[-1] + 1)
        peak = [by_hour[h] for h in hours]
        calm = [h for h in hourly if h["hour"] not in hours and h["wait"]]
        if not calm:
            return None
        start, end = peak[0]["hour"], peak[-1]["hour"] + 1
        peak_wait = sum(h["wait"] for h in peak) / len(peak)
        calm_wait = sum(h["wait"] for h in calm) / len(calm)
        uplift = (peak_wait / calm_wait - 1) * 100
        if uplift < 8:
            return None
        ratio = sum(float(h["arrivals"]) for h in peak) / len(peak) / mean
        load = emergency_load(self.db)
        dept = scalar(self.db, "SELECT id FROM departments WHERE name = 'Emergency'")
        return {
            "key": "emergency_inflow", "category": "patient_volume", "department_id": dept,
            "severity": "high" if uplift >= 20 or load["level"] == "High" else "medium",
            "title": "Emergency Department inflow surge",
            "description": f"Emergency Department is experiencing unusually high patient inflow between "
                           f"{start:02d}:00 and {end:02d}:00 ({ratio:.1f}× the hourly average over the last 7 days).",
            "impact": f"+{uplift:.0f}% waiting time during this window",
            "recommendation": "Consider reallocating 1 available physician and 2 nursing staff to the Emergency "
                              f"Department between {start:02d}:00 and {end:02d}:00.",
            "confidence": _confidence(ratio - 1, 0.8),
            "evidence": [
                {"label": "Peak window", "value": f"{start:02d}:00–{end:02d}:00"},
                {"label": "Arrivals per hour (peak vs average)", "value": f"{ratio * mean:.1f} vs {mean:.1f}"},
                {"label": "Average wait (peak vs other hours)", "value": f"{peak_wait:.0f} vs {calm_wait:.0f} min"},
                {"label": "Today vs 7-day baseline", "value": f"{load['vs_baseline_pct']:+.0f}%"},
            ],
        }

    def icu_capacity(self) -> dict | None:
        icu = next((w for w in predictions.bed_forecast(self.db, 6) if w["ward"] == "ICU"), None)
        if not icu or max(icu["current"], icu["value"]) < ICU_ALERT:
            return None
        return {
            "key": "icu_capacity", "category": "bed_occupancy", "department_id": None,
            "severity": "critical" if max(icu["current"], icu["value"]) >= 95 else "high",
            "title": "ICU bed bottleneck",
            "description": f"ICU occupancy is at {icu['current']}% and is predicted to be {icu['value']}% "
                           "within 6 hours.",
            "impact": "Limited capacity for new critical admissions",
            "recommendation": "Review ICU patients who are ready for step-down and confirm planned discharges "
                              "with the bed manager.",
            "confidence": icu["confidence"],
            "evidence": [{"label": f["name"], "value": f["detail"]} for f in icu["factors"]],
        }

    def no_show_risk(self) -> dict | None:
        risk = predictions.no_show_risk(self.db)
        if risk["elevated"] < 5:
            return None
        return {
            "key": "no_show_risk", "category": "appointments", "department_id": None, "severity": "medium",
            "title": "Appointment no-show risk",
            "description": f"{risk['elevated']} of {risk['upcoming']} appointments in the next 48 hours have an "
                           f"elevated no-show probability (≥ {risk['threshold'] * 100:.0f}%).",
            "impact": f"Baseline no-show rate is {risk['base_rate'] * 100:.1f}%",
            "recommendation": "Send reminder notifications to these patients and offer rescheduling.",
            "confidence": risk["confidence"],
            "evidence": [{"label": f["name"], "value": f["detail"]} for f in risk["factors"]],
        }

    def discharge_delay(self) -> dict | None:
        sql = ("SELECT AVG(EXTRACT(EPOCH FROM (released_at - discharge_ordered_at)) / 3600)::float "
               "FROM bed_assignments WHERE released_at >= :start AND released_at < :end "
               "AND discharge_ordered_at IS NOT NULL")
        recent = scalar(self.db, sql, start=self.now - timedelta(days=7), end=self.now)
        baseline = scalar(self.db, sql, start=self.now - timedelta(days=28), end=self.now - timedelta(days=7))
        if not recent or not baseline or recent / baseline - 1 < DISCHARGE_ALERT:
            return None
        increase = recent / baseline - 1
        return {
            "key": "discharge_delay", "category": "discharge", "department_id": None,
            "severity": "high" if increase >= 0.3 else "medium",
            "title": "Discharge bottleneck",
            "description": f"Average discharge processing time increased by {increase * 100:.0f}% over the last "
                           "7 days compared with the previous three weeks.",
            "impact": "Beds are released later, delaying new admissions",
            "recommendation": "Likely contributing factor: delayed documentation. Review discharge-summary "
                              "turnaround with ward leads.",
            "confidence": _confidence(increase, 0.4),
            "evidence": [{"label": "Order-to-release, last 7 days", "value": f"{recent:.1f} h"},
                         {"label": "Order-to-release, prior 3 weeks", "value": f"{baseline:.1f} h"}],
        }

    def wait_outlier(self) -> dict | None:
        scope = Scope(self.now - timedelta(days=7), self.now)
        hospital = avg_wait(self.db, scope)
        depts = rows(self.db, """
            SELECT d.id, d.name, AVG(EXTRACT(EPOCH FROM (a.started_at - a.checked_in_at)) / 60)::float AS wait,
                   COUNT(*) AS n
            FROM appointments a JOIN departments d ON d.id = a.department_id
            WHERE a.started_at >= :start AND a.checked_in_at IS NOT NULL AND d.name <> 'Emergency'
            GROUP BY d.id, d.name HAVING COUNT(*) >= 30 ORDER BY wait DESC""", start=scope.start)
        if not depts or not hospital or depts[0]["wait"] < hospital * 1.15:
            return None
        worst = depts[0]
        return {
            "key": "wait_outlier", "category": "wait_time", "department_id": worst["id"], "severity": "medium",
            "title": f"{worst['name']} wait time above hospital average",
            "description": f"{worst['name']} averaged {worst['wait']:.0f} minutes of waiting over the last 7 days, "
                           f"{worst['wait'] - hospital:.0f} minutes above the hospital average.",
            "impact": "Longer waits correlate with lower wait-time ratings",
            "recommendation": f"Review {worst['name']} clinic templates for the late-morning peak and consider "
                              "staggering follow-up appointments.",
            "confidence": _confidence(worst["wait"] / hospital - 1, 0.5),
            "evidence": [{"label": f"{worst['name']} average wait", "value": f"{worst['wait']:.0f} min"},
                         {"label": "Hospital average wait", "value": f"{hospital:.0f} min"},
                         {"label": "Consultations analysed", "value": str(worst["n"])}],
        }

    def satisfaction_theme(self) -> dict | None:
        themes = rows(self.db, """
            SELECT theme, category, department_id, COUNT(*) AS n FROM feedback
            WHERE sentiment = 'negative' AND created_at >= :start
            GROUP BY theme, category, department_id ORDER BY n DESC LIMIT 1""", start=self.now - timedelta(days=14))
        total = scalar(self.db, "SELECT COUNT(*) FROM feedback WHERE created_at >= :start",
                       start=self.now - timedelta(days=14))
        if not themes or themes[0]["n"] < 4:
            return None
        top = themes[0]
        return {
            "key": "satisfaction_theme", "category": "patient_experience", "department_id": top["department_id"],
            "severity": "medium", "title": "Recurring patient complaint",
            "description": f"“{top['theme']}” appeared in {top['n']} negative feedback entries in the last 14 days.",
            "impact": f"{top['n'] / total * 100:.0f}% of all feedback in the period",
            "recommendation": "Share the feedback with the department lead and agree one corrective action for "
                              "the coming week.",
            "confidence": _confidence(top["n"], 12),
            "evidence": [{"label": "Category", "value": top["category"].replace("_", " ")},
                         {"label": "Negative mentions (14 days)", "value": str(top["n"])},
                         {"label": "Feedback analysed", "value": str(total)}],
        }

    def staffing_pressure(self) -> dict | None:
        doctors = with_utilization(doctor_utilization(self.db, Scope(self.now - timedelta(days=7), self.now)))
        over = [d for d in doctors if d["utilization"] >= UTILIZATION_ALERT or d["overtime_hours"] >= 3]
        if len(over) < 2:
            return None
        over.sort(key=lambda d: -d["overtime_hours"])
        return {
            "key": "staffing_pressure", "category": "staffing", "department_id": None, "severity": "low",
            "title": "Doctors working beyond scheduled hours",
            "description": f"{len(over)} doctors ran at or above {UTILIZATION_ALERT}% utilization or logged "
                           "3+ hours of overtime in the last 7 days.",
            "impact": "Sustained overtime raises fatigue and delay risk",
            "recommendation": "Review clinic templates for these doctors and rebalance follow-up load.",
            "confidence": _confidence(len(over), 8),
            "evidence": [{"label": d["doctor"], "value": f"{d['utilization']:.0f}% utilized · "
                                                         f"{d['overtime_hours']:.1f} h overtime"}
                         for d in over[:4]],
        }

    # ------------------------------------------------------------------ orchestration
    def generate(self) -> list[dict]:
        detectors = (self.emergency_inflow, self.icu_capacity, self.no_show_risk, self.discharge_delay,
                     self.wait_outlier, self.satisfaction_theme, self.staffing_pressure)
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        return sorted((i for i in (d() for d in detectors) if i), key=lambda i: order[i["severity"]])

    def refresh(self, notify: bool = True) -> list[AIInsight]:
        """Recompute insights. Dismissed insights stay dismissed until their rule stops firing."""
        existing = {i.key: i for i in self.db.scalars(select(AIInsight))}
        generated = self.generate()
        self.db.execute(delete(AIInsight).where(AIInsight.status == "active"))
        fired = {g["key"] for g in generated}
        self.db.execute(delete(AIInsight).where(AIInsight.status == "dismissed", AIInsight.key.notin_(fired)))
        for g in generated:
            previous = existing.get(g["key"])
            if previous and previous.status == "dismissed":
                continue
            self.db.add(AIInsight(**g))
            if notify and previous is None and g["severity"] in {"high", "critical"}:
                notify_roles(self.db, ("administrator", "super_admin"), "operational_alert", g["title"],
                             g["description"], "critical" if g["severity"] == "critical" else "warning",
                             "/admin/ai-insights")
        self._snapshot_predictions()
        emit(self.db, "insight.updated")
        self.db.commit()
        return list(self.db.scalars(select(AIInsight).where(AIInsight.status == "active")))

    def _snapshot_predictions(self) -> None:
        """Keep a history of what was predicted, so forecasts can later be compared with outcomes."""
        volume = predictions.volume_forecast(self.db)
        self.db.add(AIPrediction(kind="patient_volume", target="hospital", horizon="next_day",
                                 value=volume["next_day"], unit="patients", confidence=volume["confidence"],
                                 factors=volume["factors"]))
        for w in predictions.bed_forecast(self.db, 6):
            self.db.add(AIPrediction(kind="bed_occupancy", target=w["ward"], horizon="6h", value=w["value"],
                                     unit="%", confidence=w["confidence"], factors=w["factors"]))
        for d in predictions.wait_time_predictions(self.db):
            self.db.add(AIPrediction(kind="wait_time", target=d["department"], horizon="now", value=d["value"],
                                     unit="min", confidence=d["confidence"], factors=d["factors"]))
