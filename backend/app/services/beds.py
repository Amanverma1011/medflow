from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.errors import AppError
from app.models import Bed, BedAssignment, Patient
from app.services.notifications import emit

MANUAL_STATUSES = {"available", "cleaning", "maintenance", "reserved"}


def open_assignment(db: Session, bed_id: int) -> BedAssignment | None:
    return db.scalar(select(BedAssignment).where(BedAssignment.bed_id == bed_id,
                                                 BedAssignment.released_at.is_(None)))


def set_status(db: Session, bed: Bed, status: str) -> None:
    if status not in MANUAL_STATUSES:
        raise AppError(400, "Beds become occupied by assigning a patient, not by setting a status.")
    if bed.status == "occupied":
        raise AppError(409, "Discharge the patient before changing this bed's status.")
    bed.status = status
    emit(db, "bed.updated", id=bed.id)


def assign(db: Session, bed: Bed, patient: Patient, expected_discharge_at: datetime | None) -> BedAssignment:
    if bed.status not in {"available", "reserved"}:
        raise AppError(409, f"Bed {bed.label} is {bed.status} and cannot take a patient.")
    already = db.scalar(select(BedAssignment).where(BedAssignment.patient_id == patient.id,
                                                    BedAssignment.released_at.is_(None)))
    if already:
        raise AppError(409, f"{patient.full_name} is already admitted to another bed.")
    assignment = BedAssignment(bed_id=bed.id, patient_id=patient.id, expected_discharge_at=expected_discharge_at)
    db.add(assignment)
    bed.status, patient.status = "occupied", "admitted"
    emit(db, "bed.updated", id=bed.id)
    return assignment


def release(db: Session, bed: Bed) -> None:
    """Discharge: closes the stay and sends the bed to cleaning."""
    assignment = open_assignment(db, bed.id)
    if assignment is None or bed.status != "occupied":
        raise AppError(409, "This bed has no patient to discharge.")
    stamp = now()
    assignment.discharge_ordered_at = assignment.discharge_ordered_at or stamp
    assignment.released_at = stamp
    bed.status = "cleaning"
    if patient := db.get(Patient, assignment.patient_id):
        patient.status = "discharged"
    emit(db, "bed.updated", id=bed.id)
