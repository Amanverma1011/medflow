from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.realtime import hub
from app.models import Notification, User
from app.models.identity import Role, user_roles


def emit(db: Session, event_type: str, user_ids: set[int] | None = None, **payload) -> None:
    """Queue a realtime event; it is published only after the transaction commits,
    so clients that refetch on the event always see the new state."""
    db.info.setdefault("events", []).append((event_type, user_ids, payload))


@event.listens_for(SessionLocal, "after_commit")
def _publish(db: Session) -> None:
    for event_type, user_ids, payload in db.info.pop("events", []):
        hub.publish(event_type, user_ids, **payload)


@event.listens_for(SessionLocal, "after_rollback")
def _discard(db: Session) -> None:
    db.info.pop("events", None)


def notify(db: Session, user_id: int | None, type: str, title: str, body: str = "", severity: str = "info",
           link: str = "") -> None:
    if user_id is None:  # e.g. a walk-in patient without a portal account
        return
    db.add(Notification(user_id=user_id, type=type, title=title, body=body, severity=severity, link=link))
    emit(db, "notification.new", {user_id})


def notify_roles(db: Session, roles: tuple[str, ...], type: str, title: str, body: str = "",
                 severity: str = "info", link: str = "") -> None:
    ids = db.scalars(select(User.id).join(user_roles).join(Role).where(Role.name.in_(roles),
                                                                      User.is_active.is_(True))).all()
    for user_id in set(ids):
        notify(db, user_id, type, title, body, severity, link)
