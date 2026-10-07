from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.clock import now
from app.core.db import Base
from app.models.hospital import _in

FEEDBACK_CATEGORIES = ("waiting_time", "staff_behavior", "doctor_communication", "billing", "cleanliness",
                       "appointment", "facilities", "pharmacy", "emergency_care", "general")


class Feedback(Base):
    __tablename__ = "feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), index=True)
    doctor_id: Mapped[int | None] = mapped_column(ForeignKey("doctors.id"))
    visit_id: Mapped[int | None] = mapped_column(ForeignKey("visits.id", ondelete="SET NULL"))
    overall: Mapped[int]
    wait_time: Mapped[int]
    staff: Mapped[int]
    doctor: Mapped[int]
    cleanliness: Mapped[int]
    communication: Mapped[int]
    appointment_experience: Mapped[int]
    nps: Mapped[int]
    comment: Mapped[str] = mapped_column(Text, default="")
    # Filled in by the feedback classifier
    sentiment: Mapped[str] = mapped_column(String(10), default="neutral", index=True)
    category: Mapped[str] = mapped_column(String(24), default="general", index=True)
    urgency: Mapped[str] = mapped_column(String(8), default="low")
    theme: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(default=now, index=True)
    __table_args__ = (
        CheckConstraint("overall BETWEEN 1 AND 5"), CheckConstraint("nps BETWEEN 0 AND 10"),
        CheckConstraint(_in("sentiment", ("positive", "neutral", "negative"))),
        CheckConstraint(_in("category", FEEDBACK_CATEGORIES)),
        CheckConstraint(_in("urgency", ("low", "medium", "high"))),
    )


class Complaint(Base):
    __tablename__ = "complaints"
    id: Mapped[int] = mapped_column(primary_key=True)
    feedback_id: Mapped[int | None] = mapped_column(ForeignKey("feedback.id", ondelete="CASCADE"), unique=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"))
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    category: Mapped[str] = mapped_column(String(24))
    urgency: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(12), default="open", index=True)
    description: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=now, index=True)
    resolved_at: Mapped[datetime | None]
    __table_args__ = (CheckConstraint(_in("status", ("open", "in_review", "resolved"))),)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(String(400), default="")
    severity: Mapped[str] = mapped_column(String(10), default="info")
    link: Mapped[str] = mapped_column(String(160), default="")
    is_read: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(default=now)
    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),
                      CheckConstraint(_in("severity", ("info", "success", "warning", "critical"))))


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    user_email: Mapped[str] = mapped_column(String(255), default="")
    action: Mapped[str] = mapped_column(String(64), index=True)
    resource_type: Mapped[str] = mapped_column(String(40), default="")
    resource_id: Mapped[str] = mapped_column(String(40), default="")
    result: Mapped[str] = mapped_column(String(12), default="success")
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(200), default="")
    detail: Mapped[str] = mapped_column(String(255), default="")  # never clinical content
    created_at: Mapped[datetime] = mapped_column(default=now, index=True)
