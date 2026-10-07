from datetime import date, datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import now
from app.core.db import Base
from app.models.hospital import _in

APPOINTMENT_STATUSES = ("scheduled", "checked_in", "waiting", "in_consultation", "completed", "cancelled", "no_show")
ACTIVE_STATUSES = ("scheduled", "checked_in", "waiting", "in_consultation")
QUEUE_STATUSES = ("waiting", "called", "in_consultation", "completed", "skipped", "transferred")


class Appointment(Base):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    scheduled_at: Mapped[datetime] = mapped_column(index=True)
    duration_minutes: Mapped[int] = mapped_column(default=20)
    status: Mapped[str] = mapped_column(String(20), default="scheduled", index=True)
    appointment_type: Mapped[str] = mapped_column(String(16), default="new")
    reason: Mapped[str] = mapped_column(String(255), default="")
    checked_in_at: Mapped[datetime | None]
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=now)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    patient = relationship("Patient", lazy="joined")
    doctor = relationship("Doctor", lazy="joined")
    __table_args__ = (
        CheckConstraint(_in("status", APPOINTMENT_STATUSES)),
        CheckConstraint(_in("appointment_type", ("new", "follow_up", "procedure", "emergency"))),
        Index("ix_appointments_doctor_time", "doctor_id", "scheduled_at"),
        Index("ix_appointments_dept_time", "department_id", "scheduled_at"),
        # A doctor cannot hold two live appointments in the same slot, even under concurrent booking.
        Index("uq_appointments_active_slot", "doctor_id", "scheduled_at", unique=True,
              postgresql_where=text(_in("status", ACTIVE_STATUSES))),
    )


class AppointmentStatusHistory(Base):
    __tablename__ = "appointment_status_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    appointment_id: Mapped[int] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(20))
    to_status: Mapped[str] = mapped_column(String(20))
    changed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    changed_at: Mapped[datetime] = mapped_column(default=now)


class Queue(Base):
    __tablename__ = "queues"
    id: Mapped[int] = mapped_column(primary_key=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id", ondelete="CASCADE"))
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    queue_date: Mapped[date]
    doctor = relationship("Doctor", lazy="joined")
    __table_args__ = (UniqueConstraint("doctor_id", "queue_date"),)


class QueueEntry(Base):
    __tablename__ = "queue_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"))
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id", ondelete="CASCADE"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), default="waiting")
    priority: Mapped[int] = mapped_column(default=0)
    joined_at: Mapped[datetime] = mapped_column(default=now)
    called_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]
    patient = relationship("Patient", lazy="joined")
    __table_args__ = (CheckConstraint(_in("status", QUEUE_STATUSES)),
                      Index("ix_queue_entries_queue_status", "queue_id", "status"))


class Visit(Base):
    __tablename__ = "visits"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"), index=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"))
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id", ondelete="SET NULL"), unique=True)
    started_at: Mapped[datetime] = mapped_column(index=True)
    ended_at: Mapped[datetime | None]
    summary: Mapped[str] = mapped_column(String(255), default="")


class ClinicalNote(Base):
    __tablename__ = "clinical_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=now)


class Prescription(Base):
    __tablename__ = "prescriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("visits.id", ondelete="SET NULL"))
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    doctor_id: Mapped[int] = mapped_column(ForeignKey("doctors.id"))
    medication: Mapped[str] = mapped_column(String(120))
    dosage: Mapped[str] = mapped_column(String(60))
    frequency: Mapped[str] = mapped_column(String(60))
    duration_days: Mapped[int] = mapped_column(default=30)
    instructions: Mapped[str] = mapped_column(String(255), default="")
    issued_at: Mapped[datetime] = mapped_column(default=now)


class MedicalDocument(Base):
    __tablename__ = "medical_documents"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    doc_type: Mapped[str] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text, default="")
    issued_at: Mapped[datetime] = mapped_column(default=now)
