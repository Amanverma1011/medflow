import csv
import io
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from fpdf import FPDF
from sqlalchemy.orm import Session

from app.analytics import metrics
from app.analytics.metrics import FILTER, WAIT, Scope, rows
from app.core.clock import now
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import AppError
from app.models import User
from app.security import audit
from app.security.auth import require

router = APIRouter(prefix="/reports", tags=["reports"])
MAX_RANGE_DAYS = 92


def _daily_operations(db: Session, s: Scope) -> list[dict]:
    return rows(db, f"""
        SELECT a.scheduled_at::date AS day,
               COUNT(*) FILTER (WHERE a.status <> 'cancelled') AS patients,
               COUNT(*) FILTER (WHERE a.status = 'completed') AS completed,
               COUNT(*) FILTER (WHERE a.status = 'no_show') AS no_shows,
               COUNT(*) FILTER (WHERE a.status = 'cancelled') AS cancelled,
               ROUND(AVG({WAIT})::numeric, 1) AS avg_wait_min,
               ROUND(AVG(EXTRACT(EPOCH FROM (a.completed_at - a.started_at)) / 60)::numeric, 1) AS avg_consult_min
        FROM appointments a WHERE a.scheduled_at >= :start AND a.scheduled_at < :end {FILTER}
        GROUP BY 1 ORDER BY 1""", **s.params)


def _weekly_experience(db: Session, s: Scope) -> list[dict]:
    return rows(db, """
        SELECT date_trunc('week', f.created_at)::date AS week_starting, COUNT(*) AS responses,
               ROUND(AVG(f.overall)::numeric, 2) AS satisfaction,
               ROUND(((COUNT(*) FILTER (WHERE f.nps >= 9) - COUNT(*) FILTER (WHERE f.nps <= 6)) * 100.0
                      / COUNT(*))::numeric, 0) AS nps,
               ROUND((COUNT(*) FILTER (WHERE f.sentiment = 'negative') * 100.0 / COUNT(*))::numeric, 1)
                   AS negative_pct,
               COUNT(*) FILTER (WHERE f.urgency = 'high') AS high_urgency
        FROM feedback f WHERE f.created_at >= :start AND f.created_at < :end
          AND (CAST(:dept AS int) IS NULL OR f.department_id = :dept)
        GROUP BY 1 ORDER BY 1""", start=s.start, end=s.end, dept=s.dept)


def _department_performance(db: Session, s: Scope) -> list[dict]:
    return rows(db, f"""
        SELECT d.name AS department, COUNT(*) FILTER (WHERE a.status <> 'cancelled') AS patients,
               COUNT(*) FILTER (WHERE a.status = 'completed') AS completed,
               ROUND((COUNT(*) FILTER (WHERE a.status = 'no_show') * 100.0
                      / NULLIF(COUNT(*) FILTER (WHERE a.status IN ('completed', 'no_show')), 0))::numeric, 1)
                   AS no_show_pct,
               ROUND(AVG({WAIT})::numeric, 1) AS avg_wait_min,
               (SELECT ROUND(AVG(f.overall)::numeric, 2) FROM feedback f WHERE f.department_id = d.id
                    AND f.created_at >= :start AND f.created_at < :end) AS satisfaction
        FROM departments d JOIN appointments a ON a.department_id = d.id
        WHERE a.scheduled_at >= :start AND a.scheduled_at < :end {FILTER}
        GROUP BY d.id, d.name ORDER BY d.name""", **s.params)


def _doctor_utilization(db: Session, s: Scope) -> list[dict]:
    return [{"doctor": d["doctor"], "department": d["department"], "patients": d["patients"],
             "scheduled_hours": d["scheduled_hours"], "consultation_hours": d["consultation_hours"],
             "idle_hours": d["idle_hours"], "overtime_hours": d["overtime_hours"],
             "utilization_pct": d["utilization"], "avg_consult_min": d["avg_consult_minutes"]}
            for d in metrics.with_utilization(metrics.doctor_utilization(db, s))]


def _appointment_analytics(db: Session, s: Scope) -> list[dict]:
    return rows(db, f"""
        SELECT d.name AS department, a.appointment_type AS type, a.status, COUNT(*) AS appointments
        FROM appointments a JOIN departments d ON d.id = a.department_id
        WHERE a.scheduled_at >= :start AND a.scheduled_at < :end {FILTER}
        GROUP BY 1, 2, 3 ORDER BY 1, 2, 3""", **s.params)


def _bed_occupancy(db: Session, s: Scope) -> list[dict]:
    stats = {w["ward"]: w for w in metrics.beds(db)["ward_stats"]["data"]}
    return [{"ward": w["name"], "beds": w["total"], "occupied": w["occupied"], "available": w["available"],
             "cleaning": w["cleaning"], "maintenance": w["maintenance"], "reserved": w["reserved"],
             "occupancy_pct": round(w["occupied"] / w["total"] * 100, 1),
             "avg_stay_days_30d": stats[w["name"]]["avg_stay_days"], "admissions_30d": stats[w["name"]]["admissions"]}
            for w in metrics.beds_by_ward(db)]


def _ai_insights(db: Session, s: Scope) -> list[dict]:
    return rows(db, "SELECT severity, title, description, impact, recommendation, "
                    "ROUND((confidence * 100)::numeric, 0) AS confidence_pct, created_at "
                    "FROM ai_insights WHERE status = 'active' ORDER BY created_at DESC")


REPORTS = {
    "daily-operations": ("Daily Hospital Operations", _daily_operations),
    "patient-experience": ("Weekly Patient Experience", _weekly_experience),
    "department-performance": ("Department Performance", _department_performance),
    "doctor-utilization": ("Doctor Utilization", _doctor_utilization),
    "appointments": ("Appointment Analytics", _appointment_analytics),
    "bed-occupancy": ("Bed Occupancy", _bed_occupancy),
    "ai-insights": ("AI Insights (recommendations for review)", _ai_insights),
}


def _text(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


def _csv(data: list[dict]) -> bytes:
    out = io.StringIO()
    if data:
        writer = csv.DictWriter(out, fieldnames=list(data[0]))
        writer.writeheader()
        writer.writerows({k: _text(v) for k, v in row.items()} for row in data)
    return out.getvalue().encode("utf-8-sig")  # BOM so Excel opens it as UTF-8


def _latin(text: str) -> str:
    """fpdf's built-in fonts are Latin-1 only."""
    for src, dst in (("–", "-"), ("—", "-"), ("·", "-"), ("“", '"'), ("”", '"'), ("’", "'"), ("×", "x"), ("≥", ">=")):
        text = text.replace(src, dst)
    return text.encode("latin-1", "replace").decode("latin-1")


def _pdf(title: str, subtitle: str, data: list[dict]) -> bytes:
    pdf = FPDF(orientation="L", format="A4")
    pdf.set_auto_page_break(True, margin=12)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 9, _latin(f"{settings.hospital_name} - {title}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=9)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(0, 6, _latin(subtitle), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, "Synthetic demo data. Not for clinical use.", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)
    if not data:
        pdf.cell(0, 8, "No data for the selected filters.")
    else:
        pdf.set_font("Helvetica", size=8)
        with pdf.table(text_align="LEFT", line_height=5) as table:
            header = table.row()
            for column in data[0]:
                header.cell(_latin(column.replace("_", " ").title()))
            for row in data:
                line = table.row()
                for value in row.values():
                    line.cell(_latin(_text(value)))
    return bytes(pdf.output())


@router.get("")
def list_reports(_: User = Depends(require("reports:read"))):
    return [{"key": key, "title": title} for key, (title, _builder) in REPORTS.items()]


@router.get("/{kind}")
def get_report(kind: str, request: Request, date_from: date | None = None, date_to: date | None = None,
               department_id: int | None = Query(None, ge=1), format: Literal["json", "csv", "pdf"] = "json",
               user: User = Depends(require("reports:read")), db: Session = Depends(get_db)):
    if kind not in REPORTS:
        raise AppError(404, "Unknown report.")
    end_day = date_to or now().date()
    start_day = date_from or end_day - timedelta(days=6)
    if start_day > end_day:
        raise AppError(400, "The start date must be on or before the end date.")
    if (end_day - start_day).days > MAX_RANGE_DAYS:
        raise AppError(400, f"Reports cover at most {MAX_RANGE_DAYS} days.")
    s = Scope(datetime.combine(start_day, datetime.min.time()),
              datetime.combine(end_day + timedelta(days=1), datetime.min.time()), department_id)
    title, builder = REPORTS[kind]
    data = builder(db, s)
    if format == "json":
        return {"key": kind, "title": title, "date_from": start_day, "date_to": end_day,
                "columns": list(data[0]) if data else [], "rows": data}
    audit.record(db, request, user, "report.export", "report", kind, detail=f"{format} {start_day}..{end_day}")
    db.commit()
    filename = f"medflow-{kind}-{start_day}-to-{end_day}.{format}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if format == "csv":
        return Response(_csv(data), media_type="text/csv; charset=utf-8", headers=headers)
    return Response(_pdf(title, f"{start_day:%d %b %Y} to {end_day:%d %b %Y}", data), media_type="application/pdf",
                    headers=headers)
