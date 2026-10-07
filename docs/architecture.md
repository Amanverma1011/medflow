# Architecture

## Overview

```text
┌──────────────────────────────────────────────────────────────────────────────┐
│ Frontend (React + TypeScript, Vite)                                          │
│  pages/ ── layouts/ ── components/ ── charts/                                │
│  services/queries.ts  (TanStack Query: all server state)                     │
│  hooks/useAuth (session) · hooks/useRealtime (WebSocket → cache invalidation)│
│  lib/api.ts  (bearer token in memory, silent refresh, SSE reader)            │
└───────────────▲──────────────────────────────────────────▲───────────────────┘
                │ REST + Server-Sent Events                │ WebSocket
┌───────────────┴──────────────────────────────────────────┴───────────────────┐
│ API layer (FastAPI)            backend/app/api/                              │
│  auth · patients · directory · appointments · queues · beds · feedback       │
│  analytics · rag · reports · admin                                           │
│  Pydantic request schemas · permission dependencies · audit · rate limits    │
└───────────────┬──────────────────────────────────────────────────────────────┘
                ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│ Service layer                  backend/app/services/                         │
│  appointments (state machine) · queue · beds · notifications · feedback_ai   │
│  seed / bootstrap (demo hospital)                                            │
├──────────────────────────────────────────────────────────────────────────────┤
│ Analytics                      backend/app/analytics/                        │
│  metrics · predictions · insights (InsightEngine) · copilot · sql_guard      │
├──────────────────────────────────────────────────────────────────────────────┤
│ AI layer                       backend/app/ai/        backend/app/rag/       │
│  providers (LLM, Embedding, Reranker)                 ingest · retrieval     │
│  safety (classifier + output validator)               pipeline · prompt      │
│  text (shared tokeniser)                              evaluate               │
└───────────────┬───────────────────────────────┬──────────────────────────────┘
                ▼                               ▼
┌──────────────────────────────┐   ┌──────────────────────────────────────────┐
│ PostgreSQL 16                │   │ LLM / embedding provider (optional)      │
│  relational schema (37 tbls) │   │  any OpenAI-compatible HTTP API          │
│  pgvector  (HNSW, cosine)    │   │  or the built-in demo fallbacks          │
│  full-text (tsvector + GIN)  │   └──────────────────────────────────────────┘
│  roles: medflow, medflow_ro  │
└──────────────────────────────┘
```

## Request flow

Every feature follows `UI → API → business logic → database`. For example, checking in:

```text
Patient taps "Check me in"
  → POST /api/queues/check-in            api/queues.py: is this the caller's own appointment?
  → services/queue.check_in              appointment: scheduled → checked_in → waiting
                                         queue entry created, token issued (A-027)
                                         notifications queued for patient and doctor
  → commit                               after_commit hook publishes "queue.updated"
  → WebSocket fan-out                    doctor dashboard, staff queue and patient page refetch
  → wait estimate recalculated           queue length × measured consultation pace
```

## Backend layout

| Package | Responsibility |
|---|---|
| `core/` | Settings, database engines, hospital clock, structured errors, rate limiter, WebSocket hub |
| `models/` | SQLAlchemy models, grouped by domain |
| `schemas/` | Pydantic request models (`extra="forbid"`, length and range limits) |
| `security/` | Hashing, JWT, refresh rotation, permission dependencies, RBAC matrix, audit helper |
| `api/` | Thin routers: authorise, validate, call a service, audit, commit |
| `services/` | Business rules and state transitions |
| `repositories/` | Read models that need joined SQL (patient directory and record, appointment search) |
| `analytics/` | Metrics, predictions, insight detectors, copilot and its SQL sandbox |
| `ai/`, `rag/` | Provider abstraction, safety, and the retrieval pipeline |

Routers stay thin on purpose: a rule such as "a doctor cannot hold two live appointments in one slot" lives in exactly one service function, backed by a database constraint.

## Frontend layout

| Folder | Responsibility |
|---|---|
| `pages/` | One file per screen, lazy-loaded per route |
| `layouts/` | Staff shell (sidebar, header, command palette) and patient shell (mobile tab bar) |
| `components/` | `ui.tsx` primitives, `data.tsx` tables and metrics, `cards.tsx` domain cards, chat parts, bed grid, booking modal |
| `charts/` | Chart kit: `ChartCard`, line, area, bar, donut, scatter, heatmap, with one colour system |
| `services/queries.ts` | `useGet` and `useAction`: every read and write, with consistent caching, toasts and invalidation |
| `hooks/` | Auth session, realtime, theme, toasts, debounce |
| `lib/` | HTTP client and formatting (including the hospital clock) |

State is kept separate: **server state** in TanStack Query, **authentication** in one context, **chat state** local to the assistant page, and **UI state** (theme, toasts, modals) local or in small hooks. There is no global store.

## Realtime

The server publishes small events (`queue.updated`, `appointment.updated`, `bed.updated`, `notification.new`, `insight.updated`, `feedback.new`) that carry identifiers only. The client maps each event to query groups and refetches through the normal authorised API, so the socket never carries patient data and needs no per-message authorisation logic. Events are published from an `after_commit` hook, which means a client that refetches immediately always sees the committed state. Live screens also poll every 15 to 30 seconds as a fallback.

## Time

Domain timestamps are stored as naive wall-clock times in the hospital's timezone (`HOSPITAL_TZ`). "Today", shift hours and hour-of-day analytics therefore mean the same thing in SQL, Python and the browser, and the UI asks the server for the hospital clock rather than trusting the device. JWT expiry uses real UTC.

## Deliberate simplifications

Marked in code with `ponytail:` comments, each naming its ceiling and upgrade path:

- In-memory rate limiter and WebSocket hub: per process. Use Redis for more than one replica.
- Synchronous database calls inside the async chat handlers: fine at demo concurrency; move to an async session if chat traffic grows.
- Lexical reranker and lexicon feedback classifier: transparent and deterministic; replace behind their interfaces for quality.
