from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics import copilot, metrics, predictions
from app.analytics.insights import InsightEngine
from app.analytics.metrics import Scope, rows
from app.core.clock import now, today_start
from app.core.db import get_db
from app.core.errors import AppError
from app.core.ratelimit import rate_limit
from app.models import AIInsight, Patient, User
from app.repositories import appointments as appointment_repo
from app.schemas.requests import QuestionRequest
from app.security import audit
from app.security.auth import doctor_of, require
from app.services import queue as queue_service

router = APIRouter(tags=["analytics"])


def scope(days: int = Query(14, ge=1, le=90), department_id: int | None = Query(None, ge=1),
          doctor_id: int | None = Query(None, ge=1)) -> Scope:
    return Scope.last_days(days, department_id, doctor_id)


# ------------------------------------------------------------------------------- dashboards
@router.get("/analytics/overview")
def overview(_: User = Depends(require("analytics:read")), db: Session = Depends(get_db)):
    return metrics.overview(db)


@router.get("/analytics/operations")
def operations(s: Scope = Depends(scope), _: User = Depends(require("analytics:read")),
               db: Session = Depends(get_db)):
    return metrics.operations(db, s)


@router.get("/analytics/patients")
def patients(s: Scope = Depends(scope), _: User = Depends(require("analytics:read")), db: Session = Depends(get_db)):
    return metrics.patients(db, s)


@router.get("/analytics/appointments")
def appointments(s: Scope = Depends(scope), _: User = Depends(require("analytics:read")),
                 db: Session = Depends(get_db)):
    return metrics.appointments(db, s)


@router.get("/analytics/doctors")
def doctors(s: Scope = Depends(scope), _: User = Depends(require("analytics:read")), db: Session = Depends(get_db)):
    return metrics.doctors(db, s)


@router.get("/analytics/beds")
def beds(_: User = Depends(require("analytics:read")), db: Session = Depends(get_db)):
    return metrics.beds(db)


@router.get("/analytics/patient-experience")
def patient_experience(s: Scope = Depends(scope), _: User = Depends(require("experience:read")),
                       db: Session = Depends(get_db)):
    return metrics.experience(db, s)


# ------------------------------------------------------------------------------- AI insights & predictions
def _insight(i: AIInsight) -> dict:
    return {"id": i.id, "key": i.key, "title": i.title, "description": i.description, "severity": i.severity,
            "category": i.category, "confidence": i.confidence, "impact": i.impact,
            "recommendation": i.recommendation, "evidence": i.evidence, "department_id": i.department_id,
            "created_at": i.created_at,
            "label": "AI recommendation for human review. No action is taken automatically."}


_SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@router.get("/ai/insights")
def insights(_: User = Depends(require("insights:read")), db: Session = Depends(get_db)):
    items = db.scalars(select(AIInsight).where(AIInsight.status == "active")).all()
    return [_insight(i) for i in sorted(items, key=lambda i: (_SEVERITY[i.severity], -i.confidence))]


@router.post("/ai/insights/refresh")
def refresh_insights(request: Request, user: User = Depends(require("insights:read")),
                     db: Session = Depends(get_db)):
    items = InsightEngine(db).refresh()
    audit.record(db, request, user, "insights.refresh", "ai_insight", detail=f"{len(items)} active")
    db.commit()
    return [_insight(i) for i in sorted(items, key=lambda i: (_SEVERITY[i.severity], -i.confidence))]


@router.post("/ai/insights/{insight_id}/dismiss", status_code=204)
def dismiss_insight(insight_id: int, request: Request, user: User = Depends(require("insights:read")),
                    db: Session = Depends(get_db)):
    insight = db.get(AIInsight, insight_id)
    if insight is None:
        raise AppError(404, "Insight not found.")
    insight.status = "dismissed"
    audit.record(db, request, user, "insight.dismiss", "ai_insight", insight.id, detail=insight.key)
    db.commit()


@router.get("/ai/predictions")
def ai_predictions(user: User = Depends(require("insights:read")), db: Session = Depends(get_db)):
    data = predictions.all_predictions(db)
    risky = data["no_show"]["appointments"]
    if risky and "patients:read" in user.permissions:
        names = dict(db.execute(select(Patient.id, Patient.full_name)
                                .where(Patient.id.in_({r["patient_id"] for r in risky}))).all())
        for r in risky:
            r["patient"] = names.get(r["patient_id"])
    return data


# ------------------------------------------------------------------------------- operations copilot
@router.get("/ai/copilot/suggestions")
def copilot_suggestions(_: User = Depends(require("copilot:use"))):
    return copilot.SUGGESTIONS


@router.post("/ai/copilot", dependencies=[Depends(rate_limit("copilot", 30, 60))])
async def ask_copilot(body: QuestionRequest, request: Request, user: User = Depends(require("copilot:use")),
                      db: Session = Depends(get_db)):
    result = await copilot.ask(db, body.question)
    audit.record(db, request, user, "copilot.query", "analytics", detail=f"intent: {result['intent']}")
    db.commit()
    return result


# ------------------------------------------------------------------------------- doctor workspace
@router.get("/doctor/dashboard")
def doctor_dashboard(user: User = Depends(require("clinical:write")), db: Session = Depends(get_db)):
    """Workflow-first view for the signed-in doctor. The brief summarises workload; it makes no clinical calls."""
    doctor = doctor_of(db, user)
    if doctor is None:
        raise AppError(404, "No doctor profile is linked to this account.")
    t0, current = today_start(), now()
    schedule, _total = appointment_repo.search(db, start=t0, end=t0 + timedelta(days=1), doctor=doctor.id, size=100)
    queue = queue_service.get_or_create_queue(db, doctor, t0.date())
    db.commit()
    waiting = [a for a in schedule if a["status"] in ("waiting", "checked_in")]
    in_consult = next((a for a in schedule if a["status"] == "in_consultation"), None)
    done = [a for a in schedule if a["status"] == "completed"]
    waits = [(current - a["checked_in_at"]).total_seconds() / 60 for a in waiting if a["checked_in_at"]]
    consults = [(a["completed_at"] - a["started_at"]).total_seconds() / 60 for a in done
                if a["started_at"] and a["completed_at"]]
    avg_wait = round(sum(waits) / len(waits)) if waits else 0
    pending = [a for a in schedule if a["status"] in ("scheduled", "waiting", "checked_in")]
    active = [a for a in schedule if a["status"] != "cancelled"]

    if waiting:
        brief = [f"You have {len(waiting)} patient{'s' if len(waiting) != 1 else ''} waiting. "
                 f"Average waiting time is {avg_wait} minutes."]
    else:
        brief = ["No patients are waiting right now."]
    upcoming = [a for a in schedule if a["status"] == "scheduled" and a["scheduled_at"] > current]
    if upcoming:
        brief.append(f"Next scheduled appointment is at {upcoming[0]['scheduled_at']:%I:%M %p}; "
                     f"{len(upcoming)} more to come today.")
    if consults:
        pace = sum(consults) / len(consults)
        delta = pace - doctor.avg_consult_minutes
        brief.append(f"Consultations are averaging {pace:.0f} minutes today "
                     f"({'on' if abs(delta) < 2 else f'{abs(delta):.0f} min ' + ('over' if delta > 0 else 'under')} "
                     f"your usual pace).")
    alerts = []
    if waits and max(waits) >= 30:
        alerts.append({"severity": "warning", "text": f"Longest wait in your queue is {max(waits):.0f} minutes."})
    if len(pending) and consults and len(pending) * (sum(consults) / len(consults)) > \
            max(0, (doctor.shift_end - current.hour)) * 60:
        alerts.append({"severity": "info", "text": "At today's pace the remaining list may run past your shift."})
    return {
        "doctor": {"id": doctor.id, "name": user.full_name, "department": doctor.department.name,
                   "room": doctor.room, "shift": f"{doctor.shift_start:02d}:00–{doctor.shift_end:02d}:00"},
        "queue_id": queue.id,
        "metrics": {"todays_patients": len(active), "pending_consultations": len(pending),
                    "avg_consult_minutes": round(sum(consults) / len(consults)) if consults else None,
                    "waiting_patients": len(waiting), "avg_wait_minutes": avg_wait, "completed": len(done)},
        "current": in_consult, "waiting": waiting, "schedule": schedule, "alerts": alerts,
        "brief": {"lines": brief, "label": "Operational summary generated from your schedule and queue. "
                                           "It does not make clinical decisions."},
    }


@router.get("/analytics/queue-status")
def queue_status(_: User = Depends(require("analytics:read")), db: Session = Depends(get_db)):
    """Waiting patients and predicted wait per department, for the command center."""
    return {"departments": predictions.wait_time_predictions(db),
            "longest_waits": rows(db, """
                SELECT qe.token, d.name AS department, u.full_name AS doctor,
                       ROUND(EXTRACT(EPOCH FROM (CAST(:now AS timestamp) - qe.joined_at)) / 60)::int AS waited_minutes
                FROM queue_entries qe JOIN queues q ON q.id = qe.queue_id
                JOIN departments d ON d.id = q.department_id
                JOIN doctors doc ON doc.id = q.doctor_id JOIN users u ON u.id = doc.user_id
                WHERE qe.status = 'waiting' AND q.queue_date = :day
                ORDER BY qe.joined_at LIMIT 8""", now=now(), day=today_start().date())}
