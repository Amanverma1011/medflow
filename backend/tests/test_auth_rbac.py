from app.core.config import settings
from app.security.auth import REFRESH_COOKIE

DEMO = "demo.medflow.ai"


def login(client, email, password=None):
    return client.post("/api/auth/login", json={"email": email, "password": password or settings.demo_password})


# ------------------------------------------------------------------------------- authentication
def test_login_returns_token_and_role_profile(client):
    r = login(client, f"doctor@{DEMO}")
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["roles"] == ["doctor"] and body["user"]["home"] == "/doctor/dashboard"
    assert "clinical:write" in body["user"]["permissions"]
    assert "password" not in str(body).lower().replace("password_hash", "")
    cookie = r.headers["set-cookie"]
    assert REFRESH_COOKIE in cookie and "HttpOnly" in cookie


def test_wrong_password_and_unknown_user_look_identical(client):
    wrong = login(client, f"doctor@{DEMO}", "not-the-password")
    unknown = login(client, "nobody@example.org", "not-the-password")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()
    assert wrong.json()["error"]["code"] == "unauthorized"


def test_protected_route_requires_a_valid_token(client):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_refresh_token_rotates_and_reuse_revokes_the_session(client):
    first = login(client, f"nurse@{DEMO}").cookies[REFRESH_COOKIE]
    rotated = client.post("/api/auth/refresh", cookies={REFRESH_COOKIE: first})
    assert rotated.status_code == 200
    second = rotated.cookies[REFRESH_COOKIE]
    assert second != first
    # Replaying the already-used token is treated as theft: it fails and kills the newer token too.
    assert client.post("/api/auth/refresh", cookies={REFRESH_COOKIE: first}).status_code == 401
    assert client.post("/api/auth/refresh", cookies={REFRESH_COOKIE: second}).status_code == 401
    client.cookies.clear()


def test_login_is_rate_limited(client):
    codes = [login(client, "nobody@example.org", "x").status_code for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[-1] == 429


def test_register_creates_a_patient_account_only(client):
    r = client.post("/api/auth/register", json={
        "email": "new.patient@example.org", "password": "Sup3rSecret", "full_name": "New Patient",
        "date_of_birth": "1990-04-02", "gender": "Female"})
    assert r.status_code == 201
    user = r.json()["user"]
    assert user["roles"] == ["patient"] and user["patient_id"]
    assert client.post("/api/auth/register", json={
        "email": "new.patient@example.org", "password": "Sup3rSecret", "full_name": "Dup",
        "date_of_birth": "1990-04-02", "gender": "Female"}).status_code == 409
    client.cookies.clear()


def test_validation_errors_are_structured(client):
    r = client.post("/api/auth/register", json={"email": "bad", "password": "short", "full_name": "A",
                                                "date_of_birth": "2999-01-01", "gender": "X", "role": "admin"})
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["code"] == "validation_error"
    assert {"email", "password", "role"} <= {d["field"] for d in error["details"]}


# ------------------------------------------------------------------------------- authorization
def test_patient_cannot_reach_staff_data(client, auth):
    for path in ("/api/patients", "/api/analytics/overview", "/api/audit-logs", "/api/users", "/api/beds",
                 "/api/queues", "/api/rag/documents", "/api/reports", "/api/ai/insights"):
        assert client.get(path, headers=auth("patient")).status_code == 403, path


def test_patient_can_only_read_their_own_record(client, auth):
    own = client.get("/api/patients/me", headers=auth("patient")).json()
    assert own["patient"]["full_name"] == "Alex Morgan" and own["clinical_access"] is True
    other = own["patient"]["id"] + 1
    assert client.get(f"/api/patients/{other}", headers=auth("patient")).status_code == 403


def test_doctor_only_opens_records_of_their_own_patients(client, auth):
    mine = client.get("/api/patients?size=1", headers=auth("doctor")).json()["items"][0]["id"]
    assert client.get(f"/api/patients/{mine}", headers=auth("doctor")).status_code == 200
    theirs = {p["id"] for p in client.get("/api/patients?size=100", headers=auth("doctor02")).json()["items"]}
    ours = {p["id"] for p in client.get("/api/patients?size=100", headers=auth("doctor")).json()["items"]}
    outsider = next(iter(theirs - ours))
    assert client.get(f"/api/patients/{outsider}", headers=auth("doctor")).status_code == 403


def test_administrator_sees_demographics_but_not_clinical_content(client, auth):
    record = client.get("/api/patients/1", headers=auth("admin")).json()
    assert record["clinical_access"] is False
    assert record["prescriptions"] == [] and record["documents"] == []
    assert all(v["notes"] is None for v in record["visits"])
    assert client.get("/api/patients/1", headers=auth("nurse")).json()["prescriptions"]


def test_role_boundaries_between_staff(client, auth):
    assert client.get("/api/analytics/overview", headers=auth("reception")).status_code == 403
    assert client.get("/api/beds", headers=auth("reception")).status_code == 403
    assert client.get("/api/audit-logs", headers=auth("admin")).status_code == 403  # super admin only
    assert client.get("/api/rag/documents", headers=auth("admin")).status_code == 403
    assert client.get("/api/audit-logs", headers=auth("superadmin")).status_code == 200


def test_sensitive_access_is_audited_without_clinical_content(client, auth):
    client.get("/api/patients/1", headers=auth("nurse"))
    logs = client.get("/api/audit-logs?action=patient.view", headers=auth("superadmin")).json()["items"]
    entry = next(e for e in logs if e["user"] == f"nurse@{DEMO}")
    assert entry["resource_type"] == "patient" and entry["resource_id"] == "1" and entry["result"] == "success"
    assert entry["detail"] == "clinical"


def test_security_headers_present(client):
    r = client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'none'" in r.headers["content-security-policy"]
