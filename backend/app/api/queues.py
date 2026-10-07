from datetime import timedelta

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.metrics import rows
from app.core.clock import now, today_start
from app.core.db import get_db
from app.core.errors import AppError
from app.models import Appointment, Doctor, Queue, QueueEntry, User
from app.schemas.requests import CheckInRequest, CompleteConsultation, TransferRequest
from app.security import audit
from app.security.auth import current_user, doctor_of, patient_of, require
from app.services import queue as service

router = APIRouter(prefix="/queues", tags=["queues"])


def _queue_view(db: Session, queue: Queue, with_names: bool) -> dict:
    current = service.current_entry(db, queue.id)
    waiting = service.waiting_entries(db, queue.id)
    pace = service.measured_consult_minutes(db, queue.doctor)
    stamp = now()
    remaining = 0.0
    if current and current.called_at:
        remaining = max(2.0, pace - (stamp - current.called_at).total_seconds() / 60)

    def entry(e: QueueEntry, position: int | None = None) -> dict:
        return {"id": e.id, "token": e.token, "status": e.status, "priority": e.priority,
                "patient": e.patient.full_name if with_names else None, "patient_id": e.patient_id,
                "appointment_id": e.appointment_id, "joined_at": e.joined_at,
                "waited_minutes": round((stamp - e.joined_at).total_seconds() / 60),
                "estimated_wait_minutes": None if position is None else round(remaining + position * pace)}

    done = rows(db, "SELECT COUNT(*) AS n FROM queue_entries WHERE queue_id = :q AND status = 'completed'",
                q=queue.id)[0]["n"]
    return {"id": queue.id, "doctor_id": queue.doctor_id, "doctor": queue.doctor.user.full_name,
            "room": queue.doctor.room, "department_id": queue.department_id,
            "department": queue.doctor.department.name, "avg_consult_minutes": round(pace),
            "current": entry(current) if current else None,
            "waiting": [entry(e, i) for i, e in enumerate(waiting)], "completed": done}


@router.get("")
def list_queues(department_id: int | None = Query(None, ge=1), doctor_id: int | None = Query(None, ge=1),
                user: User = Depends(require("queue:read")), db: Session = Depends(get_db)):
    """Today's live queues. Doctors see their own; other staff can filter by department or doctor."""
    stmt = select(Queue).where(Queue.queue_date == now().date()).order_by(Queue.department_id, Queue.doctor_id)
    if user.role_names == ["doctor"]:
        doctor = doctor_of(db, user)
        stmt = stmt.where(Queue.doctor_id == (doctor.id if doctor else -1))
    else:
        if department_id:
            stmt = stmt.where(Queue.department_id == department_id)
        if doctor_id:
            stmt = stmt.where(Queue.doctor_id == doctor_id)
    queues = [_queue_view(db, q, with_names="patients:read" in user.permissions) for q in db.scalars(stmt)]
    return {"queues": queues, "waiting_total": sum(len(q["waiting"]) for q in queues), "generated_at": now()}


@router.get("/me")
def my_queue(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Patient view: live position and wait estimate, plus today's appointments that can be checked in."""
    patient = patient_of(db, user)
    if patient is None:
        raise AppError(404, "No patient record is linked to this account.")
    t0 = today_start()
    entry = db.scalar(select(QueueEntry).join(Queue).where(
        QueueEntry.patient_id == patient.id, Queue.queue_date == t0.date(),
        QueueEntry.status.in_(("waiting", "in_consultation"))).order_by(QueueEntry.id.desc()))
    active = None
    if entry:
        queue = db.get(Queue, entry.queue_id)
        active = {**service.estimate(db, entry, queue), "doctor": queue.doctor.user.full_name,
                  "room": queue.doctor.room, "department": queue.doctor.department.name}
    eligible = rows(db, """
        SELECT a.id, a.scheduled_at, u.full_name AS doctor, d.name AS department, doc.room
        FROM appointments a JOIN doctors doc ON doc.id = a.doctor_id JOIN users u ON u.id = doc.user_id
        JOIN departments d ON d.id = a.department_id
        WHERE a.patient_id = :p AND a.status = 'scheduled' AND a.scheduled_at >= :t0 AND a.scheduled_at < :t1
        ORDER BY a.scheduled_at""", p=patient.id, t0=t0, t1=t0 + timedelta(days=1))
    return {"entry": active, "can_check_in": eligible}


@router.post("/check-in", status_code=201)
def check_in(body: CheckInRequest, request: Request, user: User = Depends(current_user),
             db: Session = Depends(get_db)):
    appt = db.get(Appointment, body.appointment_id)
    if appt is None:
        raise AppError(404, "Appointment not found.")
    if "queue:manage" not in user.permissions:
        patient = patient_of(db, user)
        if patient is None or patient.id != appt.patient_id:
            raise AppError(403, "You can only check in for your own appointment.")
    entry = service.check_in(db, appt, user)
    audit.record(db, request, user, "queue.check_in", "appointment", appt.id)
    queue = db.get(Queue, entry.queue_id)
    info = service.estimate(db, entry, queue)
    db.commit()
    return info


def _entry(db: Session, entry_id: int) -> tuple[QueueEntry, Queue]:
    entry = db.get(QueueEntry, entry_id)
    if entry is None:
        raise AppError(404, "Queue entry not found.")
    return entry, db.get(Queue, entry.queue_id)


@router.post("/{queue_id}/call-next")
def call_next(queue_id: int, request: Request, user: User = Depends(require("queue:manage")),
              db: Session = Depends(get_db)):
    queue = db.get(Queue, queue_id)
    if queue is None:
        raise AppError(404, "Queue not found.")
    entry = service.call_next(db, queue, user)
    audit.record(db, request, user, "queue.call_next", "queue_entry", entry.id)
    db.commit()
    return {"token": entry.token, "status": entry.status}


@router.post("/entries/{entry_id}/complete")
def complete(entry_id: int, body: CompleteConsultation, request: Request,
             user: User = Depends(require("queue:manage")), db: Session = Depends(get_db)):
    entry, queue = _entry(db, entry_id)
    if (body.note or body.prescription) and "clinical:write" not in user.permissions:
        raise AppError(403, "Only clinicians can add consultation notes or prescriptions.")
    visit = service.complete(db, entry, queue, user, body.note,
                             body.prescription.model_dump() if body.prescription else None)
    audit.record(db, request, user, "consultation.complete", "queue_entry", entry.id,
                 detail="with note" if body.note else "")
    db.commit()
    return {"token": entry.token, "status": entry.status, "visit_id": visit.id if visit else None}


@router.post("/entries/{entry_id}/skip")
def skip(entry_id: int, request: Request, user: User = Depends(require("queue:manage")),
         db: Session = Depends(get_db)):
    entry, queue = _entry(db, entry_id)
    service.skip(db, entry, queue)
    audit.record(db, request, user, "queue.skip", "queue_entry", entry.id)
    db.commit()
    return {"token": entry.token, "status": entry.status}


@router.post("/entries/{entry_id}/prioritize")
def prioritize(entry_id: int, request: Request, user: User = Depends(require("queue:manage")),
               db: Session = Depends(get_db)):
    entry, queue = _entry(db, entry_id)
    service.prioritize(db, entry, queue)
    audit.record(db, request, user, "queue.prioritize", "queue_entry", entry.id)
    db.commit()
    return {"token": entry.token, "priority": entry.priority}


@router.post("/entries/{entry_id}/transfer")
def transfer(entry_id: int, body: TransferRequest, request: Request,
             user: User = Depends(require("queue:manage")), db: Session = Depends(get_db)):
    entry, queue = _entry(db, entry_id)
    to_doctor = db.get(Doctor, body.doctor_id)
    if to_doctor is None:
        raise AppError(404, "Doctor not found.")
    service.transfer(db, entry, queue, to_doctor, user)
    audit.record(db, request, user, "queue.transfer", "queue_entry", entry.id, detail=f"to doctor {to_doctor.id}")
    db.commit()
    return {"token": entry.token, "doctor_id": to_doctor.id}
