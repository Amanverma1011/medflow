"""Doctors, departments and staff directory."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.analytics.metrics import rows
from app.api.deps import like
from app.core.clock import now, today_start
from app.core.db import get_db
from app.core.errors import AppError
from app.models import Doctor, User
from app.security.auth import current_user, require
from app.services.appointments import day_slots

router = APIRouter(tags=["directory"])
MAX_BOOKING_DAYS = 60


@router.get("/doctors")
def list_doctors(q: str | None = Query(None, max_length=80), department_id: int | None = Query(None, ge=1),
                 _: User = Depends(current_user), db: Session = Depends(get_db)):
    t0 = today_start()
    return rows(db, """
        SELECT doc.id, u.full_name AS name, d.id AS department_id, d.name AS department, doc.specialty, doc.room,
               doc.years_experience, doc.shift_start, doc.shift_end, doc.is_available, doc.avg_consult_minutes,
               (:hour >= doc.shift_start AND :hour < doc.shift_end AND doc.is_available) AS on_shift,
               (SELECT ROUND(AVG(f.doctor)::numeric, 1)::float FROM feedback f WHERE f.doctor_id = doc.id) AS rating,
               (SELECT COUNT(*) FROM feedback f WHERE f.doctor_id = doc.id) AS reviews,
               (SELECT COUNT(*) FROM appointments a WHERE a.doctor_id = doc.id AND a.scheduled_at >= :t0
                    AND a.scheduled_at < :t1 AND a.status <> 'cancelled') AS patients_today
        FROM doctors doc JOIN users u ON u.id = doc.user_id JOIN departments d ON d.id = doc.department_id
        WHERE (CAST(:dept AS int) IS NULL OR doc.department_id = :dept)
          AND (CAST(:like AS text) IS NULL OR u.full_name ILIKE :like OR doc.specialty ILIKE :like
               OR d.name ILIKE :like)
        ORDER BY d.id, u.full_name""", dept=department_id, like=like(q), t0=t0, t1=t0 + timedelta(days=1),
                hour=now().hour)


@router.get("/doctors/{doctor_id}/slots")
def doctor_slots(doctor_id: int, day: date, _: User = Depends(current_user), db: Session = Depends(get_db)):
    doctor = db.get(Doctor, doctor_id)
    if doctor is None:
        raise AppError(404, "Doctor not found.")
    today = now().date()
    if not today <= day <= today + timedelta(days=MAX_BOOKING_DAYS):
        raise AppError(400, f"Appointments can be booked up to {MAX_BOOKING_DAYS} days ahead.")
    return {"doctor_id": doctor.id, "day": day, "slots": day_slots(db, doctor, day)}


@router.get("/departments")
def list_departments(_: User = Depends(current_user), db: Session = Depends(get_db)):
    t0 = today_start()
    return rows(db, """
        SELECT d.id, d.name, d.code, d.floor, d.location, d.description, d.open_hour, d.close_hour,
               (SELECT COUNT(*) FROM doctors doc WHERE doc.department_id = d.id) AS doctors,
               (SELECT COUNT(*) FROM appointments a WHERE a.department_id = d.id AND a.scheduled_at >= :t0
                    AND a.scheduled_at < :t1 AND a.status <> 'cancelled') AS patients_today,
               (SELECT COUNT(*) FROM appointments a WHERE a.department_id = d.id AND a.scheduled_at >= :t0
                    AND a.status IN ('waiting', 'checked_in')) AS waiting,
               (SELECT ROUND(AVG(EXTRACT(EPOCH FROM (a.started_at - a.checked_in_at)) / 60))::int
                    FROM appointments a WHERE a.department_id = d.id AND a.started_at >= :week
                    AND a.checked_in_at IS NOT NULL) AS avg_wait_7d,
               (SELECT ROUND(AVG(f.overall)::numeric, 2)::float FROM feedback f WHERE f.department_id = d.id
                    AND f.created_at >= :month) AS satisfaction
        FROM departments d ORDER BY d.id""", t0=t0, t1=t0 + timedelta(days=1), week=now() - timedelta(days=7),
                month=now() - timedelta(days=30))


@router.get("/staff")
def list_staff(_: User = Depends(require("staff:read")), db: Session = Depends(get_db)):
    return rows(db, """
        SELECT s.id, u.full_name AS name, u.email, s.staff_type, s.shift, d.name AS department, u.is_active
        FROM staff s JOIN users u ON u.id = s.user_id LEFT JOIN departments d ON d.id = s.department_id
        ORDER BY s.staff_type, u.full_name""")
