from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import Page, like
from app.core.db import get_db
from app.core.errors import AppError
from app.models import Department, Patient, PatientProfile, User
from app.repositories import patients as repo
from app.schemas.requests import PatientCreate
from app.security import audit
from app.security.auth import authorize_patient_access, current_user, doctor_of, patient_of, require

router = APIRouter(prefix="/patients", tags=["patients"])
PatientStatus = Literal["active", "admitted", "discharged", "inactive"]


def _own_doctor_scope(db: Session, user: User) -> int | None:
    """Doctors (who are not also managers) only see patients they have appointments with."""
    if user.role_names == ["doctor"]:
        doctor = doctor_of(db, user)
        return doctor.id if doctor else -1
    return None


@router.get("")
def list_patients(q: str | None = Query(None, max_length=80), department_id: int | None = Query(None, ge=1),
                  doctor_id: int | None = Query(None, ge=1), status: PatientStatus | None = None,
                  appointment_date: date | None = None, page: Page = Depends(),
                  user: User = Depends(require("patients:read")), db: Session = Depends(get_db)):
    doctor = _own_doctor_scope(db, user) or doctor_id
    items, total = repo.directory(db, like(q), department_id, doctor, status, appointment_date, page.size,
                                  page.offset)
    return page.wrap(items, total)


@router.post("", status_code=201)
def register_patient(body: PatientCreate, request: Request, user: User = Depends(require("patients:write")),
                     db: Session = Depends(get_db)):
    if body.primary_department_id and not db.get(Department, body.primary_department_id):
        raise AppError(404, "Department not found.")
    patient = Patient(mrn="MF-TMP", full_name=body.full_name, date_of_birth=body.date_of_birth, gender=body.gender,
                      phone=body.phone, email=body.email or "", primary_department_id=body.primary_department_id)
    db.add(patient)
    db.flush()
    patient.mrn = f"MF-{100000 + patient.id}"
    db.add(PatientProfile(patient_id=patient.id))
    audit.record(db, request, user, "patient.register", "patient", patient.id)
    db.commit()
    return {"id": patient.id, "mrn": patient.mrn, "full_name": patient.full_name}


@router.get("/me")
def my_record(user: User = Depends(current_user), db: Session = Depends(get_db)):
    patient = patient_of(db, user)
    if patient is None:
        raise AppError(404, "No patient record is linked to this account.")
    return repo.profile(db, patient.id, include_clinical=True)  # a patient may always see their own record


@router.get("/{patient_id}")
def get_patient(patient_id: int, request: Request, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    authorize_patient_access(db, user, patient_id)
    own = patient_of(db, user)
    is_self = own is not None and own.id == patient_id
    if not is_self and (scope := _own_doctor_scope(db, user)) and not repo.is_patient_of(db, patient_id, scope):
        audit.record(db, request, user, "patient.view", "patient", patient_id, result="denied")
        db.commit()
        raise AppError(403, "You can only open records of patients under your care.")
    record = repo.profile(db, patient_id, include_clinical=is_self or "clinical:read" in user.permissions)
    if record is None:
        raise AppError(404, "Patient not found.")
    if not is_self:
        audit.record(db, request, user, "patient.view", "patient", patient_id,
                     detail="clinical" if record["clinical_access"] else "demographics only")
        db.commit()
    return record
