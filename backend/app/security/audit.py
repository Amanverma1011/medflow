from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, User


def record(db: Session, request: Request | None, user: User | None, action: str, resource_type: str = "",
           resource_id: int | str | None = None, result: str = "success", detail: str = "",
           email: str = "") -> None:
    """Append an audit entry to the caller's transaction.

    `detail` is for short operational context (e.g. "status: waiting -> completed").
    Never pass clinical text, chat content or credentials.
    """
    db.add(AuditLog(
        user_id=user.id if user else None,
        user_email=user.email if user else email[:255],
        action=action, resource_type=resource_type,
        resource_id="" if resource_id is None else str(resource_id),
        result=result, detail=detail[:255],
        ip=(request.client.host if request and request.client else ""),
        user_agent=(request.headers.get("user-agent", "")[:200] if request else ""),
    ))
