from datetime import datetime

from sqlalchemy.orm import Session

from app.analytics.metrics import rows

_SELECT = """
    SELECT a.id, a.scheduled_at, a.duration_minutes, a.status, a.appointment_type, a.reason,
           a.checked_in_at, a.started_at, a.completed_at,
           a.patient_id, p.full_name AS patient, p.mrn,
           a.doctor_id, u.full_name AS doctor, doc.room, a.department_id, d.name AS department,
           qe.token, COUNT(*) OVER () AS total
    FROM appointments a
    JOIN patients p ON p.id = a.patient_id
    JOIN doctors doc ON doc.id = a.doctor_id JOIN users u ON u.id = doc.user_id
    JOIN departments d ON d.id = a.department_id
    LEFT JOIN queue_entries qe ON qe.appointment_id = a.id"""

_WHERE = """
    WHERE (CAST(:start AS timestamp) IS NULL OR a.scheduled_at >= :start)
      AND (CAST(:end AS timestamp) IS NULL OR a.scheduled_at < :end)
      AND (CAST(:doctor AS int) IS NULL OR a.doctor_id = :doctor)
      AND (CAST(:dept AS int) IS NULL OR a.department_id = :dept)
      AND (CAST(:patient AS int) IS NULL OR a.patient_id = :patient)
      AND (CAST(:status AS text) IS NULL OR a.status = :status)
      AND (CAST(:like AS text) IS NULL OR p.full_name ILIKE :like OR p.mrn ILIKE :like)"""


def search(db: Session, *, start: datetime | None = None, end: datetime | None = None, doctor: int | None = None,
           dept: int | None = None, patient: int | None = None, status: str | None = None, like: str | None = None,
           size: int = 25, offset: int = 0, newest_first: bool = False) -> tuple[list[dict], int]:
    order = "DESC" if newest_first else "ASC"
    data = rows(db, f"{_SELECT} {_WHERE} ORDER BY a.scheduled_at {order}, a.id LIMIT :size OFFSET :offset",
                start=start, end=end, doctor=doctor, dept=dept, patient=patient, status=status, like=like,
                size=size, offset=offset)
    total = data[0]["total"] if data else 0
    for r in data:
        r.pop("total")
    return data, total


def one(db: Session, appointment_id: int) -> dict | None:
    data = rows(db, f"{_SELECT} WHERE a.id = :id", id=appointment_id)
    if data:
        data[0].pop("total")
    return data[0] if data else None


def month_counts(db: Session, start: datetime, end: datetime, doctor: int | None, dept: int | None,
                 patient: int | None) -> list[dict]:
    """Per-day totals for the month view, so the browser never loads a month of appointments."""
    return rows(db, """
        SELECT a.scheduled_at::date AS day, COUNT(*) AS total,
               COUNT(*) FILTER (WHERE a.status = 'completed') AS completed,
               COUNT(*) FILTER (WHERE a.status IN ('scheduled', 'checked_in', 'waiting', 'in_consultation')) AS active,
               COUNT(*) FILTER (WHERE a.status IN ('cancelled', 'no_show')) AS missed
        FROM appointments a
        WHERE a.scheduled_at >= :start AND a.scheduled_at < :end
          AND (CAST(:doctor AS int) IS NULL OR a.doctor_id = :doctor)
          AND (CAST(:dept AS int) IS NULL OR a.department_id = :dept)
          AND (CAST(:patient AS int) IS NULL OR a.patient_id = :patient)
        GROUP BY 1 ORDER BY 1""", start=start, end=end, doctor=doctor, dept=dept, patient=patient)
