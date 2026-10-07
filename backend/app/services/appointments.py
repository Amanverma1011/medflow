from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.errors import AppError
from app.models import Appointment, AppointmentStatusHistory, Doctor, Patient, User
from app.models.clinical import ACTIVE_STATUSES
from app.services.notifications import emit, notify

SLOT_MINUTES = 30
TRANSITIONS: dict[str, set[str]] = {
    "scheduled": {"checked_in", "waiting", "in_consultation", "cancelled", "no_show"},
    "checked_in": {"waiting", "in_consultation", "cancelled", "no_show"},
    "waiting": {"in_consultation", "completed", "cancelled", "no_show"},
    "in_consultation": {"completed"},
    "completed": set(), "cancelled": set(), "no_show": set(),
}


def set_status(db: Session, appt: Appointment, to: str, user: User | None) -> None:
    if to == appt.status:
        return
    if to not in TRANSITIONS[appt.status]:
        raise AppError(409, f"An appointment that is {appt.status.replace('_', ' ')} cannot be marked "
                            f"{to.replace('_', ' ')}.")
    db.add(AppointmentStatusHistory(appointment_id=appt.id, from_status=appt.status, to_status=to,
                                    changed_by=user.id if user else None))
    stamp = now()
    if to in {"checked_in", "waiting"} and appt.checked_in_at is None:
        appt.checked_in_at = stamp
    elif to == "in_consultation":
        appt.checked_in_at = appt.checked_in_at or stamp
        appt.started_at = stamp
    elif to == "completed":
        appt.started_at = appt.started_at or stamp
        appt.completed_at = stamp
    appt.status = to
    emit(db, "appointment.updated", id=appt.id)


def day_slots(db: Session, doctor: Doctor, day: date) -> list[dict]:
    """Every bookable slot in the doctor's shift for `day`, flagged available or not."""
    start = datetime.combine(day, datetime.min.time()) + timedelta(hours=doctor.shift_start)
    end = datetime.combine(day, datetime.min.time()) + timedelta(hours=doctor.shift_end)
    taken = set(db.scalars(select(Appointment.scheduled_at).where(
        Appointment.doctor_id == doctor.id, Appointment.scheduled_at >= start, Appointment.scheduled_at < end,
        Appointment.status.in_(ACTIVE_STATUSES))))
    current, slots, t = now(), [], start
    while t < end:
        slots.append({"time": t.isoformat(), "available": doctor.is_available and t > current and t not in taken})
        t += timedelta(minutes=SLOT_MINUTES)
    return slots


def _validate_slot(db: Session, doctor: Doctor, patient_id: int, when: datetime, ignore_id: int | None) -> None:
    if when <= now():
        raise AppError(400, "Appointments must be booked for a future time.")
    if when.minute % SLOT_MINUTES or when.second:
        raise AppError(400, f"Appointments start on {SLOT_MINUTES}-minute boundaries.")
    if not doctor.is_available:
        raise AppError(409, "This doctor is not currently accepting appointments.")
    if not (doctor.shift_start <= when.hour < doctor.shift_end):
        raise AppError(409, "That time is outside the doctor's working hours.")
    clash = select(Appointment.id).where(Appointment.scheduled_at == when, Appointment.status.in_(ACTIVE_STATUSES))
    if ignore_id:
        clash = clash.where(Appointment.id != ignore_id)
    if db.scalar(clash.where(Appointment.doctor_id == doctor.id)):
        raise AppError(409, "That slot has just been taken. Please choose another time.")
    if db.scalar(clash.where(Appointment.patient_id == patient_id)):
        raise AppError(409, "This patient already has an appointment at that time.")


def _flush_or_conflict(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError:  # the partial unique index caught a concurrent booking
        db.rollback()
        raise AppError(409, "That slot has just been taken. Please choose another time.")


def create(db: Session, patient: Patient, doctor: Doctor, when: datetime, appointment_type: str, reason: str,
           user: User) -> Appointment:
    _validate_slot(db, doctor, patient.id, when, None)
    appt = Appointment(patient_id=patient.id, doctor_id=doctor.id, department_id=doctor.department_id,
                       scheduled_at=when, duration_minutes=SLOT_MINUTES, appointment_type=appointment_type,
                       reason=reason, created_by=user.id)
    db.add(appt)
    _flush_or_conflict(db)
    db.add(AppointmentStatusHistory(appointment_id=appt.id, to_status="scheduled", changed_by=user.id))
    when_text = when.strftime("%a %d %b, %I:%M %p")
    notify(db, patient.user_id, "appointment_confirmation", "Appointment confirmed",
           f"{doctor.user.full_name} · {doctor.department.name} · {when_text}", "success", "/patient/appointments")
    notify(db, doctor.user_id, "upcoming_appointment", "New appointment booked",
           f"{patient.full_name} · {when_text}", "info", "/doctor/appointments")
    emit(db, "appointment.updated", id=appt.id)
    return appt


def reschedule(db: Session, appt: Appointment, when: datetime, user: User) -> None:
    if appt.status != "scheduled":
        raise AppError(409, "Only scheduled appointments can be rescheduled.")
    _validate_slot(db, appt.doctor, appt.patient_id, when, appt.id)
    appt.scheduled_at = when
    _flush_or_conflict(db)
    when_text = when.strftime("%a %d %b, %I:%M %p")
    notify(db, appt.patient.user_id, "schedule_change", "Appointment rescheduled",
           f"Your appointment with {appt.doctor.user.full_name} is now {when_text}.", "info",
           "/patient/appointments")
    notify(db, appt.doctor.user_id, "schedule_change", "Schedule change",
           f"{appt.patient.full_name} moved to {when_text}.", "info", "/doctor/appointments")
    emit(db, "appointment.updated", id=appt.id)


def cancel(db: Session, appt: Appointment, user: User) -> None:
    set_status(db, appt, "cancelled", user)
    when_text = appt.scheduled_at.strftime("%a %d %b, %I:%M %p")
    notify(db, appt.patient.user_id, "appointment_cancellation", "Appointment cancelled",
           f"Your appointment with {appt.doctor.user.full_name} on {when_text} was cancelled.", "warning",
           "/patient/appointments")
    notify(db, appt.doctor.user_id, "schedule_change", "Appointment cancelled",
           f"{appt.patient.full_name} · {when_text}", "info", "/doctor/appointments")
