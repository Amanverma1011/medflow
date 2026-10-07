"""Request bodies. Everything arriving from a client is validated here before it reaches a service."""
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, NaiveDatetime, field_validator

Rating = Field(ge=1, le=5)
Text255 = Field(default="", max_length=255)


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _strong(password: str) -> str:
    if not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        raise ValueError("Password must contain at least one letter and one number")
    return password


# ----------------------------------------------------------------------------- auth & users
class LoginRequest(Body):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class RegisterRequest(Body):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)  # bcrypt ignores bytes past 72
    full_name: str = Field(min_length=2, max_length=120)
    date_of_birth: date
    gender: Literal["Female", "Male", "Other"]
    phone: str = Field(default="", max_length=32)

    _password = field_validator("password")(_strong)

    @field_validator("date_of_birth")
    @classmethod
    def _past(cls, v: date) -> date:
        if v >= date.today() or v.year < 1900:
            raise ValueError("Enter a valid date of birth")
        return v


class ProfileUpdate(Body):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=255)
    emergency_contact: str | None = Field(default=None, max_length=160)
    allergies: str | None = Field(default=None, max_length=255)


class UserCreate(Body):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=120)
    password: str = Field(min_length=8, max_length=72)
    roles: list[str] = Field(min_length=1, max_length=3)

    _password = field_validator("password")(_strong)


class UserUpdate(Body):
    is_active: bool | None = None
    roles: list[str] | None = Field(default=None, min_length=1, max_length=3)


# ----------------------------------------------------------------------------- clinical workflow
class PatientCreate(Body):
    full_name: str = Field(min_length=2, max_length=120)
    date_of_birth: date
    gender: Literal["Female", "Male", "Other"]
    phone: str = Field(default="", max_length=32)
    email: EmailStr | None = None
    primary_department_id: int | None = Field(default=None, ge=1)


class AppointmentCreate(Body):
    patient_id: int | None = Field(default=None, ge=1)  # ignored for patients: always their own record
    doctor_id: int = Field(ge=1)
    scheduled_at: NaiveDatetime
    appointment_type: Literal["new", "follow_up", "procedure"] = "new"
    reason: str = Text255


class AppointmentUpdate(Body):
    scheduled_at: NaiveDatetime | None = None
    status: Literal["cancelled", "no_show"] | None = None


class CheckInRequest(Body):
    appointment_id: int = Field(ge=1)


class TransferRequest(Body):
    doctor_id: int = Field(ge=1)


class PrescriptionIn(Body):
    medication: str = Field(min_length=2, max_length=120)
    dosage: str = Field(min_length=1, max_length=60)
    frequency: str = Field(min_length=1, max_length=60)
    duration_days: int = Field(default=30, ge=1, le=365)
    instructions: str = Text255


class CompleteConsultation(Body):
    note: str = Field(default="", max_length=4000)
    prescription: PrescriptionIn | None = None


class BedStatusUpdate(Body):
    status: Literal["available", "cleaning", "maintenance", "reserved"]


class BedAssign(Body):
    patient_id: int = Field(ge=1)
    expected_discharge_at: NaiveDatetime | None = None


class FeedbackCreate(Body):
    department_id: int | None = Field(default=None, ge=1)
    doctor_id: int | None = Field(default=None, ge=1)
    visit_id: int | None = Field(default=None, ge=1)
    overall: int = Rating
    wait_time: int = Rating
    staff: int = Rating
    doctor: int = Rating
    cleanliness: int = Rating
    communication: int = Rating
    appointment_experience: int = Rating
    nps: int = Field(ge=0, le=10)
    comment: str = Field(default="", max_length=2000)


# ----------------------------------------------------------------------------- AI
class ChatRequest(Body):
    message: str = Field(min_length=1, max_length=1000)
    conversation_id: int | None = Field(default=None, ge=1)


class MessageFeedback(Body):
    value: Literal[-1, 0, 1]


class QuestionRequest(Body):
    question: str = Field(min_length=2, max_length=500)


class IngestRequest(Body):
    document_id: int | None = Field(default=None, ge=1)  # omit to re-index every document


class DocumentUpdate(Body):
    is_active: bool | None = None
    archived: bool | None = None
