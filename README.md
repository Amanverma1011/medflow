# MedFlow AI

**AI-powered hospital operations, patient experience, and medical intelligence, unified in one platform.**

MedFlow AI is a full-stack demo product: a hospital command center, role-specific workspaces for six kinds of user, a live digital queue, bed management, analytics, an explainable insight engine, a natural-language Operations Copilot, and a Medical Assistant built on real Retrieval-Augmented Generation with citations and a medical safety layer.

> **Synthetic data only.** Every patient, doctor, record and document is fictional. This prototype demonstrates privacy-conscious architecture and is **not certified for production clinical use**. It makes no claim of HIPAA or GDPR compliance.

## Contents

[Features](#features) · [Architecture](#architecture) · [Tech stack](#tech-stack) · [Setup](#setup) · [Environment variables](#environment-variables) · [Database](#database) · [RAG pipeline](#rag-pipeline) · [AI architecture](#ai-architecture) · [API](#api-documentation) · [Demo accounts](#demo-accounts) · [Security](#security) · [Testing](#testing) · [Limitations](#limitations) · [Future improvements](#future-improvements) · [Screenshots](#screenshots)

## Features

| Area | What works |
|---|---|
| **Command center** | Live status strip, patient flow, department load, bed map, AI alerts, queue status, satisfaction. Every number is computed from the database. |
| **Roles & RBAC** | Patient, doctor, nurse, receptionist, administrator, super admin. 24 permissions enforced on every API route; the UI hides what a role cannot use. |
| **Appointments** | Day / week / month calendar, doctor availability, booking, rescheduling, cancellation, no-show, status history. Double-booking is prevented by a database constraint. |
| **Digital queue** | Check-in issues a token (`A-047`), live position and an explained wait estimate. Staff can call next, skip, prioritise, complete and transfer. Updates push over WebSocket. |
| **Doctor workspace** | Today's schedule, waiting patients, current consultation, notes and prescriptions, operational workload summary. |
| **Beds** | Ward map with five bed states, admit / discharge / turnaround, ward tasks, occupancy analytics. |
| **Patient experience** | Ratings by dimension, NPS, sentiment, recurring themes. Feedback is auto-classified for sentiment, category, urgency and theme. |
| **Analytics** | Seven tabs with date, department and doctor filters. Line, area, bar, stacked, donut, scatter and heatmap charts. |
| **AI insights** | `InsightEngine` detectors (ED inflow surge, ICU capacity, no-show risk, discharge delay, wait outliers, complaint themes, staffing), each with evidence, confidence and a recommendation for human review. |
| **Predictions** | Patient volume, no-show risk, wait time and bed occupancy, each with confidence and contributing factors. |
| **Operations Copilot** | Natural language → intent → SQL → validation → read-only execution → explanation, with the query and rows shown. |
| **Medical Assistant** | Streaming chat, hybrid retrieval, reranking, citations, source viewer, follow-ups, feedback, conversation history, safety classification and emergency escalation. |
| **Knowledge base** | Upload PDF / DOCX / TXT / Markdown, view chunks, re-index, deactivate, archive, delete. |
| **RAG debugger** | Per-question trace of every pipeline stage, plus an evaluation runner. |
| **Reports** | Seven reports with date and department filters, CSV and PDF export. |
| **Platform** | Global search (Ctrl + K), notifications, audit log, dark mode, responsive layouts, mobile-first patient portal. |

## Architecture

```text
 Browser (React SPA)
        │  HTTPS  /api/*  (REST + SSE)        /ws (WebSocket)
        ▼
 nginx  ── serves the built SPA, proxies API and WebSocket (single origin)
        ▼
 FastAPI ─ api/ ──────────► services/ ─────────► models/ (SQLAlchemy)
   │        routers, RBAC     appointments,           │
   │        validation        queue, beds, seed       ▼
   │                                           PostgreSQL 16
   ├─ analytics/  metrics · predictions · InsightEngine · copilot ──► read-only role
   │
   └─ rag/ + ai/  ingest → chunk → embed ──► pgvector (HNSW, cosine)
                  query → safety → hybrid search (pgvector + full-text) → rerank
                        → confidence gate → LLM → citations → safety validation
                                              │
                                    LLMProvider / EmbeddingProvider / Reranker
                                    (OpenAI-compatible API, or local demo fallback)
```

More detail: [docs/architecture.md](docs/architecture.md).

## Tech stack

**Frontend:** React 19, TypeScript, Vite, Tailwind CSS 4, React Router 7, TanStack Query 5, Recharts 3, Framer Motion, Lucide.
**Backend:** Python 3.11+, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic, PyJWT, bcrypt, sqlglot.
**Data:** PostgreSQL 16 with pgvector.
**Infrastructure:** Docker Compose (postgres, backend, frontend/nginx).

## Setup

### Option A: Docker (one command)

```bash
cp .env.example .env        # then set JWT_SECRET
docker compose up --build
```

Open **http://localhost:8080**. On first start the backend runs migrations and, because `AUTO_SEED=true`, loads the demo hospital (about ten seconds). The API is also exposed at http://localhost:8000 with interactive docs at `/api/docs`.

### Option B: Local development

You need Python 3.11+, Node 20+, and PostgreSQL 16 with the `vector` extension. The simplest database is the one from Compose:

```bash
docker compose up -d postgres            # PostgreSQL + pgvector on localhost:5433
cp .env.example .env

cd backend
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
python ../scripts/seed_database.py
uvicorn app.main:app --reload --port 8000

cd ../frontend
npm install
npm run dev                              # http://localhost:5174 (proxies /api and /ws to :8000)
```

### The hospital clock

"Today", shift hours and the live queue follow `HOSPITAL_TZ`, and the UI shows that clock in the header. The seed anchors live data to the current hospital time, so **if you run the demo late at night the outpatient clinics will be quiet**, as they would be. Either reload the demo during the day (Settings → Demo mode → *Load Demo Hospital*), or set `HOSPITAL_TZ` to a zone where it is currently daytime and reload.

### Scripts

| Command | Purpose |
|---|---|
| `python scripts/seed_database.py` | Wipe and load the full demo hospital, knowledge base and insights. `--if-empty` skips when data exists. |
| `python scripts/generate_demo_data.py --scale 0.2` | Regenerate structured data only, at a chosen size. |
| `python scripts/ingest_documents.py [folder]` | Ingest documents into pgvector. Unchanged files are skipped. |
| `python scripts/evaluate_rag.py --details` | Run the RAG evaluation set. Exits non-zero if a safety case fails. |

## Environment variables

All configuration is read from the environment (see [.env.example](.env.example)). Nothing secret is ever sent to the browser.

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://medflow:medflow@localhost:5433/medflow` | Compose overrides the host to `postgres`. |
| `ANALYTICS_DB_PASSWORD` | `medflow_ro` | Password of the SELECT-only copilot role created by migration `0002`. |
| `JWT_SECRET` | *(insecure placeholder)* | **Set this.** The app refuses to start in `APP_ENV=production` with the placeholder. |
| `ACCESS_TOKEN_MINUTES` / `REFRESH_TOKEN_DAYS` | `30` / `7` | |
| `COOKIE_SECURE` | `false` | Set `true` behind HTTPS. |
| `CORS_ORIGINS` | dev origins | Comma-separated. |
| `HOSPITAL_TZ` | `UTC` | IANA timezone of the hospital. |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | blank | Any OpenAI-compatible chat API. Blank = demo mode. |
| `EMBEDDING_BASE_URL`, `EMBEDDING_API_KEY`, `EMBEDDING_MODEL` | blank | Any OpenAI-compatible embeddings API. Blank = local embedder. |
| `VECTOR_DIMENSION` | `384` | Must match the embedding model. Changing it needs a migration and a re-ingest. |
| `RAG_ALPHA`, `RAG_BETA`, `RAG_TOP_K`, `RAG_FINAL_K`, `RAG_MIN_CONFIDENCE` | `0.6`, `0.4`, `20`, `5`, `0.42` | Hybrid weights, candidate counts, refusal threshold. |
| `AUTO_SEED` | `true` in Compose | Seed the demo hospital when the database is empty. |
| `DEMO_PASSWORD` | `MedFlow#2026` | Password for all seeded demo accounts. |

## Database

37 tables managed by Alembic (`backend/alembic/versions`):

- **Identity:** `users`, `roles`, `permissions`, `user_roles`, `role_permissions`, `refresh_tokens`
- **Hospital:** `departments`, `doctors`, `staff`, `patients`, `patient_profiles`, `wards`, `beds`, `bed_assignments`
- **Clinical workflow:** `appointments`, `appointment_status_history`, `queues`, `queue_entries`, `visits`, `clinical_notes`, `prescriptions`, `medical_documents`
- **Experience & operations:** `feedback`, `complaints`, `notifications`, `audit_logs`
- **AI:** `ai_conversations`, `ai_messages`, `documents`, `document_chunks`, `document_embeddings`, `ai_predictions`, `ai_insights`

Notable constraints and indexes: a partial unique index stops two live appointments sharing a doctor and slot; `document_embeddings.embedding` has an HNSW index with `vector_cosine_ops`; `document_chunks.tsv` is a generated `tsvector` column with a GIN index; status columns carry `CHECK` constraints.

The seed creates 1 hospital, 8 departments, 25 doctors, 15 nurses, 10 receptionists, 520 patients, about 12,000 appointments over 45 days, 124 beds with 30 days of stays, about 190 feedback entries and 24 knowledge documents.

## RAG pipeline

```text
question → preprocess → safety classification → embed → hybrid search (pgvector + full-text, metadata-filtered)
         → rerank top 20 → keep top 5 → confidence gate → prompt → LLM → citation extraction → safety validation → answer
```

- **Hybrid score** = `α × semantic_similarity + β × normalised_keyword_score`.
- **Two knowledge bases**, medical and hospital. Navigation questions search the hospital base and answers are labelled *Medical Information* or *Hospital Information*.
- **No confident answers from weak evidence.** Below `RAG_MIN_CONFIDENCE` the LLM is not called; the user is told the knowledge base does not cover the question.
- **Safety first.** Emergencies and self-harm get a short escalation with no retrieval or generation. Diagnosis, treatment and dose-change requests get a refusal, then general information only if evidence is strong.

Full write-up, including evaluation: [docs/rag.md](docs/rag.md).

## AI architecture

Three small interfaces in `backend/app/ai/providers.py` isolate every vendor:

```python
class LLMProvider:        async def generate(prompt) -> str;  def stream(prompt) -> AsyncIterator[str]
class EmbeddingProvider:  async def embed(texts) -> list[list[float]]
class Reranker:           async def rerank(query, documents) -> list[float]
```

| Capability | With API keys | Demo mode (no keys) |
|---|---|---|
| Answer generation | Any OpenAI-compatible chat model | **Extractive composer**: selects and cites sentences from the retrieved passages. It cannot invent content. |
| Embeddings | Any OpenAI-compatible embedding model | **Feature-hashing embedder**: a real 384-dimension vector space stored in pgvector, capturing lexical rather than semantic similarity. |
| Reranking | Lexical coverage reranker | Same |
| Copilot | Reviewed SQL templates, plus LLM-generated SQL for unmatched questions | Reviewed SQL templates only |
| Safety classifier, insights, predictions, feedback classifier | Deterministic | Deterministic |

Demo mode is labelled in the UI. The retrieval, reranking, citation and safety code paths are identical in both modes.

## API documentation

Interactive OpenAPI docs are served at **`/api/docs`**. A grouped reference with examples is in [docs/api.md](docs/api.md). Errors always use one envelope:

```json
{ "error": { "code": "conflict", "message": "That slot has just been taken. Please choose another time.", "details": null } }
```

## Demo accounts

All accounts use the password **`MedFlow#2026`** (configurable with `DEMO_PASSWORD`). The login page has one-click buttons for each.

| Role | Email | Try this |
|---|---|---|
| Administrator | `admin@demo.medflow.ai` | Command Center → AI Insights → Operations Copilot: *"Why is the emergency department overloaded?"* |
| Doctor | `doctor@demo.medflow.ai` | Dr. Priya Sharma: complete the current consultation, call the next patient |
| Patient | `patient@demo.medflow.ai` | Alex Morgan: check in for today's appointment, watch the queue, ask the assistant |
| Super Admin | `superadmin@demo.medflow.ai` | Medical Knowledge → upload a guide; RAG Debugger; Audit Logs; Load Demo Hospital |
| Nurse | `nurse@demo.medflow.ai` | Beds: admit, discharge, turn a bed around |
| Receptionist | `reception@demo.medflow.ai` | Register a patient, book and check in |

## Security

Password hashing (bcrypt), short-lived JWT access tokens held in memory, rotating httpOnly refresh cookies with reuse detection, permission checks on every route, Pydantic validation of every input, rate limiting, security headers and CSP, parameterised SQL throughout, content-validated uploads, an audit log that never stores clinical text, and a SELECT-only database role with column-level grants for AI-generated SQL. Details: [docs/security.md](docs/security.md).

## Testing

```bash
# Backend: 105 tests against a real PostgreSQL + pgvector database (name must end in _test)
cd backend
TEST_DATABASE_URL=postgresql+psycopg://medflow:medflow@localhost:5433/medflow_test pytest

# Frontend: 27 tests (components, routing and access, login, chat UI)
cd frontend
npm test && npm run typecheck
```

Backend tests cover authentication, authorization, appointments, queue logic, bed assignment, RAG retrieval, citations, chatbot safety, document ingestion, the SQL sandbox, analytics and reports.

## Limitations

- **Not for clinical use.** No compliance assessment has been done. There is no encryption at rest beyond what your database provides, and TLS termination is left to your reverse proxy.
- **Demo-mode AI is lexical.** Without an embedding model, paraphrased questions that share no words with the source text retrieve poorly. Without an LLM, answers are extracted sentences rather than written prose.
- **The safety classifier is rule-based.** It is deterministic and auditable but will miss unusual phrasings; it complements, and does not replace, clinical governance.
- **Predictions are simple statistics** fitted to synthetic history. They illustrate explainable forecasting, not validated clinical models.
- **Evaluation metrics for generation are lexical-overlap proxies**, exact for the extractive mode and a lower bound for a real LLM.
- **Not implemented:** nurse vitals charting, a persistent nurse task list (ward tasks are derived from bed state), email/SMS delivery of notifications (they are in-app), multi-hospital tenancy, runtime editing of settings (configuration is environment-driven).
- **Single-process realtime and rate limiting.** The WebSocket hub and rate limiter live in memory, so running several backend replicas needs Redis.
- **Docker images were not build-tested on the authoring machine**, where the Docker engine could not start. The backend and frontend were verified by running them directly against PostgreSQL 16 + pgvector.

## Future improvements

- Cross-encoder reranker and an LLM judge for evaluation.
- Redis for pub/sub, rate limiting and caching; async SQLAlchemy sessions on the chat path.
- Calibrated, back-tested prediction models, with forecasts scored against outcomes (`ai_predictions` already stores the snapshots).
- Patient-specific assistant context behind an explicit consent and authorisation layer.
- SSO (OIDC), multi-factor authentication, field-level encryption, retention policies.
- FHIR import/export; notification delivery by email and SMS.

## Screenshots

Run the app and sign in with a demo account to see it live. Key screens: `/admin/command-center`, `/admin/ai-insights?tab=copilot`, `/admin/rag-debug`, `/patient/queue`, `/patient/chat`, `/doctor/dashboard`. To add images here, save them under `docs/screenshots/` and link them.
