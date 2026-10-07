import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api import admin, analytics, appointments, auth, beds, directory, feedback, patients, queues, rag, reports
from app.core import errors
from app.core.clock import now
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.realtime import hub
from app.security.auth import user_from_access_token
from app.services import bootstrap

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("medflow")
WS_AUTH_TIMEOUT_SECONDS = 10


@asynccontextmanager
async def lifespan(_: FastAPI):
    hub.bind_loop(asyncio.get_running_loop())
    with SessionLocal() as db:
        await bootstrap.seed_if_empty(db)
    yield


app = FastAPI(title="MedFlow AI", version="1.0.0", lifespan=lifespan, docs_url="/api/docs",
              openapi_url="/api/openapi.json", redoc_url=None,
              description="AI-powered hospital operations and patient experience platform. Synthetic demo data.")
errors.install(app)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True,
                   allow_methods=["GET", "POST", "PATCH", "DELETE"], allow_headers=["Authorization", "Content-Type"])


@app.middleware("http")
async def security_headers_and_access_log(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cache-Control", "no-store")  # API responses can contain patient data
    if not request.url.path.startswith("/api/docs"):
        response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
    if settings.cookie_secure:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    # Method, path, status, duration. Never query strings, bodies or headers.
    level = logging.WARNING if response.status_code >= 500 else logging.INFO
    log.log(level, "%s %s -> %s (%.0f ms)", request.method, request.url.path, response.status_code,
            (time.perf_counter() - started) * 1000)
    return response


api = APIRouter(prefix="/api")
for module in (auth, patients, directory, appointments, queues, beds, feedback, analytics, rag, reports, admin):
    api.include_router(module.router)

# Convenience aliases so the documented short paths work too.
api.add_api_route("/chat", rag.chat, methods=["POST"], tags=["rag"], dependencies=[rag.chat_limit])
api.add_api_route("/chat/conversations", rag.conversations, methods=["GET"], tags=["rag"])
api.add_api_route("/knowledge/documents", rag.list_documents, methods=["GET"], tags=["rag"])
api.add_api_route("/knowledge/documents", rag.upload_document, methods=["POST"], status_code=201, tags=["rag"])
api.add_api_route("/knowledge/ingest", rag.reingest, methods=["POST"], tags=["rag"])


@api.get("/health", tags=["system"])
def health():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok", "environment": settings.app_env}


@api.get("/clock", tags=["system"])
def clock():
    """Hospital-local time. Clients render "today" and schedules from this, not from the device clock."""
    return {"now": now(), "timezone": settings.hospital_tz, "hospital": settings.hospital_name}


app.include_router(api)


@app.websocket("/ws")
async def websocket(ws: WebSocket):
    """Realtime channel. The first frame must be {"type": "auth", "token": <access token>}."""
    await ws.accept()
    try:
        first = await asyncio.wait_for(ws.receive_json(), WS_AUTH_TIMEOUT_SECONDS)
        with SessionLocal() as db:
            user = user_from_access_token(db, str(first.get("token", "")))
    except Exception:
        await ws.close(code=4401)
        return
    hub.add(ws, user.id)
    await ws.send_json({"type": "ready"})
    try:
        while True:
            await ws.receive_text()  # keep-alives; clients never send data
    except WebSocketDisconnect:
        pass
    finally:
        hub.remove(ws)
