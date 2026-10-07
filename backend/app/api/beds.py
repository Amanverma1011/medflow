from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.analytics import metrics
from app.analytics.metrics import rows
from app.core.clock import now
from app.core.db import get_db
from app.core.errors import AppError
from app.models import Bed, Patient, User
from app.schemas.requests import BedAssign, BedStatusUpdate
from app.security import audit
from app.security.auth import require
from app.services import beds as service

router = APIRouter(prefix="/beds", tags=["beds"])


@router.get("")
def bed_map(user: User = Depends(require("beds:read")), db: Session = Depends(get_db)):
    """Ward-by-ward bed map. Occupant names are included only for roles allowed to see patients."""
    names = "patients:read" in user.permissions
    beds = rows(db, """
        SELECT b.id, b.ward_id, b.label, b.status, b.updated_at, ba.patient_id, p.full_name AS patient,
               ba.assigned_at, ba.expected_discharge_at
        FROM beds b
        LEFT JOIN bed_assignments ba ON ba.bed_id = b.id AND ba.released_at IS NULL
        LEFT JOIN patients p ON p.id = ba.patient_id
        ORDER BY b.ward_id, b.label""")
    wards = rows(db, "SELECT w.id, w.name, w.floor, w.ward_type, d.name AS department FROM wards w "
                     "LEFT JOIN departments d ON d.id = w.department_id ORDER BY w.id")
    for w in wards:
        w["beds"] = [b for b in beds if b["ward_id"] == w["id"]]
        occupied = sum(1 for b in w["beds"] if b["status"] == "occupied")
        w["occupancy_rate"] = round(occupied / len(w["beds"]) * 100) if w["beds"] else 0
    if not names:
        for b in beds:
            b["patient"] = None
    return {"wards": wards, "summary": metrics.bed_summary(db)}


@router.get("/analytics")
def bed_analytics(_: User = Depends(require("beds:read")), db: Session = Depends(get_db)):
    return metrics.beds(db)


@router.get("/tasks")
def ward_tasks(_: User = Depends(require("beds:read")), db: Session = Depends(get_db)):
    """Ward work derived from live bed state: turnarounds to finish and discharges coming up."""
    current = now()
    cleaning = rows(db, """
        SELECT b.id AS bed_id, b.label, w.name AS ward, b.updated_at FROM beds b JOIN wards w ON w.id = b.ward_id
        WHERE b.status = 'cleaning' ORDER BY b.updated_at""")
    discharges = rows(db, """
        SELECT b.id AS bed_id, b.label, w.name AS ward, ba.expected_discharge_at
        FROM bed_assignments ba JOIN beds b ON b.id = ba.bed_id JOIN wards w ON w.id = b.ward_id
        WHERE ba.released_at IS NULL AND ba.expected_discharge_at <= :horizon
        ORDER BY ba.expected_discharge_at""", horizon=current + timedelta(hours=8))
    return {"tasks": (
        [{"type": "turnaround", "bed_id": c["bed_id"], "title": f"Finish cleaning bed {c['label']}",
          "detail": c["ward"], "due": c["updated_at"] + timedelta(hours=1)} for c in cleaning]
        + [{"type": "discharge", "bed_id": d["bed_id"], "title": f"Planned discharge · bed {d['label']}",
            "detail": d["ward"], "due": d["expected_discharge_at"],
            "overdue": d["expected_discharge_at"] < current} for d in discharges])}


def _bed(db: Session, bed_id: int) -> Bed:
    bed = db.get(Bed, bed_id)
    if bed is None:
        raise AppError(404, "Bed not found.")
    return bed


@router.patch("/{bed_id}")
def update_status(bed_id: int, body: BedStatusUpdate, request: Request,
                  user: User = Depends(require("beds:manage")), db: Session = Depends(get_db)):
    bed = _bed(db, bed_id)
    before = bed.status
    service.set_status(db, bed, body.status)
    audit.record(db, request, user, "bed.status", "bed", bed.id, detail=f"{before} -> {bed.status}")
    db.commit()
    return {"id": bed.id, "status": bed.status}


@router.post("/{bed_id}/assign", status_code=201)
def assign(bed_id: int, body: BedAssign, request: Request, user: User = Depends(require("beds:manage")),
           db: Session = Depends(get_db)):
    bed, patient = _bed(db, bed_id), db.get(Patient, body.patient_id)
    if patient is None:
        raise AppError(404, "Patient not found.")
    if body.expected_discharge_at and body.expected_discharge_at <= now():
        raise AppError(400, "Expected discharge must be in the future.")
    service.assign(db, bed, patient, body.expected_discharge_at)
    audit.record(db, request, user, "bed.assign", "bed", bed.id, detail=f"patient {patient.id}")
    db.commit()
    return {"id": bed.id, "status": bed.status}


@router.post("/{bed_id}/release")
def release(bed_id: int, request: Request, user: User = Depends(require("beds:manage")),
            db: Session = Depends(get_db)):
    bed = _bed(db, bed_id)
    service.release(db, bed)
    audit.record(db, request, user, "bed.release", "bed", bed.id)
    db.commit()
    return {"id": bed.id, "status": bed.status}
