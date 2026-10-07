from datetime import date, datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.clock import now
from app.core.db import Base

BED_STATUSES = ("available", "occupied", "cleaning", "maintenance", "reserved")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Department(Base):
    __tablename__ = "departments"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    code: Mapped[str] = mapped_column(String(2), unique=True)  # queue token prefix
    floor: Mapped[str] = mapped_column(String(40))
    location: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    open_hour: Mapped[int] = mapped_column(default=9)
    close_hour: Mapped[int] = mapped_column(default=17)


class Doctor(Base):
    __tablename__ = "doctors"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)
    specialty: Mapped[str] = mapped_column(String(120))
    room: Mapped[str] = mapped_column(String(20))
    years_experience: Mapped[int] = mapped_column(default=5)
    avg_consult_minutes: Mapped[int] = mapped_column(default=15)
    shift_start: Mapped[int] = mapped_column(default=9)
    shift_end: Mapped[int] = mapped_column(default=17)
    is_available: Mapped[bool] = mapped_column(default=True)
    user = relationship("User", lazy="joined")
    department = relationship(Department, lazy="joined")


class Staff(Base):
    __tablename__ = "staff"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    staff_type: Mapped[str] = mapped_column(String(24))
    shift: Mapped[str] = mapped_column(String(16), default="day")
    __table_args__ = (CheckConstraint(_in("staff_type", ("nurse", "receptionist", "administrator"))),)


class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), unique=True)
    mrn: Mapped[str] = mapped_column(String(16), unique=True)
    full_name: Mapped[str] = mapped_column(String(120), index=True)
    date_of_birth: Mapped[date]
    gender: Mapped[str] = mapped_column(String(16))
    phone: Mapped[str] = mapped_column(String(32), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    primary_department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=now)
    __table_args__ = (CheckConstraint(_in("status", ("active", "admitted", "discharged", "inactive"))),)


class PatientProfile(Base):
    __tablename__ = "patient_profiles"
    id: Mapped[int] = mapped_column(primary_key=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), unique=True)
    blood_group: Mapped[str] = mapped_column(String(4), default="")
    allergies: Mapped[str] = mapped_column(String(255), default="")
    chronic_conditions: Mapped[str] = mapped_column(String(255), default="")
    emergency_contact: Mapped[str] = mapped_column(String(160), default="")
    address: Mapped[str] = mapped_column(String(255), default="")
    insurance_provider: Mapped[str] = mapped_column(String(120), default="")


class Ward(Base):
    __tablename__ = "wards"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"))
    floor: Mapped[str] = mapped_column(String(40))
    ward_type: Mapped[str] = mapped_column(String(24), default="general")


class Bed(Base):
    __tablename__ = "beds"
    id: Mapped[int] = mapped_column(primary_key=True)
    ward_id: Mapped[int] = mapped_column(ForeignKey("wards.id", ondelete="CASCADE"), index=True)
    label: Mapped[str] = mapped_column(String(12))
    status: Mapped[str] = mapped_column(String(16), default="available", index=True)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)
    __table_args__ = (UniqueConstraint("ward_id", "label"), CheckConstraint(_in("status", BED_STATUSES)))


class BedAssignment(Base):
    __tablename__ = "bed_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    bed_id: Mapped[int] = mapped_column(ForeignKey("beds.id", ondelete="CASCADE"))
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id", ondelete="CASCADE"), index=True)
    assigned_at: Mapped[datetime] = mapped_column(default=now)
    expected_discharge_at: Mapped[datetime | None]
    discharge_ordered_at: Mapped[datetime | None]
    released_at: Mapped[datetime | None]
    __table_args__ = (Index("ix_bed_assignments_bed_open", "bed_id", "released_at"),
                      Index("ix_bed_assignments_assigned_at", "assigned_at"))
