from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import Page, like
from app.core.db import get_db
from app.core.errors import AppError
from app.models import Appointment, Doctor, Patient, User
from app.repositories import appointments as repo
from app.schemas.requests import AppointmentCreate, AppointmentUpdate
from app.security import audit
from app.security.auth import current_user, doctor_of, patient_of
from app.services import appointments as service

router = APIRouter(prefix="/appointments", tags=["appointments"])
Status = Literal["scheduled", "checked_in", "waiting", "in_consultation", "completed", "cancelled", "no_show"]


def _scope(db: Session, user: User, doctor_id: int | None, patient_id: int | None) -> tuple[int | None, int | None]:
    """Narrow (doctor, patient) filters to what this caller may see."""
    if "appointments:read" not in user.permissions:
        patient = patient_of(db, user)
        if patient is None:
            raise AppError(403, "You don't have permission to view appointments.")
        return doctor_id, patient.id
    if user.role_names == ["doctor"]:
        doctor = doctor_of(db, user)
        return (doctor.id if doctor else -1), patient_id
    return doctor_id, patient_id


def _midnight(day: date | None) -> datetime | None:
    return datetime.combine(day, datetime.min.time()) if day else None


@router.get("")
def list_appointments(date_from: date | None = None, date_to: date | None = None,
                      doctor_id: int | None = Query(None, ge=1), department_id: int | None = Query(None, ge=1),
                      patient_id: int | None = Query(None, ge=1), status: Status | None = None,
                      q: str | None = Query(None, max_length=80), newest_first: bool = False,
                      page: Page = Depends(), user: User = Depends(current_user), db: Session = Depends(get_db)):
    doctor, patient = _scope(db, user, doctor_id, patient_id)
    end = _midnight(date_to + timedelta(days=1)) if date_to else None
    items, total = repo.search(db, start=_midnight(date_from), end=end, doctor=doctor, dept=department_id,
                               patient=patient, status=status, like=like(q), size=page.size, offset=page.offset,
                               newest_first=newest_first)
    return page.wrap(items, total)


@router.get("/calendar")
def month_calendar(month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
                   doctor_id: int | None = Query(None, ge=1), department_id: int | None = Query(None, ge=1),
                   user: User = Depends(current_user), db: Session = Depends(get_db)):
    doctor, patient = _scope(db, user, doctor_id, None)
    start = datetime.strptime(month, "%Y-%m")
    end = (start + timedelta(days=32)).replace(day=1)
    return {"month": month, "days": repo.month_counts(db, start, end, doctor, department_id, patient)}


@router.post("", status_code=201)
def create_appointment(body: AppointmentCreate, request: Request, user: User = Depends(current_user),
                       db: Session = Depends(get_db)):
    if "appointments:write" in user.permissions:
        if body.patient_id is None:
            raise AppError(400, "Select the patient this appointment is for.")
        patient = db.get(Patient, body.patient_id)
    else:
        patient = patient_of(db, user)  # patients can only ever book for themselves
        if patient is None:
            raise AppError(403, "You don't have permission to book appointments.")
    doctor = db.get(Doctor, body.doctor_id)
    if patient is None or doctor is None:
        raise AppError(404, "Patient or doctor not found.")
    appt = service.create(db, patient, doctor, body.scheduled_at, body.appointment_type, body.reason, user)
    audit.record(db, request, user, "appointment.create", "appointment", appt.id)
    db.commit()
    return repo.one(db, appt.id)


def _load(db: Session, user: User, appointment_id: int) -> Appointment:
    appt = db.get(Appointment, appointment_id)
    if appt is None:
        raise AppError(404, "Appointment not found.")
    if "appointments:write" not in user.permissions:
        patient = patient_of(db, user)
        if patient is None or patient.id != appt.patient_id:
            raise AppError(403, "You don't have permission to change this appointment.")
    return appt


@router.get("/{appointment_id}")
def get_appointment(appointment_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    doctor, patient = _scope(db, user, None, None)
    appt = repo.one(db, appointment_id)
    if appt is None or (patient and appt["patient_id"] != patient) or (doctor and appt["doctor_id"] != doctor):
        raise AppError(404, "Appointment not found.")
    return appt


@router.patch("/{appointment_id}")
def update_appointment(appointment_id: int, body: AppointmentUpdate, request: Request,
                       user: User = Depends(current_user), db: Session = Depends(get_db)):
    appt = _load(db, user, appointment_id)
    if body.scheduled_at is None and body.status is None:
        raise AppError(400, "Provide a new time or a new status.")
    is_staff = "appointments:write" in user.permissions
    if body.status == "no_show" and not is_staff:
        raise AppError(403, "Only staff can mark an appointment as a no-show.")
    before = appt.status
    if body.scheduled_at is not None:
        service.reschedule(db, appt, body.scheduled_at, user)
        audit.record(db, request, user, "appointment.reschedule", "appointment", appt.id)
    if body.status == "cancelled":
        service.cancel(db, appt, user)
    elif body.status == "no_show":
        service.set_status(db, appt, "no_show", user)
    if body.status:
        audit.record(db, request, user, "appointment.status", "appointment", appt.id,
                     detail=f"{before} -> {appt.status}")
    db.commit()
    return repo.one(db, appt.id)
