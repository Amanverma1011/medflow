"""SELECT-only role for the Operations Copilot.

The grants are column-level on purpose: even if SQL validation were bypassed,
this role cannot read names, contact details, credentials, clinical notes or
free-text feedback.

Revision ID: 0002
Revises: 0001
"""
import re

from alembic import op
from sqlalchemy import text

from app.core.config import settings

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

GRANTS = {
    "departments": "id, name, code, floor, open_hour, close_hour",
    "doctors": "id, user_id, department_id, specialty, avg_consult_minutes, shift_start, shift_end, is_available",
    "users": "id, full_name",
    "patients": "id, gender, date_of_birth, primary_department_id, status, created_at",
    "appointments": "id, patient_id, doctor_id, department_id, scheduled_at, duration_minutes, status, "
                    "appointment_type, checked_in_at, started_at, completed_at, created_at",
    "queues": "id, doctor_id, department_id, queue_date",
    "queue_entries": "id, queue_id, status, priority, joined_at, called_at, completed_at",
    "wards": "id, name, department_id, floor, ward_type",
    "beds": "id, ward_id, label, status, updated_at",
    "bed_assignments": "id, bed_id, assigned_at, expected_discharge_at, discharge_ordered_at, released_at",
    "visits": "id, doctor_id, department_id, started_at, ended_at",
    "feedback": "id, department_id, doctor_id, overall, wait_time, staff, doctor, cleanliness, communication, "
                "appointment_experience, nps, sentiment, category, urgency, theme, created_at",
    "complaints": "id, department_id, category, urgency, status, created_at, resolved_at",
    "ai_insights": "id, title, severity, category, confidence, status, department_id, created_at",
}


def _role() -> str:
    role = settings.analytics_db_user
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", role):
        raise ValueError("ANALYTICS_DB_USER must be a plain lowercase identifier")
    return role


def upgrade() -> None:
    role = _role()
    password = settings.analytics_db_password.replace("'", "''")
    exists = op.get_bind().execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar()
    op.execute(f"{'ALTER' if exists else 'CREATE'} ROLE {role} LOGIN PASSWORD '{password}'")
    op.execute(f"ALTER ROLE {role} SET default_transaction_read_only = on")
    op.execute(f"ALTER ROLE {role} SET statement_timeout = '5s'")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {role}")
    for table, columns in GRANTS.items():
        op.execute(f"GRANT SELECT ({columns}) ON {table} TO {role}")


def downgrade() -> None:
    role = _role()
    for table in GRANTS:
        op.execute(f"REVOKE ALL ON {table} FROM {role}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {role}")
    op.execute(f"DROP ROLE IF EXISTS {role}")
