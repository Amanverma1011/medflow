import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.clock import now
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import AppError
from app.models import Doctor, Patient, RefreshToken, User

ALGORITHM = "HS256"
REFRESH_COOKIE = "medflow_refresh"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def _encode(claims: dict, ttl: timedelta) -> str:
    issued = datetime.now(timezone.utc)
    return jwt.encode({**claims, "iat": issued, "exp": issued + ttl}, settings.jwt_secret, ALGORITHM)


def _decode(token: str, typ: str) -> dict:
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        raise AppError(401, "Your session is invalid or has expired. Please sign in again.")
    if claims.get("typ") != typ:
        raise AppError(401, "Your session is invalid or has expired. Please sign in again.")
    return claims


def create_access_token(user: User) -> str:
    return _encode({"sub": str(user.id), "typ": "access"}, timedelta(minutes=settings.access_token_minutes))


def issue_refresh_token(db: Session, user: User) -> str:
    jti = secrets.token_urlsafe(32)
    db.add(RefreshToken(user_id=user.id, jti=jti, expires_at=now() + timedelta(days=settings.refresh_token_days)))
    return _encode({"sub": str(user.id), "typ": "refresh", "jti": jti}, timedelta(days=settings.refresh_token_days))


def rotate_refresh_token(db: Session, token: str) -> User:
    """Single-use refresh tokens. Replaying a used one revokes the whole family."""
    claims = _decode(token, "refresh")
    row = db.scalar(select(RefreshToken).where(RefreshToken.jti == claims["jti"]))
    if row is None:
        raise AppError(401, "Your session has expired. Please sign in again.")
    if row.revoked_at is not None:
        revoke_all(db, row.user_id)
        db.commit()
        raise AppError(401, "Your session has expired. Please sign in again.")
    row.revoked_at = now()
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AppError(401, "This account is not active.")
    return user


def revoke_refresh_token(db: Session, token: str) -> None:
    try:
        claims = _decode(token, "refresh")
    except AppError:
        return
    db.execute(update(RefreshToken).where(RefreshToken.jti == claims["jti"], RefreshToken.revoked_at.is_(None))
               .values(revoked_at=now()))


def revoke_all(db: Session, user_id: int) -> None:
    db.execute(update(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
               .values(revoked_at=now()))


def user_from_access_token(db: Session, token: str) -> User:
    user = db.get(User, int(_decode(token, "access")["sub"]))
    if user is None or not user.is_active:
        raise AppError(401, "This account is not active.")
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise AppError(401, "Please sign in to continue.")
    return user_from_access_token(db, header[7:])


def require(*permissions: str):
    """Dependency: the caller must hold every listed permission."""

    def dependency(user: User = Depends(current_user)) -> User:
        missing = set(permissions) - user.permissions
        if missing:
            raise AppError(403, "You don't have permission to do that.")
        return user

    return dependency


def require_any(*permissions: str):
    def dependency(user: User = Depends(current_user)) -> User:
        if not set(permissions) & user.permissions:
            raise AppError(403, "You don't have permission to do that.")
        return user

    return dependency


def patient_of(db: Session, user: User) -> Patient | None:
    return db.scalar(select(Patient).where(Patient.user_id == user.id))


def doctor_of(db: Session, user: User) -> Doctor | None:
    return db.scalar(select(Doctor).where(Doctor.user_id == user.id))


def authorize_patient_access(db: Session, user: User, patient_id: int) -> None:
    """Patients may only ever reach their own record; staff need patients:read."""
    if "patients:read" in user.permissions:
        return
    own = patient_of(db, user)
    if own is None or own.id != patient_id:
        raise AppError(403, "You don't have permission to view this record.")
