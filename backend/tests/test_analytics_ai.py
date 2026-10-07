"""Dashboards, insights, predictions, the Operations Copilot and its SQL sandbox."""
import asyncio
import re

import pytest
from sqlalchemy import text

from app.analytics import copilot, sql_guard
from app.analytics.insights import InsightEngine
from app.core.db import readonly_engine
from app.services.feedback_ai import classify


def test_overview_is_computed_from_the_database(client, auth, db):
    o = client.get("/api/analytics/overview", headers=auth("admin")).json()
    beds = db.execute(text("SELECT COUNT(*) FILTER (WHERE status = 'occupied') * 100.0 / COUNT(*) FROM beds")).scalar()
    assert o["bed_occupancy"]["occupancy_rate"] == pytest.approx(float(beds), abs=0.06)
    today = db.execute(text("SELECT COUNT(*) FROM appointments WHERE scheduled_at::date = :d AND status <> "
                            "'cancelled'"), {"d": o["generated_at"][:10]}).scalar()
    assert o["patients_today"]["value"] == today > 0
    assert o["emergency_load"]["level"] in {"Low", "Normal", "Elevated", "High"}
    assert 1 <= o["patient_satisfaction"]["value"] <= 5
    assert 0 < o["appointment_completion"]["value"] <= 100


@pytest.mark.parametrize("path,keys", [
    ("operations", {"patient_flow", "department_load", "hourly_volume", "wait_distribution", "bed_occupancy",
                    "doctor_utilization"}),
    ("patients", {"registrations", "age_bands", "gender", "visit_types"}),
    ("appointments", {"status_breakdown", "daily_outcomes", "no_show_by_lead_time"}),
    ("doctors", {"utilization", "pace_vs_volume"}),
    ("beds", {"by_ward", "occupancy_trend", "ward_stats", "discharge_processing"}),
    ("patient-experience", {"dimensions", "nps", "sentiment", "categories", "weekly", "themes", "complaints"}),
])
def test_every_analytics_tab_returns_non_empty_charts(client, auth, path, keys):
    r = client.get(f"/api/analytics/{path}?days=30", headers=auth("admin"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert keys <= set(body)
    for key in keys - {"nps", "themes"}:
        assert body[key]["data"], f"{path}.{key} is empty"
        assert body[key]["range"]


def test_analytics_filters_narrow_the_result(client, auth):
    everything = client.get("/api/analytics/appointments?days=30", headers=auth("admin")).json()
    cardiology = client.get("/api/analytics/appointments?days=30&department_id=1", headers=auth("admin")).json()
    assert 0 < cardiology["daily_outcomes"]["metric"]["value"] < everything["daily_outcomes"]["metric"]["value"]
    assert client.get("/api/analytics/operations?days=500", headers=auth("admin")).status_code == 422


def test_insight_engine_produces_evidence_backed_recommendations(db):
    insights = {i["key"]: i for i in InsightEngine(db).generate()}
    assert {"emergency_inflow", "icu_capacity", "discharge_delay"} <= set(insights)
    for insight in insights.values():
        assert insight["evidence"] and insight["recommendation"] and 0.5 <= insight["confidence"] <= 0.95
        assert insight["severity"] in {"low", "medium", "high", "critical"}
    # The seeded evening surge is 17:00-20:00; sampling noise may widen the detected window by an hour.
    start, end = (int(h) for h in re.findall(r"(\d\d):00", insights["emergency_inflow"]["description"])[:2])
    assert start <= 17 and end >= 20 and end - start <= 5


def test_insights_api_and_dismissal(client, auth):
    items = client.post("/api/ai/insights/refresh", headers=auth("admin")).json()
    assert items and "No action is taken automatically" in items[0]["label"]
    target = items[-1]
    assert client.post(f"/api/ai/insights/{target['id']}/dismiss", headers=auth("admin")).status_code == 204
    after = client.post("/api/ai/insights/refresh", headers=auth("admin")).json()
    assert target["key"] not in {i["key"] for i in after}, "a dismissed insight stays dismissed while its rule fires"


def test_predictions_are_explained(client, auth):
    p = client.get("/api/ai/predictions", headers=auth("admin")).json()
    assert "estimate" in p["label"].lower()
    volume = p["patient_volume"]
    assert volume["next_day"] > 0 and 0.5 <= volume["confidence"] <= 0.92 and len(volume["factors"]) == 3
    assert len(volume["series"]) == 14
    risk = p["no_show"]
    assert 0 < risk["base_rate"] < 0.5 and risk["elevated"] == len(risk["appointments"]) or risk["elevated"] > 25
    assert all(a["probability"] >= risk["threshold"] and a["factors"] for a in risk["appointments"])
    assert len(p["wait_time"]) == 8 and all(len(w["factors"]) == 3 for w in p["wait_time"])
    icu = next(w for w in p["bed_occupancy"] if w["ward"] == "ICU")
    assert 0 <= icu["value"] <= 100 and icu["factors"]


# ------------------------------------------------------------------------------- copilot
@pytest.mark.parametrize("question,intent", [
    ("Why did waiting time increase today?", "why_wait_changed"),
    ("Which department is overloaded?", "overloaded_department"),
    ("What are the top patient complaints this week?", "top_complaints"),
    ("Which doctors have the highest utilization?", "doctor_utilization"),
    ("Predict tomorrow's patient volume.", "volume_forecast"),
    ("Which department should receive additional staff?", "staffing_recommendation"),
    ("Why is the emergency department overloaded?", "emergency_overload"),
    ("Which department had the highest average waiting time this month?", "wait_by_department"),
])
def test_copilot_answers_with_underlying_data(client, auth, question, intent):
    r = client.post("/api/ai/copilot", headers=auth("admin"), json={"question": question})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["intent"] == intent and body["answer"] and body["data"] and body["chart"]
    if intent != "volume_forecast":
        assert body["queries"] and body["queries"][0]["sql"].upper().startswith("SELECT")


def test_copilot_admits_what_it_cannot_answer(db):
    result = asyncio.run(copilot.ask(db, "What's the weather like?"))
    assert result["intent"] == "unsupported" and result["queries"] == []


@pytest.mark.parametrize("sql", [
    "DELETE FROM appointments",
    "UPDATE beds SET status = 'available'",
    "DROP TABLE beds",
    "SELECT 1; DROP TABLE beds",
    "SELECT * FROM audit_logs",
    "SELECT * FROM public.beds",
    "SELECT * FROM pg_catalog.pg_shadow",
    "SELECT pg_sleep(10)",
    "SELECT id FROM beds -- trailing comment",
    "SELECT id INTO stolen FROM beds",
    "not sql at all",
])
def test_sql_guard_rejects_unsafe_statements(sql):
    with pytest.raises(sql_guard.UnsafeSQL):
        sql_guard.validate(sql)


def test_sql_guard_allows_and_caps_safe_selects():
    capped = sql_guard.validate("WITH x AS (SELECT id FROM beds) SELECT COUNT(*) FROM x;")
    assert capped.endswith(f"LIMIT {sql_guard.MAX_ROWS}")
    assert len(sql_guard.run_readonly("SELECT id FROM appointments")) == sql_guard.MAX_ROWS


@pytest.mark.parametrize("sql", [
    "SELECT email FROM users", "SELECT password_hash FROM users", "SELECT full_name FROM patients",
    "SELECT comment FROM feedback", "SELECT note FROM clinical_notes", "SELECT * FROM ai_messages",
    "INSERT INTO departments (name, code, floor, location) VALUES ('x', 'Z', '1', 'x')",
])
def test_readonly_role_is_a_second_line_of_defence(sql):
    """Even with the validator bypassed, the database role itself cannot read PII or write."""
    with readonly_engine.connect() as conn, pytest.raises(Exception) as exc:
        conn.execute(text(sql))
    assert "permission denied" in str(exc.value) or "read-only transaction" in str(exc.value)


# ------------------------------------------------------------------------------- reports & search
def test_reports_export_json_csv_and_pdf(client, auth):
    kinds = [r["key"] for r in client.get("/api/reports", headers=auth("admin")).json()]
    assert len(kinds) == 7
    for kind in kinds:
        body = client.get(f"/api/reports/{kind}", headers=auth("admin")).json()
        assert body["rows"], kind
    csv = client.get("/api/reports/department-performance?format=csv&department_id=1", headers=auth("admin"))
    assert csv.headers["content-type"].startswith("text/csv") and "attachment" in csv.headers["content-disposition"]
    lines = csv.text.strip().splitlines()
    assert lines[0].lstrip("﻿").startswith("department,patients") and len(lines) == 2
    pdf = client.get("/api/reports/doctor-utilization?format=pdf", headers=auth("admin"))
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    assert client.get("/api/reports/daily-operations?date_from=2026-01-01&date_to=2026-12-31",
                      headers=auth("admin")).status_code == 400


def test_global_search_is_scoped_by_role(client, auth):
    staff = client.get("/api/search?q=sharma", headers=auth("reception")).json()["results"]
    assert any(r["type"] == "doctor" and r["title"] == "Dr. Priya Sharma" for r in staff)
    assert client.get("/api/search?q=alex", headers=auth("reception")).json()["results"][0]["type"] == "patient"
    patient = client.get("/api/search?q=alex", headers=auth("patient")).json()["results"]
    assert not any(r["type"] == "patient" for r in patient)
    knowledge = client.get("/api/search?q=hypertension", headers=auth("patient")).json()["results"]
    assert any(r["type"] == "knowledge" for r in knowledge)
    assert client.get("/api/search?q=a", headers=auth("patient")).status_code == 422


def test_feedback_classifier_examples():
    assert classify("The waiting time was extremely long.", 2, "Emergency").category == "waiting_time"
    billing = classify("I was overcharged and the bill was confusing.", 2)
    assert (billing.sentiment, billing.category) == ("negative", "billing")
    praise = classify("The nurses were kind and helpful, thank you!", 5)
    assert (praise.sentiment, praise.urgency) == ("positive", "low")
    assert classify("My father fell and was left unattended.", 1).urgency == "high"
