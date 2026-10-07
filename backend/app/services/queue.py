from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.errors import AppError
from app.models import Appointment, ClinicalNote, Doctor, Prescription, Queue, QueueEntry, User, Visit
from app.services import appointments as appointment_service
from app.services.notifications import emit, notify

MAX_PRIORITY = 2


def get_or_create_queue(db: Session, doctor: Doctor, day: date) -> Queue:
    queue = db.scalar(select(Queue).where(Queue.doctor_id == doctor.id, Queue.queue_date == day))
    if queue is None:
        queue = Queue(doctor_id=doctor.id, department_id=doctor.department_id, queue_date=day)
        db.add(queue)
        db.flush()
    return queue


def next_token(db: Session, doctor: Doctor, day: date) -> str:
    """Tokens run per department per day: A-001, A-002, ..."""
    issued = db.scalar(select(func.count(QueueEntry.id)).join(Queue).where(
        Queue.department_id == doctor.department_id, Queue.queue_date == day)) or 0
    return f"{doctor.department.code}-{issued + 1:03d}"


def waiting_entries(db: Session, queue_id: int) -> list[QueueEntry]:
    return list(db.scalars(select(QueueEntry).where(QueueEntry.queue_id == queue_id, QueueEntry.status == "waiting")
                           .order_by(QueueEntry.priority.desc(), QueueEntry.joined_at, QueueEntry.id)))


def current_entry(db: Session, queue_id: int) -> QueueEntry | None:
    return db.scalar(select(QueueEntry).where(QueueEntry.queue_id == queue_id,
                                              QueueEntry.status == "in_consultation"))


def measured_consult_minutes(db: Session, doctor: Doctor) -> float:
    """Doctor's observed average consultation length over the last 14 days, else their configured norm."""
    avg = db.scalar(select(func.avg(func.extract("epoch", Appointment.completed_at - Appointment.started_at) / 60))
                    .where(Appointment.doctor_id == doctor.id, Appointment.status == "completed",
                           Appointment.completed_at >= now() - timedelta(days=14)))
    return float(avg) if avg else float(doctor.avg_consult_minutes)


def estimate(db: Session, entry: QueueEntry, queue: Queue) -> dict:
    """Explainable wait estimate for one queue entry."""
    waiting = waiting_entries(db, queue.id)
    serving = current_entry(db, queue.id)
    ahead = next((i for i, e in enumerate(waiting) if e.id == entry.id), 0) if entry.status == "waiting" else 0
    per_patient = measured_consult_minutes(db, queue.doctor)
    remaining = 0.0
    if serving and serving.called_at:
        elapsed = (now() - serving.called_at).total_seconds() / 60
        remaining = max(2.0, per_patient - elapsed)
    minutes = 0 if entry.status != "waiting" else round(remaining + ahead * per_patient)
    return {
        "token": entry.token, "status": entry.status, "patients_ahead": ahead,
        "currently_serving": serving.token if serving else None,
        "estimated_wait_minutes": minutes,
        # Confidence falls as the queue gets longer: more consultations, more variance.
        "confidence": round(max(0.55, 0.9 - 0.04 * ahead), 2),
        "factors": [
            {"name": "Queue length", "detail": f"{ahead} patient{'s' if ahead != 1 else ''} ahead of you"},
            {"name": "Doctor's consultation pace", "detail": f"about {per_patient:.0f} min per patient (last 14 days)"},
            {"name": "Current consultation", "detail": f"about {remaining:.0f} min remaining" if serving
             else "no consultation in progress"},
        ],
        "label": "AI-generated estimate, not a guaranteed time",
    }


def _notify_position(db: Session, queue: Queue) -> None:
    waiting = waiting_entries(db, queue.id)
    if waiting:
        notify(db, waiting[0].patient.user_id, "queue_update", "You're next",
               f"Token {waiting[0].token}: please make your way to room {queue.doctor.room}.", "info",
               "/patient/queue")


def check_in(db: Session, appt: Appointment, user: User) -> QueueEntry:
    today = now().date()
    if appt.scheduled_at.date() != today:
        raise AppError(409, "Check-in opens on the day of the appointment.")
    if appt.status != "scheduled":
        raise AppError(409, f"This appointment is already {appt.status.replace('_', ' ')}.")
    doctor = appt.doctor
    queue = get_or_create_queue(db, doctor, today)
    appointment_service.set_status(db, appt, "checked_in", user)
    appointment_service.set_status(db, appt, "waiting", user)
    entry = QueueEntry(queue_id=queue.id, appointment_id=appt.id, patient_id=appt.patient_id,
                       token=next_token(db, doctor, today), priority=1 if appt.appointment_type == "emergency" else 0)
    db.add(entry)
    db.flush()
    info = estimate(db, entry, queue)
    notify(db, appt.patient.user_id, "queue_update", f"Checked in · token {entry.token}",
           f"{info['patients_ahead']} ahead of you. Estimated wait about {info['estimated_wait_minutes']} min.",
           "success", "/patient/queue")
    notify(db, doctor.user_id, "patient_waiting", "Patient waiting", f"{appt.patient.full_name} checked in "
           f"({entry.token}).", "info", "/doctor/dashboard")
    emit(db, "queue.updated", queue_id=queue.id)
    return entry


def call_next(db: Session, queue: Queue, user: User) -> QueueEntry:
    if current_entry(db, queue.id):
        raise AppError(409, "Complete the current consultation before calling the next patient.")
    waiting = waiting_entries(db, queue.id)
    if not waiting:
        raise AppError(409, "There are no patients waiting in this queue.")
    entry = waiting[0]
    entry.status, entry.called_at = "in_consultation", now()
    if appt := db.get(Appointment, entry.appointment_id):
        appointment_service.set_status(db, appt, "in_consultation", user)
    notify(db, entry.patient.user_id, "queue_update", "It's your turn",
           f"Token {entry.token}: {queue.doctor.user.full_name} is ready for you in room {queue.doctor.room}.",
           "success", "/patient/queue")
    db.flush()
    _notify_position(db, queue)
    emit(db, "queue.updated", queue_id=queue.id)
    return entry


def complete(db: Session, entry: QueueEntry, queue: Queue, user: User, note: str = "",
             prescription: dict | None = None) -> Visit | None:
    if entry.status not in {"in_consultation", "waiting"}:
        raise AppError(409, "This queue entry is already closed.")
    entry.status, entry.completed_at = "completed", now()
    visit = None
    appt = db.get(Appointment, entry.appointment_id) if entry.appointment_id else None
    if appt:
        appointment_service.set_status(db, appt, "completed", user)
        visit = Visit(patient_id=appt.patient_id, doctor_id=appt.doctor_id, department_id=appt.department_id,
                      appointment_id=appt.id, started_at=appt.started_at, ended_at=appt.completed_at,
                      summary=appt.reason or "Consultation")
        db.add(visit)
        db.flush()
        if note.strip():
            db.add(ClinicalNote(visit_id=visit.id, author_id=user.id, note=note.strip()))
        if prescription:
            db.add(Prescription(visit_id=visit.id, patient_id=appt.patient_id, doctor_id=appt.doctor_id,
                                **prescription))
            notify(db, appt.patient.user_id, "prescription", "New prescription available",
                   "Your doctor added a prescription to your records.", "info", "/patient/documents")
        notify(db, appt.patient.user_id, "feedback_request", "How was your visit?",
               "Your feedback helps us improve. It takes under a minute.", "info", "/patient/feedback")
    emit(db, "queue.updated", queue_id=queue.id)
    return visit


def skip(db: Session, entry: QueueEntry, queue: Queue) -> None:
    """Patient not present: move to the back of the line without losing their place in the queue."""
    if entry.status != "waiting":
        raise AppError(409, "Only waiting patients can be skipped.")
    entry.joined_at, entry.priority = now(), 0
    notify(db, entry.patient.user_id, "queue_update", "We called your token",
           f"Token {entry.token} was called but you weren't available. You've been moved back in the queue.",
           "warning", "/patient/queue")
    emit(db, "queue.updated", queue_id=queue.id)


def prioritize(db: Session, entry: QueueEntry, queue: Queue) -> None:
    if entry.status != "waiting":
        raise AppError(409, "Only waiting patients can be prioritised.")
    entry.priority = MAX_PRIORITY
    emit(db, "queue.updated", queue_id=queue.id)


def transfer(db: Session, entry: QueueEntry, queue: Queue, to_doctor: Doctor, user: User) -> None:
    if entry.status != "waiting":
        raise AppError(409, "Only waiting patients can be transferred.")
    if to_doctor.id == queue.doctor_id:
        raise AppError(400, "The patient is already in this doctor's queue.")
    target = get_or_create_queue(db, to_doctor, queue.queue_date)
    entry.queue_id, entry.joined_at = target.id, now()
    if appt := db.get(Appointment, entry.appointment_id):
        appt.doctor_id, appt.department_id = to_doctor.id, to_doctor.department_id
        appointment_service._flush_or_conflict(db)  # target doctor may already hold that slot
    notify(db, entry.patient.user_id, "queue_update", "Your queue was changed",
           f"You'll now be seen by {to_doctor.user.full_name} in room {to_doctor.room}.", "info", "/patient/queue")
    notify(db, to_doctor.user_id, "patient_waiting", "Patient transferred to you",
           f"{entry.patient.full_name} ({entry.token})", "info", "/doctor/dashboard")
    emit(db, "queue.updated", queue_id=queue.id)
    emit(db, "queue.updated", queue_id=target.id)
