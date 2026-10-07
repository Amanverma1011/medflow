from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import AppError
from app.core.ratelimit import rate_limit
from app.models import Patient, PatientProfile, Role, User
from app.schemas.requests import LoginRequest, ProfileUpdate, RegisterRequest
from app.security import audit
from app.security.auth import (REFRESH_COOKIE, create_access_token, current_user, doctor_of, hash_password,
                               issue_refresh_token, patient_of, revoke_refresh_token, rotate_refresh_token,
                               verify_password)
from app.security.rbac import STAFF_ROLES

router = APIRouter(prefix="/auth", tags=["auth"])
# Verified against when the email is unknown, so response time does not reveal which accounts exist.
_DUMMY_HASH = hash_password("timing-equaliser")


def _home(roles: list[str]) -> str:
    if "patient" in roles and not STAFF_ROLES & set(roles):
        return "/patient/dashboard"
    if roles == ["doctor"]:
        return "/doctor/dashboard"
    if "super_admin" in roles or "administrator" in roles:
        return "/admin/command-center"
    return "/admin/queue" if "receptionist" in roles else "/admin/beds"


def user_payload(db: Session, user: User) -> dict:
    patient, doctor = patient_of(db, user), doctor_of(db, user)
    return {"id": user.id, "email": user.email, "full_name": user.full_name, "roles": user.role_names,
            "permissions": sorted(user.permissions), "patient_id": patient.id if patient else None,
            "doctor_id": doctor.id if doctor else None, "home": _home(user.role_names)}


def _session(db: Session, response: Response, user: User) -> dict:
    refresh = issue_refresh_token(db, user)
    response.set_cookie(REFRESH_COOKIE, refresh, httponly=True, secure=settings.cookie_secure, samesite="lax",
                        max_age=settings.refresh_token_days * 86400, path="/api/auth")
    return {"access_token": create_access_token(user), "token_type": "bearer",
            "expires_in": settings.access_token_minutes * 60, "user": user_payload(db, user)}


@router.post("/login", dependencies=[Depends(rate_limit("login", 10, 60))])
def login(body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    valid = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not valid or not user.is_active:
        audit.record(db, request, None, "auth.login", "user", result="failure", email=body.email.lower())
        db.commit()
        raise AppError(401, "Incorrect email or password.")
    user.last_login_at = now()
    audit.record(db, request, user, "auth.login", "user", user.id)
    payload = _session(db, response, user)
    db.commit()
    return payload


@router.post("/register", status_code=201, dependencies=[Depends(rate_limit("register", 5, 300))])
def register(body: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)):
    """Self-registration always creates a patient account; staff accounts are created by a super admin."""
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise AppError(409, "An account with this email already exists.")
    user = User(email=email, full_name=body.full_name, password_hash=hash_password(body.password),
                roles=[db.scalar(select(Role).where(Role.name == "patient"))])
    db.add(user)
    db.flush()
    patient = Patient(user_id=user.id, mrn=f"MF-TMP-{user.id}", full_name=body.full_name,
                      date_of_birth=body.date_of_birth, gender=body.gender, phone=body.phone, email=email)
    db.add(patient)
    db.flush()
    patient.mrn = f"MF-{100000 + patient.id}"
    db.add(PatientProfile(patient_id=patient.id))
    audit.record(db, request, user, "auth.register", "patient", patient.id)
    payload = _session(db, response, user)
    db.commit()
    return payload


@router.post("/refresh")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise AppError(401, "Please sign in to continue.")
    user = rotate_refresh_token(db, token)
    payload = _session(db, response, user)
    db.commit()
    return payload


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    if token := request.cookies.get(REFRESH_COOKIE):
        revoke_refresh_token(db, token)
        db.commit()
    response.delete_cookie(REFRESH_COOKIE, path="/api/auth")


@router.get("/me")
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    payload = user_payload(db, user)
    if patient := patient_of(db, user):
        profile = db.scalar(select(PatientProfile).where(PatientProfile.patient_id == patient.id))
        payload["profile"] = {
            "mrn": patient.mrn, "date_of_birth": patient.date_of_birth, "gender": patient.gender,
            "phone": patient.phone, "address": profile.address if profile else "",
            "emergency_contact": profile.emergency_contact if profile else "",
            "allergies": profile.allergies if profile else "", "blood_group": profile.blood_group if profile else "",
            "insurance_provider": profile.insurance_provider if profile else ""}
    return payload


@router.patch("/me")
def update_me(body: ProfileUpdate, request: Request, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    changes = body.model_dump(exclude_none=True)
    patient = patient_of(db, user)
    if "full_name" in changes:
        user.full_name = changes["full_name"]
        if patient:
            patient.full_name = changes["full_name"]
    if patient:
        if "phone" in changes:
            patient.phone = changes["phone"]
        profile = db.scalar(select(PatientProfile).where(PatientProfile.patient_id == patient.id))
        for field in ("address", "emergency_contact", "allergies"):
            if field in changes and profile:
                setattr(profile, field, changes[field])
    audit.record(db, request, user, "profile.update", "user", user.id, detail=", ".join(sorted(changes)))
    db.commit()
    return me(user, db)
