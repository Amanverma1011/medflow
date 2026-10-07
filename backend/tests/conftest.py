"""Integration tests run against a real PostgreSQL + pgvector database.

Point TEST_DATABASE_URL at a throwaway database whose name ends in `_test`.
The suite migrates it with Alembic and loads a small demo hospital once per session.
"""
import asyncio
import os

TEST_URL = os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://medflow:medflow@localhost:5433/medflow_test")
if not TEST_URL.rsplit("/", 1)[-1].split("?")[0].endswith("_test"):
    raise RuntimeError("Refusing to run: the test database name must end with '_test' (the suite wipes it).")
os.environ.update(DATABASE_URL=TEST_URL, AUTO_SEED="false", LLM_API_KEY="", EMBEDDING_API_KEY="",
                  APP_ENV="test", JWT_SECRET="test-secret-not-used-anywhere-else")

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.core import ratelimit  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.services import bootstrap  # noqa: E402

DEMO = "demo.medflow.ai"


@pytest.fixture(scope="session", autouse=True)
def database():
    url = make_url(TEST_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        if not conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}).scalar():
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()
    command.upgrade(Config("alembic.ini"), "head")
    with SessionLocal() as db:
        asyncio.run(bootstrap.load_demo(db, scale=0.3))
    yield


@pytest.fixture(autouse=True)
def _no_rate_limit_bleed():
    ratelimit.reset()
    yield


@pytest.fixture()
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture(scope="session")
def client(database):
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def tokens(client):
    """Access tokens for each demo role, fetched once."""
    out = {}
    for role in ("superadmin", "admin", "doctor", "doctor02", "nurse", "reception", "patient"):
        r = client.post("/api/auth/login", json={"email": f"{role}@{DEMO}", "password": settings.demo_password})
        assert r.status_code == 200, r.text
        out[role] = r.json()["access_token"]
        ratelimit.reset()
    return out


@pytest.fixture(scope="session")
def auth(tokens):
    return lambda role: {"Authorization": f"Bearer {tokens[role]}"}
