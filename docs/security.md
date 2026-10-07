# Security and privacy

> This prototype demonstrates privacy-conscious architecture and is not certified for production clinical use. It has not been assessed for HIPAA, GDPR or any other regulatory regime, and all data in it is synthetic.

## Authentication

- **Passwords** are hashed with bcrypt (`security/auth.py`). Inputs are capped at 72 bytes, bcrypt's limit, and new passwords need 8+ characters with a letter and a number.
- **Access tokens** are short-lived JWTs (HS256, 30 minutes) sent as a bearer header and held **only in memory** in the browser.
- **Refresh tokens** live in an `httpOnly`, `SameSite=Lax` cookie scoped to `/api/auth` (`Secure` when `COOKIE_SECURE=true`). They are single-use: each refresh rotates the token, and **replaying a used token revokes the whole session family**.
- **Login** is rate-limited (10/minute per IP), returns one identical message for a wrong password and an unknown email, and verifies against a dummy hash when the email is unknown so timing does not reveal which accounts exist.
- **Deactivating a user** revokes their refresh tokens immediately.
- The app refuses to start with the placeholder `JWT_SECRET` when `APP_ENV=production`.

## Authorization (RBAC)

Roles and permissions are stored in `roles`, `permissions`, `user_roles` and `role_permissions`, seeded from one matrix in `security/rbac.py`. Routes declare what they need with `Depends(require("patients:read"))`; the check runs on every request against the database, not against claims in the token.

| Role | Scope |
|---|---|
| Patient | Own appointments, queue, documents, feedback, profile; the assistant |
| Doctor | Own schedule and queue; records of **their own patients only**; notes and prescriptions |
| Nurse | Wards, beds, queue; clinical view of patients |
| Receptionist | Registration, scheduling, check-in; **no clinical content, no analytics** |
| Administrator | Operations, analytics, AI insights, reports; **demographics without clinical content** |
| Super admin | Everything, plus users, audit log, knowledge base, RAG debugger, demo data |

Beyond role checks, **record-level rules** are enforced in the handlers:

- A patient can only ever reach their own record, appointments and conversations. A `patient_id` sent by a patient is ignored.
- A doctor opening the record of a patient they have never had an appointment with gets a 403, and the denied attempt is audited.
- Clinical content (notes, prescriptions, documents) is not loaded at all for roles without `clinical:read`.

The frontend mirrors these rules to hide navigation and pages, but that is presentation only; the API is the control.

## Audit logging

`audit_logs` records the user, action, resource type and id, result, IP, user agent and a short operational detail for: sign-in (success and failure), registration, patient record views (including denials), appointment changes, queue actions, consultations, bed changes, knowledge base changes, report exports, copilot queries, insight actions, user management and demo loads.

It deliberately **does not** store clinical notes, chat messages or feedback text. A chat escalation is logged as the category only (`EMERGENCY`), never what the user typed. Application logs record method, path, status and duration, with no query strings, bodies or headers.

## Input validation

- Every request body is a Pydantic model with `extra="forbid"`, explicit length and range limits, and literal types for enumerations. Query and path parameters are typed and bounded. Timestamps must be naive hospital-local values.
- Validation failures return a structured 422 listing the offending fields.
- Page sizes are capped at 100; report ranges at 92 days.

## SQL injection

All application SQL uses bound parameters through SQLAlchemy. `LIKE` patterns escape user wildcards. There is no string-built SQL from user input.

AI-generated SQL (the Operations Copilot) passes three independent layers, any one of which blocks a bad query:

1. **Validator** (`analytics/sql_guard.py`): parsed with sqlglot; exactly one statement, `SELECT` only, allow-listed tables, no schema-qualified names, no `pg_*` or other risky functions, no comments; wrapped in a hard row limit.
2. **Database role**: queries run as `medflow_ro`, which has `SELECT` on specific **columns** only. It cannot read names, contact details, emails, password hashes, clinical notes, chat messages or free-text feedback, and it cannot write.
3. **Session**: read-only transaction with a 5-second statement timeout.

## File upload security

Knowledge uploads require `knowledge:manage` and are checked for extension, size (10 MB, enforced by the API and by nginx), and **content**: PDF magic bytes, a valid DOCX zip structure, or valid UTF-8. Filenames are reduced to a safe character set and stored under a server-chosen name. Deletion only ever removes files inside the uploads directory. Uploaded files are parsed for text, never executed or served back as files.

## Document access control

Passages from deactivated or archived documents are excluded from retrieval, and `GET /rag/sources/{id}` returns 404 for them to anyone without `knowledge:manage`. Conversations belong to one user; other users, including administrators, receive 404.

## AI safety

- The assistant is positioned as an information and navigation assistant, never a diagnostic system. A disclaimer and an emergency notice are always visible.
- A deterministic classifier runs before retrieval. Emergencies and self-harm are escalated without calling the LLM. Diagnosis, treatment and dose-change requests receive refusals.
- A confidence gate prevents answers from weak or irrelevant context.
- An output validator blocks diagnosis claims, dosing instructions and clinician claims, and strips citations that do not correspond to a retrieved source.
- Retrieved text is treated as reference material: the prompt tells the model it is not instructions.
- The assistant has no access to patient records. The copilot cannot reach personal data at the database level.
- Insights and predictions are labelled as AI-generated recommendations or estimates with confidence and contributing factors. Nothing is acted on automatically.

## Transport and browser hardening

- nginx and the API set `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy` and a Content Security Policy. API responses are `Cache-Control: no-store`.
- CORS is restricted to configured origins. In the default deployment the SPA and API share one origin, so no cross-origin access is needed.
- The WebSocket authenticates with the access token in its first frame (not in the URL) and carries event names and identifiers only.
- **TLS is not terminated by this stack.** Put it behind an HTTPS reverse proxy and set `COOKIE_SECURE=true`, which also enables HSTS.

## Secrets

All secrets come from environment variables. `.env` is git-ignored; `.env.example` contains placeholders only. No API key is present in frontend code or returned by any endpoint; the settings page shows only whether a key is configured.

## Data minimisation and retention

- Search, directory and copilot results return the minimum fields needed for the screen.
- Bed maps omit occupant names for roles without `patients:read`.
- There is no retention automation: conversations, audit entries and notifications are kept until deleted. A production deployment needs retention policies, encryption at rest, backup controls and a data-processing assessment.

## Known gaps

No multi-factor authentication or SSO; no account lockout beyond rate limiting; rate limits are per process; no field-level encryption; the safety classifier is rule-based and will miss unusual phrasings.
