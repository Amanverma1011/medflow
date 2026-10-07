# API reference

Base path `/api`. Interactive OpenAPI documentation is served at `/api/docs`.

**Authentication:** `Authorization: Bearer <access token>` on everything except `/auth/login`, `/auth/register`, `/auth/refresh`, `/health` and `/clock`.
**Timestamps:** hospital-local, without a zone, for example `2026-10-07T10:30:00`.
**Pagination:** `page` (from 1) and `size` (max 100); responses are `{ "items": [], "total": 0, "page": 1, "size": 25 }`.

**Errors** always use one envelope:

```json
{ "error": { "code": "validation_error", "message": "The request was not valid.",
             "details": [{ "field": "scheduled_at", "message": "Input should be a valid datetime" }] } }
```

| Status | Meaning |
|---|---|
| 400 | Rejected by a business rule (for example, booking in the past) |
| 401 | Missing, invalid or expired session |
| 403 | Authenticated, but the role or record-level rule forbids it |
| 404 | Not found, or not visible to this user |
| 409 | Conflicts with current state (slot taken, bed occupied, invalid status change) |
| 413 / 422 | Upload too large / request failed validation |
| 429 | Rate limited; see `Retry-After` |
| 500 / 502 | Server error / AI provider unavailable |

The *Permission* column lists what the caller needs; "own" means the endpoint scopes results to the caller.

## Auth

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/auth/login` | public | `{email, password}` → `{access_token, expires_in, user}` and sets the refresh cookie |
| POST | `/auth/register` | public | Creates a **patient** account |
| POST | `/auth/refresh` | cookie | Rotates the refresh token |
| POST | `/auth/logout` | cookie | Revokes the refresh token |
| GET / PATCH | `/auth/me` | signed in | Profile; patients can update contact details |

## Patients, doctors, departments

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/patients` | `patients:read` | `q`, `department_id`, `doctor_id`, `status`, `appointment_date`. Doctors see their own patients. |
| POST | `/patients` | `patients:write` | Register a patient |
| GET | `/patients/me` | patient | Own full record |
| GET | `/patients/{id}` | own, or `patients:read` | Clinical sections only with `clinical:read`. Audited. |
| GET | `/doctors` | signed in | `q`, `department_id` |
| GET | `/doctors/{id}/slots?day=` | signed in | Bookable slots for a day |
| GET | `/departments` | signed in | With today's load, 7-day wait, satisfaction |
| GET | `/staff` | `staff:read` | Nurses, receptionists, administrators |

## Appointments

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/appointments` | own, or `appointments:read` | `date_from`, `date_to`, `doctor_id`, `department_id`, `patient_id`, `status`, `q`, `newest_first` |
| GET | `/appointments/calendar?month=YYYY-MM` | same | Per-day counts for the month view |
| POST | `/appointments` | own, or `appointments:write` | `{doctor_id, scheduled_at, appointment_type, reason, patient_id?}` |
| GET | `/appointments/{id}` | same | |
| PATCH | `/appointments/{id}` | own, or `appointments:write` | `{scheduled_at}` to reschedule; `{status: "cancelled" \| "no_show"}` (no-show is staff only) |

## Queue

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/queues` | `queue:read` | Today's queues; `department_id`, `doctor_id`. Doctors see their own. |
| GET | `/queues/me` | patient | Live position, explained estimate, and appointments ready for check-in |
| POST | `/queues/check-in` | own, or `queue:manage` | `{appointment_id}` → token and estimate |
| POST | `/queues/{queue_id}/call-next` | `queue:manage` | 409 while a consultation is open |
| POST | `/queues/entries/{id}/complete` | `queue:manage` | `{note?, prescription?}`; note and prescription need `clinical:write` |
| POST | `/queues/entries/{id}/skip` | `queue:manage` | Moves the patient to the back |
| POST | `/queues/entries/{id}/prioritize` | `queue:manage` | |
| POST | `/queues/entries/{id}/transfer` | `queue:manage` | `{doctor_id}` |

## Beds

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/beds` | `beds:read` | Wards with beds; occupant names only with `patients:read` |
| GET | `/beds/analytics` | `beds:read` | Occupancy trend, stay, turnover, discharge processing |
| GET | `/beds/tasks` | `beds:read` | Turnarounds and upcoming discharges |
| PATCH | `/beds/{id}` | `beds:manage` | `{status: available \| cleaning \| maintenance \| reserved}` |
| POST | `/beds/{id}/assign` | `beds:manage` | `{patient_id, expected_discharge_at?}` |
| POST | `/beds/{id}/release` | `beds:manage` | Discharge; bed goes to cleaning |

## Feedback and notifications

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/feedback` | `feedback:write` | Seven ratings, NPS, comment → stored with AI classification |
| GET | `/feedback/mine` | patient | Own feedback and visits awaiting feedback |
| GET | `/feedback` | `experience:read` | `sentiment`, `category`, `department_id` |
| GET | `/notifications` | signed in | Latest 40 with unread count |
| POST | `/notifications/{id}/read`, `/notifications/read-all` | signed in | |

## Analytics

All accept `days` (1 to 90), `department_id`, `doctor_id` unless noted. Each chart block is `{data, range, metric?}`.

| Method | Path | Permission |
|---|---|---|
| GET | `/analytics/overview` | `analytics:read` |
| GET | `/analytics/operations`, `/patients`, `/appointments`, `/doctors`, `/beds`, `/queue-status` | `analytics:read` |
| GET | `/analytics/patient-experience` | `experience:read` |
| GET | `/doctor/dashboard` | `clinical:write` |

## AI

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/ai/insights` | `insights:read` | Active insights, most severe first |
| POST | `/ai/insights/refresh` | `insights:read` | Re-run the InsightEngine |
| POST | `/ai/insights/{id}/dismiss` | `insights:read` | |
| GET | `/ai/predictions` | `insights:read` | Volume, no-show, wait time, bed occupancy, each with confidence and factors |
| GET | `/ai/copilot/suggestions` | `copilot:use` | |
| POST | `/ai/copilot` | `copilot:use` | `{question}` → `{intent, answer, queries: [{sql, params, rows}], chart, data}` |

## RAG

| Method | Path | Permission | Notes |
|---|---|---|---|
| POST | `/rag/chat` (alias `/chat`) | `chat:use` | `{message, conversation_id?}` → full answer |
| POST | `/rag/chat/stream` | `chat:use` | Server-Sent Events: `meta`, `token`…, `done` (or `error`) |
| GET | `/rag/status` | `chat:use` | Providers, demo-mode flags, suggestions, disclaimers |
| GET | `/rag/conversations` (alias `/chat/conversations`) | `chat:use` | Own conversations |
| GET / DELETE | `/rag/conversations/{id}` | owner | |
| POST | `/rag/messages/{id}/feedback` | owner | `{value: -1 \| 0 \| 1}` |
| GET | `/rag/sources/{chunk_id}` | `chat:use` | The passage behind a citation |
| GET / POST | `/rag/documents` (alias `/knowledge/documents`) | `knowledge:manage` | POST is multipart: `file`, `name?`, `kb`, `source_type`, `version` |
| GET / PATCH / DELETE | `/rag/documents/{id}` | `knowledge:manage` | PATCH `{is_active?, archived?}` |
| POST | `/rag/ingest` (alias `/knowledge/ingest`) | `knowledge:manage` | `{document_id?}`; omit to re-index everything |
| POST | `/rag/debug` | `rag:debug` | Full pipeline trace for one question |
| POST | `/rag/evaluate` | `rag:debug` | Run the evaluation set |

`POST /rag/chat` response:

```json
{
  "conversation_id": 12, "message_id": 48,
  "answer": "**Short answer**\n\nHypertension is a condition where blood pressure remains consistently above the healthy range. [1]",
  "sources": [{ "index": 1, "chunk_id": 31, "document": "Hospital Hypertension Guide", "section": "What is hypertension",
                "page": 1, "kb": "medical", "version": "2.1", "score": 1.0, "semantic": 0.32, "keyword": 1.0, "cited": true }],
  "confidence": 0.89, "safety_category": "GENERAL_INFORMATION", "knowledge_scope": "medical",
  "follow_ups": ["What does the Hospital Hypertension Guide say about causes and risk factors?"],
  "flags": [], "grounded": true,
  "disclaimer": "This AI assistant provides general medical information and is not a substitute for professional medical advice, diagnosis, or treatment."
}
```

## Reports, search, administration

| Method | Path | Permission | Notes |
|---|---|---|---|
| GET | `/reports` | `reports:read` | The seven report types |
| GET | `/reports/{kind}` | `reports:read` | `date_from`, `date_to`, `department_id`, `format=json \| csv \| pdf` |
| GET | `/search?q=` | signed in | Patients, doctors, departments, appointments, documents, knowledge; filtered by role |
| GET / POST | `/users` | `users:manage` | |
| PATCH | `/users/{id}` | `users:manage` | `{roles?, is_active?}` |
| GET | `/roles` | `users:manage` | Roles with permissions and user counts |
| GET | `/audit-logs` | `audit:read` | `action` (prefix), `result`, `q` |
| GET | `/settings/system` | `settings:read` | Runtime configuration, with secrets redacted |
| POST | `/demo/load` | `demo:load` | Wipe and reload the demo hospital |
| GET | `/health`, `/clock` | public | Liveness; hospital-local time |

## WebSocket

Connect to `/ws` and send `{"type": "auth", "token": "<access token>"}` as the first frame. The server replies `{"type": "ready"}` and then pushes events such as `{"type": "queue.updated", "queue_id": 3}`. Events contain identifiers only; fetch the data through the REST API.
