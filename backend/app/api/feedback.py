from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.analytics.metrics import rows
from app.api.deps import Page
from app.core.db import get_db
from app.core.errors import AppError
from app.models import Complaint, Department, Doctor, Feedback, Notification, User, Visit
from app.schemas.requests import FeedbackCreate
from app.security import audit
from app.security.auth import current_user, patient_of, require
from app.services.feedback_ai import classify
from app.services.notifications import emit, notify_roles

router = APIRouter(tags=["feedback"])


@router.post("/feedback", status_code=201)
def submit_feedback(body: FeedbackCreate, request: Request, user: User = Depends(require("feedback:write")),
                    db: Session = Depends(get_db)):
    patient = patient_of(db, user)
    if patient is None:
        raise AppError(403, "Only patients can submit feedback.")
    data = body.model_dump()
    if body.visit_id:
        visit = db.get(Visit, body.visit_id)
        if visit is None or visit.patient_id != patient.id:
            raise AppError(404, "Visit not found.")
        data["department_id"], data["doctor_id"] = visit.department_id, visit.doctor_id
    elif body.doctor_id:
        doctor = db.get(Doctor, body.doctor_id)
        if doctor is None:
            raise AppError(404, "Doctor not found.")
        data["department_id"] = doctor.department_id
    department = db.get(Department, data["department_id"]) if data["department_id"] else None
    if data["department_id"] and department is None:
        raise AppError(404, "Department not found.")

    label = classify(body.comment, body.overall, department.name if department else "")
    feedback = Feedback(patient_id=patient.id, **data, sentiment=label.sentiment, category=label.category,
                        urgency=label.urgency, theme=label.theme)
    db.add(feedback)
    db.flush()
    if label.sentiment == "negative" and label.urgency != "low":
        db.add(Complaint(feedback_id=feedback.id, patient_id=patient.id, department_id=data["department_id"],
                         category=label.category, urgency=label.urgency, description=body.comment))
        if label.urgency == "high":
            notify_roles(db, ("administrator", "super_admin"), "complaint", "High-urgency patient complaint",
                         f"{label.theme}. Review it in Patient Experience.", "warning", "/admin/experience")
    audit.record(db, request, user, "feedback.submit", "feedback", feedback.id)
    emit(db, "feedback.new")
    db.commit()
    return {"id": feedback.id, "analysis": {"sentiment": label.sentiment, "category": label.category,
                                            "urgency": label.urgency, "theme": label.theme}}


@router.get("/feedback/mine")
def my_feedback(user: User = Depends(current_user), db: Session = Depends(get_db)):
    patient = patient_of(db, user)
    if patient is None:
        return {"items": [], "visits": []}
    items = rows(db, """
        SELECT f.id, f.overall, f.nps, f.comment, f.created_at, d.name AS department
        FROM feedback f LEFT JOIN departments d ON d.id = f.department_id
        WHERE f.patient_id = :p ORDER BY f.created_at DESC LIMIT 20""", p=patient.id)
    visits = rows(db, """
        SELECT v.id, v.started_at, u.full_name AS doctor, d.name AS department
        FROM visits v JOIN doctors doc ON doc.id = v.doctor_id JOIN users u ON u.id = doc.user_id
        JOIN departments d ON d.id = v.department_id
        WHERE v.patient_id = :p AND NOT EXISTS (SELECT 1 FROM feedback f WHERE f.visit_id = v.id)
        ORDER BY v.started_at DESC LIMIT 5""", p=patient.id)
    return {"items": items, "visits": visits}


@router.get("/feedback")
def list_feedback(sentiment: Literal["positive", "neutral", "negative"] | None = None,
                  category: str | None = Query(None, max_length=24), department_id: int | None = Query(None, ge=1),
                  page: Page = Depends(), _: User = Depends(require("experience:read")),
                  db: Session = Depends(get_db)):
    items = rows(db, """
        SELECT f.id, f.overall, f.nps, f.comment, f.sentiment, f.category, f.urgency, f.theme, f.created_at,
               d.name AS department, COUNT(*) OVER () AS total
        FROM feedback f LEFT JOIN departments d ON d.id = f.department_id
        WHERE (CAST(:sentiment AS text) IS NULL OR f.sentiment = :sentiment)
          AND (CAST(:category AS text) IS NULL OR f.category = :category)
          AND (CAST(:dept AS int) IS NULL OR f.department_id = :dept)
        ORDER BY f.created_at DESC LIMIT :size OFFSET :offset""",
                 sentiment=sentiment, category=category, dept=department_id, size=page.size, offset=page.offset)
    total = items[0]["total"] if items else 0
    for i in items:
        i.pop("total")
    return page.wrap(items, total)


# ------------------------------------------------------------------------------- notifications
@router.get("/notifications")
def list_notifications(user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.scalars(select(Notification).where(Notification.user_id == user.id)
                       .order_by(Notification.created_at.desc(), Notification.id.desc()).limit(40)).all()
    return {"unread": sum(1 for n in items if not n.is_read),
            "items": [{"id": n.id, "type": n.type, "title": n.title, "body": n.body, "severity": n.severity,
                       "link": n.link, "is_read": n.is_read, "created_at": n.created_at} for n in items]}


@router.post("/notifications/read-all", status_code=204)
def read_all(user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.user_id == user.id).values(is_read=True))
    db.commit()


@router.post("/notifications/{notification_id}/read", status_code=204)
def read_one(notification_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.execute(update(Notification).where(Notification.id == notification_id, Notification.user_id == user.id)
               .values(is_read=True))
    db.commit()
