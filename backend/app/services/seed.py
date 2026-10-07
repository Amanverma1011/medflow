"""Synthetic demo hospital. Every person, record and comment here is fictional.

Deterministic (fixed RNG seed) but anchored to the current hospital time, so
"today" always has a live queue, waiting patients and upcoming appointments.
"""
import random
from collections import defaultdict
from datetime import datetime, timedelta

from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from app.core.clock import now as clock_now
from app.core.config import settings
from app.core.db import Base
from app.models import (Appointment, AppointmentStatusHistory, Bed, BedAssignment, ClinicalNote, Complaint,
                        Department, Doctor, Feedback, MedicalDocument, Notification, Patient, PatientProfile,
                        Permission, Prescription, Queue, QueueEntry, Role, Staff, User, Visit, Ward)
from app.security.auth import hash_password
from app.security.rbac import PERMISSIONS, ROLES
from app.services.feedback_ai import classify

DEMO_DOMAIN = "demo.medflow.ai"

# name, token code, floor, location, open, close, description, doctors, avg consult, base wait, specialties
DEPARTMENTS = [
    ("Cardiology", "A", "Level 2", "East Wing, Level 2", 8, 18, "Heart and circulation care", 3, 18, 19,
     ["Interventional Cardiology", "Heart Failure", "Preventive Cardiology"]),
    ("Neurology", "B", "Level 3", "East Wing, Level 3", 8, 18, "Brain, spine and nerve conditions", 3, 20, 17,
     ["Stroke Medicine", "Epilepsy", "Headache Medicine"]),
    ("Orthopedics", "C", "Level 1", "West Wing, Level 1", 8, 18, "Bones, joints and sports injuries", 3, 15, 21,
     ["Joint Replacement", "Sports Medicine", "Spine Surgery"]),
    ("Pediatrics", "D", "Level 1", "Children's Pavilion, Level 1", 8, 18, "Care for infants, children and teens",
     3, 14, 13, ["General Pediatrics", "Neonatology", "Pediatric Allergy"]),
    ("General Medicine", "E", "Ground Floor", "Main Building, Ground Floor", 8, 18,
     "Adult primary and internal medicine", 4, 12, 24,
     ["Internal Medicine", "Diabetes & Endocrinology", "Family Medicine", "Geriatric Medicine"]),
    ("Emergency", "F", "Ground Floor", "Main Building, Ground Floor (24-hour entrance)", 0, 24,
     "24-hour emergency and urgent care", 4, 16, 33,
     ["Emergency Medicine", "Emergency Medicine", "Trauma Care", "Emergency Medicine"]),
    ("Radiology", "G", "Level B1", "Main Building, Level B1", 8, 18, "X-ray, CT, MRI and ultrasound imaging",
     2, 20, 15, ["Diagnostic Radiology", "Interventional Radiology"]),
    ("Oncology", "H", "Level 4", "East Wing, Level 4", 8, 18, "Cancer diagnosis, treatment and support", 3, 25, 16,
     ["Medical Oncology", "Radiation Oncology", "Hematology"]),
]
SHIFTS = [(9, 17), (8, 16), (10, 18), (9, 17)]
EMERGENCY_SHIFTS = [(0, 8), (8, 16), (14, 22), (16, 24)]  # 24-hour cover, doubled up in the evening

# name, department, type, floor, label prefix, beds, target occupancy, mean stay (days)
WARDS = [
    ("ICU", None, "icu", "Level 3", "ICU", 16, 0.90, 4.5),
    ("Emergency Bay", "Emergency", "emergency", "Ground Floor", "EB", 12, 0.70, 0.6),
    ("Ward A · General", "General Medicine", "general", "Level 2", "A", 24, 0.78, 3.2),
    ("Ward B · Cardiac", "Cardiology", "general", "Level 2", "B", 18, 0.80, 3.5),
    ("Ward C · Orthopedic", "Orthopedics", "general", "Level 1", "C", 16, 0.72, 4.0),
    ("Pediatric Ward", "Pediatrics", "pediatric", "Level 1", "P", 14, 0.65, 2.5),
    ("Oncology Ward", "Oncology", "general", "Level 4", "O", 12, 0.75, 5.0),
    ("Neuro Ward", "Neurology", "general", "Level 3", "N", 12, 0.70, 4.0),
]

FIRST = ("Aarav Aditi Alex Amara Ananya Arjun Ava Ben Carlos Chloe Daniel Deepa Elena Emma Ethan Farah Grace "
         "Hannah Ibrahim Isha Jamal Julia Karan Kavya Leo Lina Lucas Maya Meera Mohan Nadia Neha Noah Olivia "
         "Omar Priya Rahul Ravi Rhea Rohan Sana Sara Sofia Tariq Uma Vikram Yusuf Zara Zoe Nikhil").split()
LAST = ("Ahmed Anderson Banerjee Brooks Chatterjee Chen Costa Das Desai Diaz Evans Fernandes Garcia Gupta Hughes "
        "Iyer Jain Joshi Kapoor Khan Kim Kumar Lee Malhotra Martin Mehta Menon Mishra Nair Nguyen Okafor Patel "
        "Pillai Rao Reddy Rossi Roy Saxena Shah Singh Sinha Smith Thomas Varma Verma Walker Wilson Wright Young "
        "Bose").split()
REASONS = {
    "Cardiology": ["Blood pressure review", "Chest discomfort follow-up", "Palpitations", "Post-procedure review",
                   "Cholesterol review"],
    "Neurology": ["Recurring headaches", "Dizziness assessment", "Seizure follow-up", "Numbness in hand"],
    "Orthopedics": ["Knee pain", "Lower back pain", "Fracture follow-up", "Shoulder stiffness"],
    "Pediatrics": ["Well-child visit", "Fever and cough", "Vaccination", "Allergy review"],
    "General Medicine": ["Annual check-up", "Diabetes review", "Persistent cough", "Fatigue", "Medication review"],
    "Emergency": ["Abdominal pain", "Minor injury", "Shortness of breath", "High fever", "Fall at home"],
    "Radiology": ["MRI scan", "CT scan", "Chest X-ray", "Abdominal ultrasound"],
    "Oncology": ["Treatment review", "Follow-up scan results", "Chemotherapy planning", "Symptom review"],
}
MEDICATIONS = {
    "Cardiology": [("Amlodipine", "5 mg", "Once daily"), ("Atorvastatin", "20 mg", "Once daily at night")],
    "Neurology": [("Sumatriptan", "50 mg", "As needed for migraine"), ("Levetiracetam", "500 mg", "Twice daily")],
    "Orthopedics": [("Ibuprofen", "400 mg", "Three times daily with food"), ("Calcium + Vitamin D", "1 tablet",
                                                                           "Once daily")],
    "Pediatrics": [("Paracetamol syrup", "As per weight", "Every 6 hours if needed"),
                   ("Cetirizine", "5 mg", "Once daily")],
    "General Medicine": [("Metformin", "500 mg", "Twice daily with meals"), ("Omeprazole", "20 mg", "Once daily")],
    "Oncology": [("Ondansetron", "8 mg", "As needed for nausea")],
}
COMMENTS = {
    ("waiting_time", "neg"): ["The waiting time was extremely long. I waited over {w} minutes past my appointment.",
                              "Very slow service. Nobody told us why there was such a long delay.",
                              "I waited for hours in the queue and the delay was never explained."],
    ("waiting_time", "pos"): ["I was seen on time and the whole visit was quick and efficient.",
                              "Hardly any wait at all. Very prompt service."],
    ("staff_behavior", "neg"): ["The receptionist was rude and unhelpful when I asked a simple question.",
                                "Staff at the desk seemed dismissive and ignored me for a long time."],
    ("staff_behavior", "pos"): ["The nurses were kind, friendly and very helpful throughout.",
                                "Reception staff were polite and courteous. Thank you."],
    ("doctor_communication", "neg"): ["The doctor seemed rushed and did not explain my results clearly.",
                                      "I felt my questions were ignored during the consultation."],
    ("doctor_communication", "pos"): ["The doctor listened carefully and explained everything in clear terms.",
                                      "Excellent consultation. The doctor answered all my questions."],
    ("billing", "neg"): ["The bill was confusing and I think I was overcharged for a test.",
                         "Billing took a long time and the insurance paperwork was wrong."],
    ("cleanliness", "neg"): ["The washroom near the waiting area was dirty and had a bad smell.",
                             "The waiting room chairs were stained and the floor was not clean."],
    ("cleanliness", "pos"): ["The ward was spotless and very clean. I felt comfortable."],
    ("appointment", "neg"): ["My appointment was rescheduled twice without a proper reminder.",
                             "Booking a slot online was confusing and frustrating."],
    ("appointment", "pos"): ["Booking the appointment was easy and the reminder was helpful."],
    ("facilities", "neg"): ["Parking was full and the signage to the department was confusing."],
    ("facilities", "pos"): ["Comfortable seating and good wheelchair access. Great facilities."],
    ("pharmacy", "neg"): ["The pharmacy was out of stock for my prescription and the queue was slow."],
    ("emergency_care", "neg"): ["In the emergency department triage took forever while my father was in pain for "
                                "an hour, unattended.",
                                "Emergency was overcrowded and we waited a long time before anyone saw us."],
    ("emergency_care", "pos"): ["The emergency team was fast, professional and caring."],
    ("general", "neu"): ["The visit was okay overall.", "Average experience, nothing to complain about.",
                         "Fine, but there is room for improvement."],
}


class _Ids:
    """Hands out explicit primary keys so related rows can be bulk-inserted together."""

    def __init__(self):
        self._next = defaultdict(int)

    def __call__(self, table: str) -> int:
        self._next[table] += 1
        return self._next[table]


def _truncate(db: Session) -> None:
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    db.execute(text(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE"))


def _sync_sequences(db: Session) -> None:
    for table in Base.metadata.sorted_tables:
        if "id" in table.c:
            db.execute(text(f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), "
                            f"COALESCE(MAX(id), 1), MAX(id) IS NOT NULL) FROM \"{table.name}\""))


def _bulk(db: Session, model, rows: list[dict]) -> None:
    for i in range(0, len(rows), 2000):
        db.execute(insert(model), rows[i:i + 2000])


def _wait_minutes(rng: random.Random, dept: str, base: int, when: datetime, days_ago: int) -> float:
    factor = 1.0
    if dept == "Emergency":
        if 17 <= when.hour < 20:
            factor *= 1.38  # evening surge
        if days_ago <= 7:
            factor *= 1.15  # the last week has been busier
    elif 10 <= when.hour < 13:
        factor *= 1.2
    if when.weekday() == 0:
        factor *= 1.1
    return max(2.0, rng.gauss(base * factor, base * 0.3))


def run(db: Session, scale: float = 1.0, days_back: int = 45, days_forward: int = 7) -> dict:
    """Wipe the database and load the demo hospital. Returns row counts."""
    rng = random.Random(42)
    ids = _Ids()
    now = clock_now()
    today = now.replace(hour=0, minute=0, second=0)
    _truncate(db)

    # ------------------------------------------------------------------ roles & permissions
    perms = {code: Permission(code=code) for code in PERMISSIONS}
    roles = {name: Role(name=name, description=desc, permissions=[perms[c] for c in codes])
             for name, (desc, codes) in ROLES.items()}
    db.add_all(roles.values())
    password_hash = hash_password(settings.demo_password)  # hashed once; bcrypt is deliberately slow
    used_names: set[str] = set()

    def person() -> str:
        while True:
            name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
            if name not in used_names:
                used_names.add(name)
                return name

    def user(email: str, name: str, role: str) -> User:
        u = User(email=f"{email}@{DEMO_DOMAIN}", full_name=name, password_hash=password_hash, roles=[roles[role]],
                 created_at=now - timedelta(days=400))
        db.add(u)
        return u

    super_admin = user("superadmin", "Morgan Hale", "super_admin")
    admin = user("admin", "Jordan Ellis", "administrator")

    # ------------------------------------------------------------------ departments & doctors
    departments: dict[str, Department] = {}
    dept_meta: dict[int, dict] = {}
    doctors: list[Doctor] = []
    for name, code, floor, location, open_h, close_h, desc, n_doctors, consult, wait, specialties in DEPARTMENTS:
        dept = Department(name=name, code=code, floor=floor, location=location, description=desc,
                          open_hour=open_h, close_hour=close_h)
        db.add(dept)
        db.flush()
        departments[name] = dept
        dept_meta[dept.id] = {"name": name, "wait": wait, "code": code}
        for i in range(n_doctors):
            first = name == "Cardiology" and i == 0
            doc_user = user("doctor" if first else f"doctor{len(doctors) + 1:02d}",
                            "Dr. Priya Sharma" if first else f"Dr. {person()}", "doctor")
            db.flush()
            start, end = EMERGENCY_SHIFTS[i] if name == "Emergency" else SHIFTS[i % len(SHIFTS)]
            doctor = Doctor(user_id=doc_user.id, department_id=dept.id, specialty=specialties[i % len(specialties)],
                            room=f"{code}{101 + i}", years_experience=rng.randint(4, 28),
                            avg_consult_minutes=consult + rng.randint(-2, 3), shift_start=start, shift_end=end)
            db.add(doctor)
            doctors.append(doctor)
    db.flush()
    sharma = doctors[0]

    dept_list = list(departments.values())
    for i in range(15):
        u = user("nurse" if i == 0 else f"nurse{i + 1:02d}", "Sam Okafor" if i == 0 else person(), "nurse")
        db.flush()
        db.add(Staff(user_id=u.id, department_id=dept_list[i % 8].id, staff_type="nurse",
                     shift=("day", "evening", "night")[i % 3]))
    for i in range(10):
        u = user("reception" if i == 0 else f"reception{i + 1:02d}", "Riley Costa" if i == 0 else person(),
                 "receptionist")
        db.flush()
        db.add(Staff(user_id=u.id, department_id=dept_list[i % 8].id, staff_type="receptionist"))
    db.flush()
    for u in (super_admin, admin):
        db.add(Staff(user_id=u.id, staff_type="administrator"))
    alex_user = user("patient", "Alex Morgan", "patient")
    db.flush()

    # ------------------------------------------------------------------ patients
    n_patients = max(60, int(520 * scale))
    dept_weights = [14, 10, 12, 12, 22, 14, 6, 10]
    patients: list[dict] = []
    profiles: list[dict] = []
    flaky: set[int] = set()  # patients with a history of missing appointments
    by_dept: dict[int, list[int]] = defaultdict(list)
    for _ in range(n_patients):
        pid = ids("patients")
        dept = departments["Cardiology"] if pid == 1 else rng.choices(dept_list, dept_weights)[0]
        age = 42 if pid == 1 else rng.randint(1, 15) if dept.name == "Pediatrics" else int(rng.triangular(18, 92, 46))
        name = "Alex Morgan" if pid == 1 else person()
        patients.append({
            "id": pid, "user_id": alex_user.id if pid == 1 else None, "mrn": f"MF-{100000 + pid}",
            "full_name": name, "date_of_birth": (today - timedelta(days=age * 365 + rng.randint(0, 364))).date(),
            "gender": rng.choices(["Female", "Male", "Other"], [49, 49, 2])[0],
            "phone": f"+1-555-01{rng.randint(10, 99)}", "status": "active",
            "email": f"patient@{DEMO_DOMAIN}" if pid == 1 else f"{name.lower().replace(' ', '.')}@example.org",
            "primary_department_id": dept.id,
            "created_at": now - timedelta(days=rng.choice([rng.randint(0, 56), rng.randint(57, 700)]),
                                          hours=rng.randint(0, 23)),
        })
        profiles.append({
            "patient_id": pid, "blood_group": rng.choice(["A+", "B+", "O+", "AB+", "A-", "O-", "B-"]),
            "allergies": rng.choices(["None known", "Penicillin", "Peanuts", "Latex", "Sulfa drugs"],
                                     [70, 10, 8, 6, 6])[0],
            "chronic_conditions": rng.choices(["None", "Hypertension", "Type 2 diabetes", "Asthma",
                                               "Hypertension, Type 2 diabetes"], [55, 16, 12, 10, 7])[0],
            "emergency_contact": f"{rng.choice(FIRST)} {name.split()[-1]} · +1-555-01{rng.randint(10, 99)}",
            "address": f"{rng.randint(1, 240)} {rng.choice(['Maple', 'Cedar', 'Lake', 'Hill', 'Park'])} Street",
            "insurance_provider": rng.choice(["Northstar Health", "Unity Care", "BlueRiver Mutual", "Self-pay"]),
        })
        by_dept[dept.id].append(pid)
        if pid != 1 and rng.random() < 0.1:
            flaky.add(pid)
    # Alex (patient 1) is the demo login: keep that record curated rather than randomly booked.
    by_dept[departments["Cardiology"].id].remove(1)
    child_ids = by_dept[departments["Pediatrics"].id]
    adult_ids = [p["id"] for p in patients if p["id"] != 1 and p["id"] not in set(child_ids)]

    # ------------------------------------------------------------------ wards, beds, 30 days of stays
    beds: list[dict] = []
    stays: list[dict] = []
    admitted: set[int] = set()
    for name, dept_name, ward_type, floor, prefix, n_beds, target, stay_days in WARDS:
        ward = Ward(name=name, department_id=departments[dept_name].id if dept_name else None, floor=floor,
                    ward_type=ward_type)
        db.add(ward)
        db.flush()
        pool = child_ids if ward_type == "pediatric" else adult_ids
        idle_mean_h = stay_days * 24 * (1 - target) / target
        for n in range(1, n_beds + 1):
            bed_id = ids("beds")
            t = now - timedelta(days=32) + timedelta(hours=rng.uniform(0, stay_days * 24))
            status, last_release = None, None
            while t < now:
                end = t + timedelta(hours=max(5.0, rng.expovariate(1 / (stay_days * 24))))
                patient_id = rng.choice(pool)
                if end > now:
                    while patient_id in admitted or patient_id == 1:
                        patient_id = rng.choice(pool)
                    admitted.add(patient_id)
                    stays.append({"id": ids("stays"), "bed_id": bed_id, "patient_id": patient_id, "assigned_at": t,
                                  "expected_discharge_at": end, "discharge_ordered_at": None, "released_at": None})
                    status = "occupied"
                    break
                # Discharge paperwork has been running ~21% slower over the last week.
                processing = max(0.5, rng.gauss(2.4, 0.5)) * (1.21 if end > now - timedelta(days=7) else 1.0)
                stays.append({"id": ids("stays"), "bed_id": bed_id, "patient_id": patient_id, "assigned_at": t,
                              "expected_discharge_at": end, "released_at": end,
                              "discharge_ordered_at": max(t, end - timedelta(hours=processing))})
                last_release = end
                t = end + timedelta(hours=rng.uniform(1, 4) + rng.expovariate(1 / idle_mean_h))
            if status is None:
                recently = last_release and now - last_release < timedelta(hours=2)
                status = "cleaning" if recently else rng.choices(
                    ["available", "maintenance", "reserved", "cleaning"], [82, 6, 7, 5])[0]
            beds.append({"id": bed_id, "ward_id": ward.id, "label": f"{prefix}-{n:02d}", "status": status,
                         "updated_at": now})
    for p in patients:
        if p["id"] in admitted:
            p["status"] = "admitted"
    _bulk(db, Patient, patients)
    _bulk(db, PatientProfile, profiles)
    _bulk(db, Bed, beds)
    _bulk(db, BedAssignment, stays)

    # ------------------------------------------------------------------ appointments
    appts: list[dict] = []
    history: list[dict] = []
    slot0 = now.replace(minute=now.minute - now.minute % 30, second=0)
    last_slot = today + timedelta(hours=23, minutes=30)
    # Alex's past visits with Dr. Sharma, so the patient portal has history.
    forced = {(sharma.id, today - timedelta(days=d) + timedelta(hours=10, minutes=30)) for d in (35, 21, 7)}

    def add_appt(doctor: Doctor, patient_id: int, when: datetime, status: str, kind: str, lead_days: int,
                 checked_in=None, started=None, completed=None) -> dict:
        row = {"id": ids("appointments"), "patient_id": patient_id, "doctor_id": doctor.id,
               "department_id": doctor.department_id, "scheduled_at": when, "duration_minutes": 30,
               "status": status, "appointment_type": kind,
               "reason": rng.choice(REASONS[dept_meta[doctor.department_id]["name"]]),
               "checked_in_at": checked_in, "started_at": started, "completed_at": completed,
               "created_at": min(now - timedelta(hours=1), when - timedelta(days=lead_days, hours=rng.randint(1, 20))),
               "created_by": None}
        appts.append(row)
        history.append({"appointment_id": row["id"], "from_status": None, "to_status": status,
                        "changed_by": None, "changed_at": completed or started or checked_in or row["created_at"]})
        return row

    for doctor in doctors:
        meta = dept_meta[doctor.department_id]
        dept_name, emergency = meta["name"], meta["name"] == "Emergency"
        pool = by_dept[doctor.department_id]
        for offset in range(-days_back, days_forward + 1):
            day = today + timedelta(days=offset)
            weekend = day.weekday() >= 5
            in_consult_today = False
            for half_hour in range(doctor.shift_start * 2, doctor.shift_end * 2):
                when = day + timedelta(minutes=30 * half_hour)
                is_forced = (doctor.id, when) in forced
                if doctor is sharma and offset == 0 and when >= slot0 - timedelta(minutes=60):
                    continue  # Dr. Sharma's live clinic is scripted below
                if emergency:
                    fill = 0.95 if 17 <= when.hour < 20 else 0.68
                    fill = min(0.98, fill * (1.12 if offset == 0 else 1.0))
                else:
                    fill = (0.72 if 9 <= when.hour < 13 else 0.58) * (0.4 if weekend else 1.0)
                if not is_forced and rng.random() > fill:
                    continue
                if is_forced:
                    patient_id = 1
                elif dept_name == "Pediatrics":
                    patient_id = rng.choice(child_ids)
                else:
                    patient_id = rng.choice(pool) if rng.random() < 0.75 else rng.choice(adult_ids)
                kind = ("emergency" if emergency else "procedure" if dept_name == "Radiology"
                        else rng.choices(["new", "follow_up"], [45, 55])[0])
                lead = 0 if emergency else rng.choices([0, 1, 2, 3, 5, 7, 14, 21, 30],
                                                       [6, 12, 14, 14, 14, 16, 12, 7, 5])[0]
                if when > now:  # ---- future
                    if offset == 0 and (when - now) < timedelta(minutes=20) and rng.random() < 0.4:
                        add_appt(doctor, patient_id, when, "waiting", kind, lead,
                                 checked_in=now - timedelta(minutes=rng.randint(1, 8)))
                    else:
                        status = "cancelled" if offset > 0 and rng.random() < 0.05 else "scheduled"
                        add_appt(doctor, patient_id, when, status, kind, lead)
                    continue
                # ---- past (including earlier today)
                p_no_show = 0.01 if emergency else min(0.5, 0.035 + min(0.12, 0.006 * lead)
                                                       + (0.22 if patient_id in flaky else 0)
                                                       + (0.03 if when.hour >= 16 else 0)
                                                       + (0.02 if kind == "new" else 0))
                roll = rng.random()
                if not is_forced and roll < p_no_show:
                    add_appt(doctor, patient_id, when, "no_show", kind, lead)
                    continue
                if not is_forced and roll < p_no_show + (0.02 if emergency else 0.07):
                    add_appt(doctor, patient_id, when, "cancelled", kind, lead)
                    continue
                checked_in = when - timedelta(minutes=0 if emergency else rng.randint(2, 14))
                started = checked_in + timedelta(minutes=_wait_minutes(rng, dept_name, meta["wait"], when, -offset))
                completed = started + timedelta(minutes=max(5.0, rng.gauss(doctor.avg_consult_minutes, 4)))
                if doctor is sharma and offset == 0 and completed > now:  # keep her live state scripted
                    completed = now - timedelta(minutes=9)
                    started = min(started, completed - timedelta(minutes=5))
                if completed <= now:
                    add_appt(doctor, patient_id, when, "completed", kind, lead, checked_in, started.replace(microsecond=0),
                             completed.replace(microsecond=0))
                elif not in_consult_today:
                    in_consult_today = True
                    began = min(now - timedelta(minutes=1), max(checked_in + timedelta(minutes=1),
                                                               now - timedelta(minutes=rng.randint(3, 12))))
                    add_appt(doctor, patient_id, when, "in_consultation", kind, lead, checked_in, began)
                else:
                    add_appt(doctor, patient_id, when, "waiting", kind, lead, checked_in)

    # Dr. Sharma's scripted live clinic: 1 in consultation, 4 waiting, Alex next, 3 more to come.
    cardio_pool = list(by_dept[sharma.department_id])
    rng.shuffle(cardio_pool)
    add_appt(sharma, cardio_pool.pop(), slot0 - timedelta(minutes=60), "in_consultation", "follow_up", 7,
             checked_in=slot0 - timedelta(minutes=66), started=now - timedelta(minutes=8))
    for minutes_before in (45, 30, 15, 0):
        when = slot0 - timedelta(minutes=minutes_before)
        add_appt(sharma, cardio_pool.pop(), when, "waiting", rng.choice(["new", "follow_up"]), 5,
                 checked_in=min(now - timedelta(minutes=1), when - timedelta(minutes=rng.randint(3, 8))))
    upcoming = sorted({min(last_slot, slot0 + timedelta(minutes=m)) for m in (30, 60, 90, 120)} - {slot0})
    for i, when in enumerate(upcoming):
        row = add_appt(sharma, 1 if i == 0 else cardio_pool.pop(), when, "scheduled", "follow_up", 7)
        if i == 0:
            row["reason"] = "Blood pressure review"

    _bulk(db, Appointment, appts)
    _bulk(db, AppointmentStatusHistory, history)

    # ------------------------------------------------------------------ today's queues
    doctor_by_id = {d.id: d for d in doctors}
    queues: dict[int, int] = {}
    entries: list[dict] = []
    token_counter: dict[int, int] = defaultdict(int)
    todays = sorted((a for a in appts if a["checked_in_at"] and a["scheduled_at"] >= today
                     and a["scheduled_at"] < today + timedelta(days=1)), key=lambda a: a["checked_in_at"])
    queue_rows = []
    for a in todays:
        if a["doctor_id"] not in queues:
            queues[a["doctor_id"]] = ids("queues")
            queue_rows.append({"id": queues[a["doctor_id"]], "doctor_id": a["doctor_id"],
                               "department_id": a["department_id"], "queue_date": today.date()})
        token_counter[a["department_id"]] += 1
        entries.append({"queue_id": queues[a["doctor_id"]], "appointment_id": a["id"], "patient_id": a["patient_id"],
                        "token": f"{dept_meta[a['department_id']]['code']}-{token_counter[a['department_id']]:03d}",
                        "status": a["status"], "priority": 0, "joined_at": a["checked_in_at"],
                        "called_at": a["started_at"], "completed_at": a["completed_at"]})
    _bulk(db, Queue, queue_rows)
    _bulk(db, QueueEntry, entries)

    # ------------------------------------------------------------------ visits, notes, prescriptions, documents
    visits, notes, prescriptions, documents = [], [], [], []
    for a in appts:
        if a["status"] != "completed":
            continue
        vid = ids("visits")
        doctor = doctor_by_id[a["doctor_id"]]
        dept_name = dept_meta[a["department_id"]]["name"]
        visits.append({"id": vid, "patient_id": a["patient_id"], "doctor_id": a["doctor_id"],
                       "department_id": a["department_id"], "appointment_id": a["id"],
                       "started_at": a["started_at"], "ended_at": a["completed_at"], "summary": a["reason"]})
        a["visit_id"] = vid
        mine = a["patient_id"] == 1
        if mine or rng.random() < 0.25:
            notes.append({"visit_id": vid, "author_id": doctor.user_id, "created_at": a["completed_at"],
                          "note": f"[Synthetic note] {a['reason']}. Patient reviewed, observations stable. "
                                  "Advised on follow-up and when to return."})
        if dept_name in MEDICATIONS and (mine or rng.random() < 0.18):
            med, dose, freq = rng.choice(MEDICATIONS[dept_name])
            prescriptions.append({"visit_id": vid, "patient_id": a["patient_id"], "doctor_id": a["doctor_id"],
                                  "medication": med, "dosage": dose, "frequency": freq, "duration_days": 30,
                                  "instructions": "Take as directed by your doctor.", "issued_at": a["completed_at"]})
        if mine or rng.random() < 0.08:
            title, kind = rng.choice([("Lab report · Lipid panel", "lab_report"),
                                      ("Lab report · Complete blood count", "lab_report"),
                                      ("Imaging report · Chest X-ray", "imaging"),
                                      ("Visit summary", "visit_summary")])
            documents.append({"patient_id": a["patient_id"], "title": title, "doc_type": kind,
                              "summary": "[Synthetic document] Results reviewed with the patient during the visit. "
                                         "No values are real.", "issued_at": a["completed_at"]})
    _bulk(db, Visit, [{k: v for k, v in row.items()} for row in visits])
    _bulk(db, ClinicalNote, notes)
    _bulk(db, Prescription, prescriptions)
    _bulk(db, MedicalDocument, documents)

    # ------------------------------------------------------------------ feedback (labelled by the classifier)
    completed = [a for a in appts if a["status"] == "completed"]
    sample = rng.sample(completed, min(len(completed), max(30, int(190 * scale))))
    sample += [a for a in completed if a["patient_id"] == 1][:1]
    feedback, complaints = [], []

    def clamp(v: float) -> int:
        return max(1, min(5, round(v)))

    for a in sample:
        fid = ids("feedback")
        dept_name = dept_meta[a["department_id"]]["name"]
        wait = (a["started_at"] - a["checked_in_at"]).total_seconds() / 60
        wait_rating = clamp((5 if wait < 15 else 4 if wait < 28 else 3 if wait < 40 else 2 if wait < 55 else 1)
                            + rng.choice([-1, 0, 0, 0, 1]))
        mood = rng.random()
        if wait_rating <= 2:
            key = ("emergency_care", "neg") if dept_name == "Emergency" and rng.random() < 0.35 else \
                ("waiting_time", "neg")
        elif mood < 0.13:
            key = (rng.choice(["staff_behavior", "doctor_communication", "billing", "cleanliness", "appointment",
                               "facilities", "pharmacy"]), "neg")
        elif mood < 0.30:
            key = ("general", "neu")
        else:
            key = (rng.choice(["waiting_time", "staff_behavior", "doctor_communication", "cleanliness",
                               "appointment", "facilities", "emergency_care"]), "pos")
        tone = {"neg": -1.6, "neu": -0.4, "pos": 0.6}[key[1]]
        scores = {f: clamp(4 + tone * (1.0 if f.startswith(key[0].split("_")[0]) else 0.45) + rng.gauss(0, 0.5))
                  for f in ("staff", "doctor", "cleanliness", "communication", "appointment_experience")}
        overall = clamp((wait_rating + sum(scores.values())) / 6 + tone * 0.5)
        comment = rng.choice(COMMENTS[key]).format(w=int(wait))
        label = classify(comment, overall, dept_name)
        created = min(now, a["completed_at"] + timedelta(hours=rng.randint(1, 48)))
        feedback.append({"id": fid, "patient_id": a["patient_id"], "department_id": a["department_id"],
                         "doctor_id": a["doctor_id"], "visit_id": a.get("visit_id"), "overall": overall,
                         "wait_time": wait_rating, **scores,
                         "nps": {5: rng.randint(9, 10), 4: rng.randint(7, 9), 3: rng.randint(5, 7),
                                 2: rng.randint(2, 5), 1: rng.randint(0, 3)}[overall],
                         "comment": comment, "sentiment": label.sentiment, "category": label.category,
                         "urgency": label.urgency, "theme": label.theme, "created_at": created})
        if label.sentiment == "negative" and label.urgency != "low":
            old = created < now - timedelta(days=10)
            complaints.append({"feedback_id": fid, "patient_id": a["patient_id"],
                               "department_id": a["department_id"], "category": label.category,
                               "urgency": label.urgency, "description": comment, "created_at": created,
                               "status": "resolved" if old else rng.choice(["open", "in_review"]),
                               "resolved_at": created + timedelta(days=3) if old else None})
    _bulk(db, Feedback, feedback)
    _bulk(db, Complaint, complaints)

    # ------------------------------------------------------------------ starter notifications
    alex_appt = next(a for a in appts if a["patient_id"] == 1 and a["status"] == "scheduled")
    db.add_all([
        Notification(user_id=alex_user.id, type="appointment_reminder", title="Appointment today",
                     body=f"Dr. Priya Sharma · Cardiology · {alex_appt['scheduled_at']:%I:%M %p}. "
                          "Check in from the Queue tab when you arrive.", link="/patient/appointments"),
        Notification(user_id=sharma.user_id, type="patient_waiting", title="4 patients waiting",
                     body="Your clinic queue has patients checked in.", link="/doctor/dashboard"),
    ])
    _sync_sequences(db)
    db.commit()
    return {"departments": len(DEPARTMENTS), "doctors": len(doctors), "nurses": 15, "receptionists": 10,
            "patients": len(patients), "appointments": len(appts), "queue_entries": len(entries),
            "beds": len(beds), "visits": len(visits), "feedback": len(feedback), "complaints": len(complaints)}
