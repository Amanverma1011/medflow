from datetime import date

from sqlalchemy.orm import Session

from app.analytics.metrics import rows

_DIRECTORY = """
    SELECT p.id, p.mrn, p.full_name, p.gender, p.status,
           EXTRACT(YEAR FROM age(p.date_of_birth))::int AS age, d.name AS department,
           nxt.scheduled_at AS appointment_at, nxt.status AS appointment_status, nxt.doctor,
           (SELECT MAX(v.started_at) FROM visits v WHERE v.patient_id = p.id) AS last_visit,
           COUNT(*) OVER () AS total
    FROM patients p
    LEFT JOIN departments d ON d.id = p.primary_department_id
    LEFT JOIN LATERAL (
        SELECT a.scheduled_at, a.status, u.full_name AS doctor
        FROM appointments a JOIN doctors doc ON doc.id = a.doctor_id JOIN users u ON u.id = doc.user_id
        WHERE a.patient_id = p.id AND a.status IN ('scheduled', 'checked_in', 'waiting', 'in_consultation')
        ORDER BY a.scheduled_at LIMIT 1) nxt ON TRUE
    WHERE (CAST(:like AS text) IS NULL OR p.full_name ILIKE :like OR p.mrn ILIKE :like)
      AND (CAST(:dept AS int) IS NULL OR p.primary_department_id = :dept)
      AND (CAST(:status AS text) IS NULL OR p.status = :status)
      AND (CAST(:doctor AS int) IS NULL OR EXISTS (
            SELECT 1 FROM appointments a WHERE a.patient_id = p.id AND a.doctor_id = :doctor))
      AND (CAST(:day AS date) IS NULL OR EXISTS (
            SELECT 1 FROM appointments a WHERE a.patient_id = p.id AND a.scheduled_at::date = :day))
    ORDER BY p.full_name, p.id
    LIMIT :size OFFSET :offset"""


def directory(db: Session, like: str | None, dept: int | None, doctor: int | None, status: str | None,
              day: date | None, size: int, offset: int) -> tuple[list[dict], int]:
    data = rows(db, _DIRECTORY, like=like, dept=dept, doctor=doctor, status=status, day=day, size=size,
                offset=offset)
    total = data[0]["total"] if data else 0
    for r in data:
        r.pop("total")
    return data, total


def is_patient_of(db: Session, patient_id: int, doctor_id: int) -> bool:
    return bool(rows(db, "SELECT 1 FROM appointments WHERE patient_id = :p AND doctor_id = :d LIMIT 1",
                     p=patient_id, d=doctor_id))


def profile(db: Session, patient_id: int, include_clinical: bool) -> dict | None:
    """Full patient record. Clinical content is only loaded for callers allowed to see it."""
    basic = rows(db, """
        SELECT p.id, p.mrn, p.full_name, p.gender, p.status, p.date_of_birth, p.phone, p.email, p.created_at,
               EXTRACT(YEAR FROM age(p.date_of_birth))::int AS age, d.name AS department,
               pp.blood_group, pp.allergies, pp.chronic_conditions, pp.emergency_contact, pp.address,
               pp.insurance_provider
        FROM patients p LEFT JOIN departments d ON d.id = p.primary_department_id
        LEFT JOIN patient_profiles pp ON pp.patient_id = p.id WHERE p.id = :id""", id=patient_id)
    if not basic:
        return None
    appointments = rows(db, """
        SELECT a.id, a.scheduled_at, a.status, a.appointment_type, a.reason, u.full_name AS doctor,
               d.name AS department
        FROM appointments a JOIN doctors doc ON doc.id = a.doctor_id JOIN users u ON u.id = doc.user_id
        JOIN departments d ON d.id = a.department_id
        WHERE a.patient_id = :id ORDER BY a.scheduled_at DESC LIMIT 40""", id=patient_id)
    visits = rows(db, """
        SELECT v.id, v.started_at, v.ended_at, v.summary, u.full_name AS doctor, d.name AS department,
               (SELECT string_agg(n.note, E'\n') FROM clinical_notes n WHERE n.visit_id = v.id) AS notes
        FROM visits v JOIN doctors doc ON doc.id = v.doctor_id JOIN users u ON u.id = doc.user_id
        JOIN departments d ON d.id = v.department_id
        WHERE v.patient_id = :id ORDER BY v.started_at DESC LIMIT 40""", id=patient_id)
    feedback = rows(db, "SELECT id, overall, nps, comment, sentiment, category, created_at FROM feedback "
                        "WHERE patient_id = :id ORDER BY created_at DESC LIMIT 20", id=patient_id)
    prescriptions, documents = [], []
    if include_clinical:
        prescriptions = rows(db, """
            SELECT pr.id, pr.medication, pr.dosage, pr.frequency, pr.duration_days, pr.instructions, pr.issued_at,
                   u.full_name AS doctor
            FROM prescriptions pr JOIN doctors doc ON doc.id = pr.doctor_id JOIN users u ON u.id = doc.user_id
            WHERE pr.patient_id = :id ORDER BY pr.issued_at DESC LIMIT 40""", id=patient_id)
        documents = rows(db, "SELECT id, title, doc_type, summary, issued_at FROM medical_documents "
                             "WHERE patient_id = :id ORDER BY issued_at DESC LIMIT 40", id=patient_id)
    else:
        for v in visits:
            v["notes"] = None  # visit happened; what was said stays clinical

    timeline = (
        [{"at": a["scheduled_at"], "type": "appointment", "title": f"Appointment {a['status'].replace('_', ' ')}",
          "detail": f"{a['doctor']} · {a['department']}"} for a in appointments]
        + [{"at": v["ended_at"] or v["started_at"], "type": "visit", "title": "Visit completed",
            "detail": f"{v['doctor']} · {v['department']}"} for v in visits]
        + [{"at": p["issued_at"], "type": "prescription", "title": "Prescription issued",
            "detail": p["medication"]} for p in prescriptions]
        + [{"at": d["issued_at"], "type": "document", "title": "Document added", "detail": d["title"]}
           for d in documents]
        + [{"at": f["created_at"], "type": "feedback", "title": "Feedback submitted",
            "detail": f"{f['overall']} / 5"} for f in feedback])
    timeline.sort(key=lambda e: e["at"], reverse=True)
    return {"patient": basic[0], "appointments": appointments, "visits": visits, "prescriptions": prescriptions,
            "documents": documents, "feedback": feedback, "timeline": timeline[:60],
            "clinical_access": include_clinical}
