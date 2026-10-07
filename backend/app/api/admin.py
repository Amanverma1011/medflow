"""User & role management, audit log, global search, system settings and demo loading."""
from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.providers import get_embedder, get_llm, get_reranker
from app.analytics.metrics import rows
from app.api.auth import _session
from app.api.deps import Page, like
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import AppError
from app.core.ratelimit import rate_limit
from app.models import AuditLog, Role, User
from app.schemas.requests import UserCreate, UserUpdate
from app.security import audit
from app.security.auth import current_user, doctor_of, hash_password, patient_of, require, revoke_all
from app.services import bootstrap

router = APIRouter(tags=["admin"])


# ------------------------------------------------------------------------------- users & roles
def _user(u: User) -> dict:
    return {"id": u.id, "email": u.email, "full_name": u.full_name, "roles": u.role_names,
            "is_active": u.is_active, "last_login_at": u.last_login_at, "created_at": u.created_at}


def _roles(db: Session, names: list[str]) -> list[Role]:
    roles = list(db.scalars(select(Role).where(Role.name.in_(names))))
    if len(roles) != len(set(names)):
        raise AppError(400, "One or more roles do not exist.")
    return roles


@router.get("/users")
def list_users(q: str | None = Query(None, max_length=80), role: str | None = Query(None, max_length=32),
               page: Page = Depends(), _: User = Depends(require("users:manage")), db: Session = Depends(get_db)):
    stmt = select(User)
    if pattern := like(q):
        stmt = stmt.where(User.full_name.ilike(pattern) | User.email.ilike(pattern))
    if role:
        stmt = stmt.where(User.roles.any(Role.name == role))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    users = db.scalars(stmt.order_by(User.full_name).limit(page.size).offset(page.offset)).all()
    return page.wrap([_user(u) for u in users], total)


@router.post("/users", status_code=201)
def create_user(body: UserCreate, request: Request, admin: User = Depends(require("users:manage")),
                db: Session = Depends(get_db)):
    email = body.email.lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise AppError(409, "An account with this email already exists.")
    user = User(email=email, full_name=body.full_name, password_hash=hash_password(body.password),
                roles=_roles(db, body.roles))
    db.add(user)
    db.flush()
    audit.record(db, request, admin, "user.create", "user", user.id, detail=f"roles: {', '.join(body.roles)}")
    db.commit()
    return _user(user)


@router.patch("/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, request: Request, admin: User = Depends(require("users:manage")),
                db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise AppError(404, "User not found.")
    if user.id == admin.id and (body.is_active is False or (body.roles and "super_admin" not in body.roles)):
        raise AppError(409, "You can't deactivate your own account or remove your own super admin role.")
    changes = []
    if body.roles is not None:
        user.roles = _roles(db, body.roles)
        changes.append(f"roles: {', '.join(body.roles)}")
    if body.is_active is not None:
        user.is_active = body.is_active
        changes.append("activated" if body.is_active else "deactivated")
        if not body.is_active:
            revoke_all(db, user.id)  # end their sessions immediately
    audit.record(db, request, admin, "user.update", "user", user.id, detail="; ".join(changes))
    db.commit()
    return _user(user)


@router.get("/roles")
def list_roles(_: User = Depends(require("users:manage")), db: Session = Depends(get_db)):
    counts = {r["name"]: r["users"] for r in rows(db, """
        SELECT r.name, COUNT(ur.user_id) AS users FROM roles r LEFT JOIN user_roles ur ON ur.role_id = r.id
        GROUP BY r.name""")}
    return [{"name": r.name, "description": r.description, "users": counts.get(r.name, 0),
             "permissions": sorted(p.code for p in r.permissions)} for r in db.scalars(select(Role).order_by(Role.id))]


# ------------------------------------------------------------------------------- audit
@router.get("/audit-logs")
def audit_logs(action: str | None = Query(None, max_length=64), result: str | None = Query(None, max_length=12),
               q: str | None = Query(None, max_length=80), page: Page = Depends(),
               _: User = Depends(require("audit:read")), db: Session = Depends(get_db)):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action))
    if result:
        stmt = stmt.where(AuditLog.result == result)
    if pattern := like(q):
        stmt = stmt.where(AuditLog.user_email.ilike(pattern) | AuditLog.action.ilike(pattern))
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    logs = db.scalars(stmt.order_by(AuditLog.id.desc()).limit(page.size).offset(page.offset)).all()
    return page.wrap([{"id": a.id, "user": a.user_email or "anonymous", "action": a.action,
                       "resource_type": a.resource_type, "resource_id": a.resource_id, "result": a.result,
                       "ip": a.ip, "device": a.user_agent, "detail": a.detail, "created_at": a.created_at}
                      for a in logs], total)


# ------------------------------------------------------------------------------- global search
@router.get("/search", dependencies=[Depends(rate_limit("search", 120, 60))])
def search(q: str = Query(min_length=2, max_length=80), user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    """Command-palette search. Each section is only searched if the caller may see that kind of record."""
    pattern, perms, results = like(q), user.permissions, []
    own_patient = patient_of(db, user)
    own_doctor = doctor_of(db, user) if user.role_names == ["doctor"] else None

    if "patients:read" in perms:
        results += [{"type": "patient", "id": r["id"], "title": r["full_name"],
                     "subtitle": f"{r['mrn']} · {r['department'] or 'No department'}"} for r in rows(db, """
            SELECT p.id, p.full_name, p.mrn, d.name AS department FROM patients p
            LEFT JOIN departments d ON d.id = p.primary_department_id
            WHERE (p.full_name ILIKE :like OR p.mrn ILIKE :like)
              AND (CAST(:doctor AS int) IS NULL OR EXISTS (
                    SELECT 1 FROM appointments a WHERE a.patient_id = p.id AND a.doctor_id = :doctor))
            ORDER BY p.full_name LIMIT 6""", like=pattern, doctor=own_doctor.id if own_doctor else None)]

    results += [{"type": "doctor", "id": r["id"], "title": r["name"],
                 "subtitle": f"{r['specialty']} · {r['department']}"} for r in rows(db, """
        SELECT doc.id, u.full_name AS name, doc.specialty, d.name AS department
        FROM doctors doc JOIN users u ON u.id = doc.user_id JOIN departments d ON d.id = doc.department_id
        WHERE u.full_name ILIKE :like OR doc.specialty ILIKE :like ORDER BY u.full_name LIMIT 5""", like=pattern)]

    results += [{"type": "department", "id": r["id"], "title": r["name"], "subtitle": r["location"]}
                for r in rows(db, "SELECT id, name, location FROM departments WHERE name ILIKE :like "
                                  "OR description ILIKE :like ORDER BY name LIMIT 4", like=pattern)]

    if "appointments:read" in perms or own_patient:
        results += [{"type": "appointment", "id": r["id"], "title": f"{r['patient']} with {r['doctor']}",
                     "subtitle": f"{r['scheduled_at']:%d %b %Y, %I:%M %p} · {r['status'].replace('_', ' ')}"}
                    for r in rows(db, """
            SELECT a.id, a.scheduled_at, a.status, p.full_name AS patient, u.full_name AS doctor
            FROM appointments a JOIN patients p ON p.id = a.patient_id
            JOIN doctors doc ON doc.id = a.doctor_id JOIN users u ON u.id = doc.user_id
            WHERE (p.full_name ILIKE :like OR u.full_name ILIKE :like)
              AND a.scheduled_at >= CURRENT_DATE - INTERVAL '1 day'
              AND (CAST(:patient AS int) IS NULL OR a.patient_id = :patient)
              AND (CAST(:doctor AS int) IS NULL OR a.doctor_id = :doctor)
            ORDER BY a.scheduled_at LIMIT 5""", like=pattern,
                                  patient=None if "appointments:read" in perms else own_patient.id,
                                  doctor=own_doctor.id if own_doctor else None)]

    if "knowledge:manage" in perms:
        results += [{"type": "document", "id": r["id"], "title": r["name"],
                     "subtitle": f"{r['kb']} knowledge base · {r['status']}"}
                    for r in rows(db, "SELECT id, name, kb, status FROM documents WHERE name ILIKE :like "
                                      "ORDER BY name LIMIT 5", like=pattern)]

    if "chat:use" in perms:
        results += [{"type": "knowledge", "id": r["id"], "title": r["section"] or r["document"],
                     "subtitle": f"{r['document']} · {r['snippet']}"} for r in rows(db, """
            SELECT c.id, c.section, d.name AS document, left(c.content, 90) AS snippet
            FROM document_chunks c JOIN documents d ON d.id = c.document_id, plainto_tsquery('english', :q) query
            WHERE d.is_active AND d.status = 'indexed' AND c.tsv @@ query
            ORDER BY ts_rank_cd(c.tsv, query) DESC LIMIT 5""", q=q)]
    return {"query": q, "results": results}


# ------------------------------------------------------------------------------- settings & demo
@router.get("/settings/system")
def system_settings(_: User = Depends(require("settings:read")), db: Session = Depends(get_db)):
    """Read-only view of runtime configuration. Secrets are never returned, only whether they are set."""
    counts = rows(db, """
        SELECT (SELECT COUNT(*) FROM users) AS users, (SELECT COUNT(*) FROM patients) AS patients,
               (SELECT COUNT(*) FROM doctors) AS doctors, (SELECT COUNT(*) FROM appointments) AS appointments,
               (SELECT COUNT(*) FROM beds) AS beds, (SELECT COUNT(*) FROM feedback) AS feedback,
               (SELECT COUNT(*) FROM documents) AS documents, (SELECT COUNT(*) FROM document_chunks) AS chunks,
               (SELECT COUNT(*) FROM audit_logs) AS audit_entries""")[0]
    llm = get_llm()
    return {
        "hospital": {"name": settings.hospital_name, "timezone": settings.hospital_tz,
                     "environment": settings.app_env},
        "ai": {"llm": llm.name, "llm_demo_mode": llm.is_demo, "llm_key_configured": bool(settings.llm_api_key),
               "embedding": get_embedder().name, "embedding_demo_mode": not settings.remote_embeddings,
               "vector_dimension": settings.vector_dimension, "reranker": get_reranker().name},
        "rag": {"alpha": settings.rag_alpha, "beta": settings.rag_beta, "top_k": settings.rag_top_k,
                "final_k": settings.rag_final_k, "min_confidence": settings.rag_min_confidence,
                "chunk_chars": settings.rag_chunk_chars, "chunk_overlap": settings.rag_chunk_overlap},
        "security": {"access_token_minutes": settings.access_token_minutes,
                     "refresh_token_days": settings.refresh_token_days, "secure_cookies": settings.cookie_secure,
                     "max_upload_mb": settings.max_upload_mb},
        "data": counts,
        "notice": "All data in this environment is synthetic. This prototype demonstrates privacy-conscious "
                  "architecture and is not certified for production clinical use.",
    }


@router.post("/demo/load", dependencies=[Depends(rate_limit("demo", 3, 300))])
async def load_demo(request: Request, response: Response, admin: User = Depends(require("demo:load")),
                    db: Session = Depends(get_db)):
    """Wipe everything and rebuild the demo hospital. The caller is signed back in afterwards."""
    email = admin.email
    counts = await bootstrap.load_demo(db)
    user = db.scalar(select(User).where(User.email == email))
    audit.record(db, request, user, "demo.load", "system", detail=f"{counts['patients']} patients", email=email)
    payload = _session(db, response, user) if user else None
    db.commit()
    return {"loaded": counts, "session": payload}
