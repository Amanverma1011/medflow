"""Appointments, queue and bed management, exercised through the API."""
from datetime import timedelta

import pytest

from app.core.clock import now


def _free_slot(client, auth, doctor_id=2, days_ahead=3):
    """First available slot for a doctor, searching forward so tests never collide with seeded bookings."""
    for offset in range(days_ahead, days_ahead + 10):
        day = (now() + timedelta(days=offset)).date().isoformat()
        slots = client.get(f"/api/doctors/{doctor_id}/slots?day={day}", headers=auth("patient")).json()["slots"]
        free = [s["time"] for s in slots if s["available"]]
        if free:
            return free
    pytest.fail("no free slot found")


# ------------------------------------------------------------------------------- appointments
def test_patient_books_reschedules_and_cancels(client, auth):
    first, second, *_ = _free_slot(client, auth)
    created = client.post("/api/appointments", headers=auth("patient"),
                          json={"doctor_id": 2, "scheduled_at": first, "reason": "Check-up", "patient_id": 99})
    assert created.status_code == 201
    appt = created.json()
    assert appt["patient"] == "Alex Morgan"  # patient_id in the body is ignored for patients
    assert appt["status"] == "scheduled"

    moved = client.patch(f"/api/appointments/{appt['id']}", headers=auth("patient"), json={"scheduled_at": second})
    assert moved.status_code == 200 and moved.json()["scheduled_at"] == second

    cancelled = client.patch(f"/api/appointments/{appt['id']}", headers=auth("patient"), json={"status": "cancelled"})
    assert cancelled.json()["status"] == "cancelled"
    again = client.patch(f"/api/appointments/{appt['id']}", headers=auth("patient"), json={"status": "cancelled"})
    assert again.status_code == 200  # idempotent
    assert client.patch(f"/api/appointments/{appt['id']}", headers=auth("patient"),
                        json={"scheduled_at": first}).status_code == 409  # cancelled can't be rescheduled

    titles = [n["title"] for n in client.get("/api/notifications", headers=auth("patient")).json()["items"]]
    assert {"Appointment confirmed", "Appointment rescheduled", "Appointment cancelled"} <= set(titles)


def test_double_booking_a_slot_is_a_conflict(client, auth):
    slot = _free_slot(client, auth, doctor_id=3)[0]
    walk_ins = [client.post("/api/patients", headers=auth("reception"), json={
        "full_name": f"Walk In {n}", "date_of_birth": "1985-06-01", "gender": "Other"}).json()["id"] for n in "AB"]
    body = {"doctor_id": 3, "scheduled_at": slot, "patient_id": walk_ins[0]}
    assert client.post("/api/appointments", headers=auth("reception"), json=body).status_code == 201
    clash = client.post("/api/appointments", headers=auth("reception"), json={**body, "patient_id": walk_ins[1]})
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "conflict"


def test_booking_rules(client, auth):
    past = (now() - timedelta(days=1)).replace(hour=10, minute=0, second=0).isoformat()
    assert client.post("/api/appointments", headers=auth("patient"),
                       json={"doctor_id": 2, "scheduled_at": past}).status_code == 400
    odd = (now() + timedelta(days=2)).replace(hour=10, minute=7, second=0).isoformat()
    assert client.post("/api/appointments", headers=auth("patient"),
                       json={"doctor_id": 2, "scheduled_at": odd}).status_code == 400
    night = (now() + timedelta(days=2)).replace(hour=3, minute=0, second=0).isoformat()
    assert client.post("/api/appointments", headers=auth("patient"),
                       json={"doctor_id": 2, "scheduled_at": night}).status_code == 409
    assert client.post("/api/appointments", headers=auth("reception"),
                       json={"doctor_id": 2, "scheduled_at": night}).status_code == 400  # staff must name a patient


def test_patient_cannot_touch_someone_elses_appointment_or_mark_no_show(client, auth):
    other = client.get("/api/appointments?patient_id=7&size=1", headers=auth("reception")).json()["items"][0]
    assert client.patch(f"/api/appointments/{other['id']}", headers=auth("patient"),
                        json={"status": "cancelled"}).status_code == 403
    mine = client.get("/api/appointments?size=50&patient_id=7", headers=auth("patient")).json()["items"]
    assert {a["patient_id"] for a in mine} == {1}  # the list is scoped to the caller whatever they ask for
    booked = client.post("/api/appointments", headers=auth("patient"),
                         json={"doctor_id": 4, "scheduled_at": _free_slot(client, auth, doctor_id=4)[0]}).json()
    assert client.patch(f"/api/appointments/{booked['id']}", headers=auth("patient"),
                        json={"status": "no_show"}).status_code == 403
    assert client.patch(f"/api/appointments/{booked['id']}", headers=auth("reception"),
                        json={"status": "no_show"}).json()["status"] == "no_show"


# ------------------------------------------------------------------------------- queue
def test_full_queue_flow_from_check_in_to_completed_visit(client, auth):
    """Scenario 1 + 2: patient checks in, waits behind others, doctor works the queue."""
    me = client.get("/api/queues/me", headers=auth("patient")).json()
    assert me["entry"] is None and me["can_check_in"], "the seed gives Alex an appointment today"
    appointment_id = me["can_check_in"][0]["id"]

    checked = client.post("/api/queues/check-in", headers=auth("patient"), json={"appointment_id": appointment_id})
    assert checked.status_code == 201
    info = checked.json()
    assert info["token"].startswith("A-") and info["patients_ahead"] == 4  # 4 scripted patients already waiting
    assert info["estimated_wait_minutes"] > 0 and len(info["factors"]) == 3
    assert client.post("/api/queues/check-in", headers=auth("patient"),
                       json={"appointment_id": appointment_id}).status_code == 409

    dash = client.get("/api/doctor/dashboard", headers=auth("doctor")).json()
    assert dash["metrics"]["waiting_patients"] == 5 and dash["current"] is not None
    assert "5 patients waiting" in dash["brief"]["lines"][0]
    queue = client.get("/api/queues", headers=auth("doctor")).json()["queues"]
    assert len(queue) == 1, "a doctor only sees their own queue"
    queue = queue[0]
    queue_id, current = queue["id"], queue["current"]

    # Can't call the next patient while a consultation is open.
    assert client.post(f"/api/queues/{queue_id}/call-next", headers=auth("doctor")).status_code == 409
    done = client.post(f"/api/queues/entries/{current['id']}/complete", headers=auth("doctor"), json={
        "note": "Reviewed. Stable.",
        "prescription": {"medication": "Demo medication", "dosage": "1 tablet", "frequency": "Once daily"}})
    assert done.status_code == 200 and done.json()["visit_id"]

    # Prioritise Alex past the four people ahead, then call.
    alex = next(e for e in queue["waiting"] if e["token"] == info["token"])
    assert client.post(f"/api/queues/entries/{alex['id']}/prioritize", headers=auth("reception")).status_code == 200
    assert client.get("/api/queues/me", headers=auth("patient")).json()["entry"]["patients_ahead"] == 0
    called = client.post(f"/api/queues/{queue_id}/call-next", headers=auth("doctor")).json()
    assert called["token"] == info["token"] and called["status"] == "in_consultation"
    assert client.get("/api/queues/me", headers=auth("patient")).json()["entry"]["status"] == "in_consultation"
    assert client.get(f"/api/appointments/{appointment_id}",
                      headers=auth("patient")).json()["status"] == "in_consultation"

    titles = [n["title"] for n in client.get("/api/notifications", headers=auth("patient")).json()["items"]]
    assert "It's your turn" in titles


def test_skip_moves_patient_to_back_and_transfer_changes_doctor(client, auth):
    queue = client.get("/api/queues?doctor_id=1", headers=auth("reception")).json()["queues"][0]
    waiting = queue["waiting"]
    assert len(waiting) >= 2
    first = waiting[0]
    assert client.post(f"/api/queues/entries/{first['id']}/skip", headers=auth("reception")).status_code == 200
    after = client.get("/api/queues?doctor_id=1", headers=auth("reception")).json()["queues"][0]["waiting"]
    assert after[-1]["id"] == first["id"] and after[0]["id"] != first["id"]

    moved = after[0]
    r = client.post(f"/api/queues/entries/{moved['id']}/transfer", headers=auth("reception"), json={"doctor_id": 2})
    assert r.status_code == 200
    target = client.get("/api/queues?doctor_id=2", headers=auth("reception")).json()["queues"][0]
    assert moved["id"] in [e["id"] for e in target["waiting"]]
    assert client.get(f"/api/appointments/{moved['appointment_id']}",
                      headers=auth("reception")).json()["doctor_id"] == 2


def test_receptionist_cannot_write_clinical_notes(client, auth):
    queue = client.get("/api/queues?doctor_id=2", headers=auth("reception")).json()["queues"][0]
    entry = queue["waiting"][0]
    r = client.post(f"/api/queues/entries/{entry['id']}/complete", headers=auth("reception"),
                    json={"note": "should not be allowed"})
    assert r.status_code == 403


# ------------------------------------------------------------------------------- beds
def test_bed_assignment_lifecycle(client, auth):
    wards = client.get("/api/beds", headers=auth("nurse")).json()["wards"]
    beds = [b for w in wards for b in w["beds"]]
    free = [b for b in beds if b["status"] == "available"]
    bed, other = free[0], free[1]
    occupied = next(b for b in beds if b["status"] == "occupied")
    admitted = {b["patient_id"] for b in beds if b["patient_id"]}
    patient_id = next(i for i in range(2, 60) if i not in admitted)

    r = client.post(f"/api/beds/{bed['id']}/assign", headers=auth("nurse"), json={"patient_id": patient_id})
    assert r.status_code == 201 and r.json()["status"] == "occupied"
    # One patient, one bed; one bed, one patient.
    assert client.post(f"/api/beds/{other['id']}/assign", headers=auth("nurse"),
                       json={"patient_id": patient_id}).status_code == 409
    assert client.post(f"/api/beds/{occupied['id']}/assign", headers=auth("nurse"),
                       json={"patient_id": patient_id + 100}).status_code == 409
    # Status can't be changed underneath a patient, and "occupied" can't be set by hand.
    assert client.patch(f"/api/beds/{bed['id']}", headers=auth("nurse"),
                        json={"status": "maintenance"}).status_code == 409
    assert client.patch(f"/api/beds/{other['id']}", headers=auth("nurse"),
                        json={"status": "occupied"}).status_code == 422

    assert client.post(f"/api/beds/{bed['id']}/release", headers=auth("nurse")).json()["status"] == "cleaning"
    tasks = client.get("/api/beds/tasks", headers=auth("nurse")).json()["tasks"]
    assert any(t["type"] == "turnaround" and t["bed_id"] == bed["id"] for t in tasks)
    assert client.patch(f"/api/beds/{bed['id']}", headers=auth("nurse"),
                        json={"status": "available"}).json()["status"] == "available"
    assert client.post(f"/api/beds/{bed['id']}/assign", headers=auth("doctor"),
                       json={"patient_id": patient_id}).status_code == 403  # doctors can view, not manage


# ------------------------------------------------------------------------------- feedback
def test_feedback_is_classified_and_raises_a_complaint(client, auth):
    r = client.post("/api/feedback", headers=auth("patient"), json={
        "department_id": 6, "overall": 1, "wait_time": 1, "staff": 2, "doctor": 3, "cleanliness": 3,
        "communication": 2, "appointment_experience": 2, "nps": 1,
        "comment": "The waiting time was extremely long."})
    assert r.status_code == 201
    analysis = r.json()["analysis"]
    assert analysis == {"sentiment": "negative", "category": "waiting_time", "urgency": "medium",
                        "theme": "Emergency department congestion and long waits"}
    listed = client.get("/api/feedback?sentiment=negative&category=waiting_time", headers=auth("admin")).json()
    assert listed["items"][0]["comment"] == "The waiting time was extremely long."
    assert client.post("/api/feedback", headers=auth("doctor"), json={}).status_code == 403
