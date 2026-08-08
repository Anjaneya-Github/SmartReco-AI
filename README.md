# SmartReco AI

> **AI-powered personalized learning recommendation engine** — built with FastAPI, LangGraph, PostgreSQL, Qdrant, Redis, and Mesh API.

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.12-blue)](https://python.org)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-orange)](https://langchain-ai.github.io/langgraph)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-blue)](https://postgresql.org)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Features](#2-features)
3. [Architecture](#3-architecture)
4. [ER Diagram](#4-er-diagram)
5. [LangGraph Workflow](#5-langgraph-workflow)
6. [Recommendation Pipeline](#6-recommendation-pipeline)
7. [Folder Structure](#7-folder-structure)
8. [Installation](#8-installation)
9. [Docker Setup](#9-docker-setup)
10. [Environment Variables](#10-environment-variables)
11. [Mesh API Configuration](#11-mesh-api-configuration)
12. [Redis Configuration](#12-redis-configuration)
13. [Qdrant Configuration](#13-qdrant-configuration)
14. [Authentication](#14-authentication)
15. [Dashboard](#15-dashboard)
16. [Caching Strategy](#16-caching-strategy)
17. [AI Guardrails](#17-ai-guardrails)
18. [Scheduler](#18-scheduler)
19. [LangSmith Tracing](#19-langsmith-tracing)
20. [API Endpoints](#20-api-endpoints)
21. [Development Steps](#21-development-steps)

---

## 1. Project Overview

SmartReco AI is a **hackathon-grade production system** that analyses user learning behaviour and delivers AI-generated course recommendations in real time.

Every user interaction (view, click, search, purchase, wishlist, rating) is tracked as a behavioral event. The **Behavior Intelligence Layer** converts those events into a rich profile. A **LangGraph workflow** retrieves semantically similar courses from a Qdrant vector store and calls a **Mesh API LLM** to compose a personalised recommendation story. Results are cached in Redis, persisted to PostgreSQL, and served from a Bootstrap 5 dashboard — all without regenerating on every page load.

---

## 2. Features

| Category | Feature |
|---|---|
| **Auth** | JWT authentication, RBAC (user / admin), bcrypt password hashing |
| **Products** | Full CRUD with PostgreSQL + Qdrant dual-write and semantic embeddings |
| **Event Tracking** | Batch event ingest (1–500 events), 8 event types, auto-trigger logic |
| **Behavior Intelligence** | InterestExtractor, EngagementScorer, BehaviorAnalyzer — pure Python, DB-free |
| **Recommendation Trigger** | 4 rules: new events threshold, repeated search, purchase/wishlist, inactivity |
| **LangGraph Workflow** | 8-node stateful graph with retrieval quality loop and conditional edges |
| **Mesh API** | All LLM calls routed through Mesh API (OpenAI-compatible endpoint) |
| **LangSmith** | Full trace capture for every LangGraph run |
| **Dashboard** | Read-only JSON API + Jinja2 Bootstrap 5 UI |
| **Redis Cache** | behavior (10 min), recommendation (30 min), dashboard (5 min), search (30 min) |
| **AI Guardrails** | Prompt injection detection, sanitization, output validation |
| **Feedback** | POST /recommendations/{id}/feedback → converts to behavioral event |
| **Admin Analytics** | Users, products, events, recommendations, top categories, top searches |
| **Scheduler** | APScheduler: daily recommendation refresh, hourly cache cleanup, daily event cleanup |

---

## 3. Architecture

> 📐 **Full architecture flow diagrams (ASCII + request flows):** [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

```
Browser / API Client
        │
        ▼
   FastAPI (port 8000)
        │
        ├── JWT Auth Middleware
        ├── Request ID Middleware
        ├── CORS Middleware
        │
        ├── /api/v1/auth          → AuthService
        ├── /api/v1/products      → ProductService  ──► PostgreSQL + Qdrant
        ├── /api/v1/events        → EventService    ──► PostgreSQL
        │                            └─ auto-trigger → RecommendationService
        ├── /api/v1/recommendations → RecommendationService
        │                              └─ LangGraph Workflow
        │                                   └─ Mesh API (LLM)
        ├── /api/v1/dashboard     → DashboardService ──► PostgreSQL + Redis
        ├── /api/v1/dashboard/analytics → DashboardService
        ├── /dashboard            → Jinja2 Template
        ├── /login                → Jinja2 Template
        └── /admin/*              → Jinja2 Templates

Infrastructure
  PostgreSQL 16   — persistent data (users, products, events, recommendations)
  Qdrant          — vector embeddings for semantic product search
  Redis 7         — caching layer (behavior, recommendations, dashboard, search)
  APScheduler     — background jobs (daily refresh, cache cleanup, event archival)
  LangSmith       — LangGraph trace collection and monitoring
```

---

## 4. ER Diagram

```
┌──────────────────┐        ┌──────────────────────┐
│      users       │        │       products        │
├──────────────────┤        ├──────────────────────┤
│ id (UUID PK)     │        │ id (UUID PK)          │
│ email (unique)   │        │ title                 │
│ full_name        │        │ description           │
│ hashed_password  │        │ category              │
│ role (enum)      │        │ difficulty            │
│ is_active        │        │ duration              │
│ is_verified      │        │ price                 │
│ created_at       │        │ tags (TEXT[])         │
│ updated_at       │        │ is_active             │
└────────┬─────────┘        │ created_at            │
         │                  │ updated_at            │
         │ 1:N              └──────────┬────────────┘
         ▼                             │
┌──────────────────┐                   │ soft FK
│   user_events    │◄──────────────────┘
├──────────────────┤
│ id (UUID PK)     │
│ user_id          │
│ session_id       │
│ event_type(enum) │        ┌──────────────────────┐
│ product_id       │        │   recommendations     │
│ search_query     │        ├──────────────────────┤
│ event_metadata   │        │ id (UUID PK)          │
│ created_at       │        │ user_id (soft FK)     │
└──────────────────┘        │ summary (TEXT)        │
                            │ reasoning (TEXT)      │
                            │ recommended_products  │
                            │   (JSONB)             │
                            │ confidence (float)    │
                            │ generated_at          │
                            └──────────────────────┘
```

---

## 5. LangGraph Workflow

```
START
  │
  ▼
load_profile          ← BehaviorAnalyzer → EventRepository + ProductRepository
  │
  ▼
build_query           ← Builds pipe-delimited vector search query from profile
  │
  ▼
retrieve_products ◄────────────────────────────────┐
  │                                                 │
  ▼                                                 │
evaluate_quality      ← checks count + category overlap
  │                                                 │
  ├── "good" ──────────────────────────────────────►│ skip
  │                                                 │
  └── "poor" + attempts < 2 ──► refine_query ──────┘
      "poor" + exhausted  ──────────────────────────► (force through)
  │
  ▼
generate_recommendation   ← Mesh API LLM (OpenAI-compatible)
  │                          LangSmith trace captured here
  ▼
validate_products         ← Strip hallucinated IDs, clamp confidence
  │
  ▼
store_recommendation      ← PostgreSQL commit
  │
  ▼
END
```

State flows through a `TypedDict` (`RecommendationState`). Each node receives and returns partial state dicts. `WorkflowDeps` injects all external dependencies.

---

## 6. Recommendation Pipeline

```
User Action (view / click / purchase / search)
          │
          ▼
POST /api/v1/events/batch
          │
          ▼
EventService.ingest_batch()  ──► PostgreSQL
          │
          ▼
RecommendationService.should_generate()
          │
    ┌─────┴──────────────────────────────────┐
    │  Rule 1: ≥ 20 new events               │
    │  Rule 2: repeated search query         │  OR logic
    │  Rule 3: purchase / wishlist event     │
    │  Rule 4: inactive ≥ 10 minutes         │
    └─────┬──────────────────────────────────┘
          │ any rule fires
          ▼
RecommendationService.generate()
          │
          ▼
   LangGraph Workflow (8 nodes)
          │
          ▼
   Recommendation persisted  ──► recommendations table
          │
          ▼
GET /api/v1/dashboard  ──► reads from DB + Redis cache
```

---

## 7. Folder Structure

```
SmartReco-AI/
├── app/
│   ├── api/v1/router.py          # Central route aggregator
│   ├── auth/                     # JWT, password hashing, FastAPI dependencies
│   ├── cache/
│   │   ├── redis_client.py       # Redis singleton + graceful no-op fallback
│   │   └── keys.py               # Cache key builders + TTL constants
│   ├── core/
│   │   ├── config.py             # Pydantic Settings (all env vars)
│   │   ├── exceptions.py         # Domain exception hierarchy
│   │   └── logging.py            # Structured logging setup
│   ├── dashboard/
│   │   ├── dashboard_router.py   # JSON API + Jinja2 HTML routes
│   │   ├── dashboard_schema.py   # DashboardResponse, AnalyticsResponse
│   │   └── dashboard_service.py  # Read-only aggregation (never regenerates)
│   ├── database/                 # SQLAlchemy engine, session, base models
│   ├── middleware/               # Request ID, access logging
│   ├── models/                   # SQLAlchemy ORM models
│   │   ├── user.py               # User + UserRole enum
│   │   ├── product.py            # Product (tags as PostgreSQL ARRAY)
│   │   ├── event.py              # UserEvent (JSONB metadata, pgENUM type)
│   │   └── recommendation.py     # Recommendation (JSONB product list)
│   ├── repositories/             # Data-access layer (no business logic)
│   ├── routers/                  # Thin HTTP handlers
│   ├── scheduler/
│   │   ├── scheduler.py          # APScheduler setup + registration
│   │   └── jobs.py               # daily_refresh, cache_cleanup, event_cleanup
│   ├── schemas/                  # Pydantic v2 request/response schemas
│   ├── security/
│   │   ├── prompt_guard.py       # Injection pattern detection
│   │   ├── prompt_sanitizer.py   # HTML strip, whitespace normalise, truncate
│   │   └── output_guard.py       # Confidence clamp, dedup, ID validation
│   ├── services/
│   │   ├── auth_service.py
│   │   ├── behavior_analyzer.py  # Orchestrates InterestExtractor + EngagementScorer
│   │   ├── embedding_service.py  # sentence-transformers (BAAI/bge-small-en-v1.5)
│   │   ├── engagement_scorer.py  # Engagement score + learning level
│   │   ├── event_service.py
│   │   ├── interest_extractor.py # Categories, tags, searches — pure Python
│   │   ├── product_service.py
│   │   ├── recommendation_service.py  # LangGraph orchestrator + trigger eval
│   │   ├── recommendation_trigger.py  # 4 trigger rules (DB-free)
│   │   ├── vector_service.py     # Qdrant upsert / delete / search
│   │   └── workflow/
│   │       ├── state.py          # RecommendationState TypedDict
│   │       ├── nodes.py          # 8 graph nodes + WorkflowDeps
│   │       └── graph.py          # StateGraph assembly + compile
│   ├── static/js/
│   │   ├── tracker.js            # Client-side event tracker (batch every 5s / 20 events)
│   │   ├── dashboard.js          # Dashboard data loader + renderer
│   │   └── feedback.js           # Feedback submit helper
│   └── main.py                   # FastAPI factory, middleware, lifespan
├── templates/
│   ├── base.html                 # Bootstrap 5 dark theme layout
│   ├── login.html                # Login + register
│   ├── dashboard.html            # User dashboard
│   ├── products.html             # Course catalogue grid
│   ├── product_detail.html       # Single course detail
│   └── admin/
│       ├── dashboard.html        # Admin analytics + recommendation trigger
│       └── products.html         # Admin CRUD product management
├── alembic/versions/             # 4 migration files (users→products→events→recs)
├── scripts/
│   ├── seed_admin.py             # Create first admin account
│   ├── seed_products.py          # Seed 20 AI/ML courses via Admin API
│   ├── seed_user_events.py       # Seed behavioral events + trigger recommendation
│   ├── test_mesh_langsmith.py    # Smoke-test Mesh API + LangSmith connectivity
│   └── verify_apis.py
├── tests/                        # pytest test suite
├── docker-compose.yml            # PostgreSQL + Qdrant + Redis
├── requirements.txt
└── .env.example
```

---

## 8. Installation

### Prerequisites

- Python 3.12+
- Docker Desktop (for PostgreSQL, Qdrant, Redis)
- Git

### Steps

```bash
# 1. Clone the repository
git clone https://github.com/your-org/SmartReco-AI.git
cd SmartReco-AI

# 2. Create and activate virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy environment template and fill in values
cp .env.example .env
# Edit .env — see Environment Variables section below

# 5. Start infrastructure
docker compose up -d

# 6. Run database migrations
alembic upgrade head

# 7. Create admin account
python scripts/seed_admin.py

# 8. Seed the product catalogue (20 AI/ML courses)
python scripts/seed_products.py

# 9. Start the API server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The application is now running at **http://localhost:8000**

| URL | Description |
|---|---|
| http://localhost:8000/login | User login / registration |
| http://localhost:8000/dashboard | User AI dashboard |
| http://localhost:8000/products | Course catalogue |
| http://localhost:8000/admin/dashboard | Admin analytics |
| http://localhost:8000/docs | Swagger UI (dev only) |

---

## 9. Docker Setup

`docker-compose.yml` starts three services:

```yaml
services:
  postgres:  # PostgreSQL 16  → port 5432
  qdrant:    # Qdrant         → port 6333
  redis:     # Redis 7        → port 6379
```

```bash
# Start all services
docker compose up -d

# Check status
docker compose ps

# Stop and remove
docker compose down
```

> Data persists in named Docker volumes: `postgres_data`, `qdrant_data`, `redis_data`.

---

## 10. Environment Variables

Copy `.env.example` to `.env` and fill in the required values.

| Variable | Required | Default | Description |
|---|---|---|---|
| `SECRET_KEY` | ✅ | — | JWT signing secret (min 32 chars) |
| `DATABASE_URL` | ✅ | — | PostgreSQL DSN (`postgresql://...`) |
| `LLM_API_KEY` | ✅ | — | Mesh API key (or OpenAI key) |
| `LLM_BASE_URL` | ✅ | — | `https://api.meshapi.ai/v1` |
| `LLM_MODEL` | ✅ | `minimax/m2-her` | Model for recommendation generation |
| `REDIS_URL` | ✅ | `redis://localhost:6379/0` | Redis connection string |
| `QDRANT_URL` | ✅ | `http://localhost:6333` | Qdrant server URL |
| `LANGSMITH_API_KEY` | ⚠️ | — | LangSmith tracing (optional) |
| `LANGSMITH_TRACING` | ⚠️ | `false` | Enable LangSmith trace collection |
| `LANGSMITH_PROJECT` | ⚠️ | `SmartReco-AI` | LangSmith project name |
| `EMBEDDING_MODEL` | — | `BAAI/bge-small-en-v1.5` | sentence-transformers model |
| `EMBEDDING_DIMENSION` | — | `384` | Vector dimension |
| `APP_ENV` | — | `development` | `development` / `staging` / `production` |
| `LOG_LEVEL` | — | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | — | `60` | JWT token lifetime |
| `VECTOR_MODE` | — | `qdrant` | `qdrant` (default) or `memory` (dev/CI only) |

---

## 11. Mesh API Configuration

All LLM calls are routed through **[Mesh API](https://app.meshapi.ai)** — an OpenAI-compatible gateway.

```env
LLM_API_KEY=rsk_your_key_here
LLM_BASE_URL=https://api.meshapi.ai/v1
LLM_MODEL=minimax/m2-her       # free model with 32k context
```

### Available Free Models (at time of writing)

| Model ID | Context | Notes |
|---|---|---|
| `minimax/m2-her` | 32k | Recommended — responds to system + user prompts correctly |
| `tencent/hy3` | 262k | Reasoning model — returns empty content field, not suitable |

### Verifying Connectivity

```bash
python scripts/test_mesh_langsmith.py
```

Expected output:
```
✓ PASS  Mesh endpoint reachable
✓ PASS  Chat completion succeeded
✓ PASS  LangSmith auth OK
✓ PASS  Trace submitted to LangSmith
```

---

## 12. Redis Configuration

Redis provides four cache layers:

| Cache Key Pattern | TTL | Invalidated When |
|---|---|---|
| `behavior:{user_id}` | 10 min | New events ingested |
| `recommendation:{user_id}:{hash}` | 30 min | New recommendation generated |
| `dashboard:{user_id}` | 5 min | Feedback submitted / recommendation regenerated |
| `search:{behavior_hash}:{query_hash}` | 30 min | Product catalogue updated |
| `analytics:global` | 5 min | Time-based expiry only |

```env
REDIS_URL=redis://localhost:6379/0
```

**Redis is optional** — if unavailable, the `CacheClient` disables itself with a single 1-second connection attempt at startup. All operations become transparent no-ops. The application continues running without caching.

Start Redis via Docker:
```bash
docker compose up -d redis
```

---

## 13. Qdrant Configuration

Qdrant stores 384-dimensional product embeddings generated by `BAAI/bge-small-en-v1.5`.

```env
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=          # leave blank for local; set for Qdrant Cloud
QDRANT_COLLECTION=products
VECTOR_MODE=qdrant       # or "memory" for dev without Docker
```

**Dual-write pattern**: every `POST /admin/products` writes to PostgreSQL first, then upserts to Qdrant. If Qdrant fails, the SQL transaction is rolled back — both stores stay in sync.

---

## 14. Authentication

SmartReco AI uses **JWT Bearer tokens** with two roles:

| Role | Access |
|---|---|
| `user` | Own events, own profile, own dashboard, own recommendations |
| `admin` | Everything + product CRUD, any user's recommendations, analytics |

### Register

```bash
POST /api/v1/auth/register
{
  "email": "you@example.com",
  "full_name": "Your Name",
  "password": "SecurePass1"
}
```

### Login

```bash
POST /api/v1/auth/login
{
  "email": "you@example.com",
  "password": "SecurePass1"
}
# Returns: { "access_token": "eyJ...", "token_type": "bearer" }
```

Use the token in subsequent requests:
```
Authorization: Bearer eyJ...
```

### Default Accounts

```
Admin:  admin@smartreco.ai  /  Admin1234!
```

---

## 15. Dashboard

The dashboard is **read-only** — it never regenerates recommendations.

### JSON API

```
GET /api/v1/dashboard
Authorization: Bearer <token>
```

Returns: `DashboardResponse` containing:
- User profile (name, email, role, member since)
- Behavior profile (categories, tags, searches, engagement score, learning level)
- Latest recommendation (summary, reasoning, products, confidence score, AI model used)
- Evidence used (categories and searches that drove the recommendation)
- Recent activity timeline (last 10 events with timestamps)
- Cache metadata (hit/miss, cache key)

### Web UI

| URL | Description |
|---|---|
| `/login` | Login + account registration |
| `/dashboard` | User AI dashboard (requires login) |
| `/products` | Course catalogue with search |
| `/products/{id}` | Course detail + enroll / wishlist |
| `/admin/dashboard` | Analytics + recommendation trigger (admin only) |
| `/admin/products` | CRUD product management (admin only) |

### Triggering Recommendations

Recommendations are triggered **automatically** when behavioral rules fire after event ingest. They can also be triggered manually:

```bash
# Via Admin UI at /admin/dashboard — paste a User UUID and click "Run AI Workflow"

# Via API (admin token required)
POST /api/v1/recommendations/generate
{
  "user_id": "510bfe26-0412-4225-aaf5-57ee10a9a526",
  "max_products": 20
}
```

---

## 16. Caching Strategy

```
Request for dashboard
        │
        ▼
CacheClient.get("dashboard:{user_id}")
        │
   HIT ─┤─ MISS
        │       │
        │       ▼
        │   BehaviorAnalyzer.build_profile()
        │       │
        │   CacheClient.get("behavior:{user_id}")  ──HIT──► return cached
        │       │ MISS
        │       ▼
        │   EventRepository + ProductRepository
        │       │
        │   CacheClient.set("behavior:{user_id}", TTL=600)
        │       │
        │   RecommendationRepository.get_latest()   (DB read, no LLM)
        │       │
        │   Assemble DashboardResponse
        │       │
        │   CacheClient.set("dashboard:{user_id}", TTL=300)
        │       │
        ◄───────┘
        │
        ▼
Return DashboardResponse  { cache_hit: true/false }
```

Cache is invalidated on:
- New recommendation generated → invalidates `dashboard:*` and `recommendation:*`
- Feedback submitted → invalidates `dashboard:{user_id}` and `behavior:{user_id}`
- Product updated (admin) → invalidates `search:*`

---

## 17. AI Guardrails

Three guardrail layers protect the LLM pipeline and are **wired directly into the LangGraph workflow nodes**.

### Where each guardrail runs

```
build_query node
    └─ PromptSanitizer.sanitize(query)
           Strip HTML, remove control chars, normalise whitespace, truncate to 500 chars
           Applied before the query reaches vector search or any prompt

generate_recommendation node
    └─ PromptGuard.check(full_prompt)
           Scan assembled prompt for 10 injection patterns
           If detected → return {"error": "prompt_blocked"} → workflow stores fallback
           LLM is never called with a poisoned prompt

validate_products node
    └─ OutputGuard.validate(llm_output, valid_product_ids)
           Strip hallucinated product IDs not in the candidate set
           Remove duplicate product IDs
           Clamp confidence to [0.0, 1.0]
           Enforce maximum 5 products
           If all IDs invalid → fallback to top-N candidates, confidence ≤ 0.30
```

### Prompt Guard (`app/security/prompt_guard.py`)
Detects and rejects 10 prompt injection patterns before they reach the LLM:
- "ignore previous/all instructions"
- "reveal system prompt / API key / secret"
- "jailbreak", "developer mode", "DAN"
- "bypass filter / restriction / safety"
- "forget all instructions", "disregard instructions"
- "act as unrestricted", "you are now a different AI"

### Prompt Sanitizer (`app/security/prompt_sanitizer.py`)
Cleans user-derived text before it enters any prompt:
- Strips HTML tags and unescapes HTML entities
- Removes invisible control characters (non-printable ASCII)
- Normalizes whitespace and collapses consecutive blank lines
- Truncates to configurable max length (query: 500 chars, general: 2000 chars)

### Output Guard (`app/security/output_guard.py`)
Validates LLM recommendation output before persistence:
- Confidence clamped to [0.0, 1.0]
- Duplicate product IDs removed
- Hallucinated product IDs (not in the candidate set) stripped
- Maximum recommendation count enforced (5)

---

## 18. Scheduler

APScheduler runs three background jobs, registered during FastAPI startup:

| Job | Schedule | Description |
|---|---|---|
| `daily_recommendation_refresh` | **08:00 UTC** daily | Generate recommendations for active users who haven't had one in 23 hours; invalidates dashboard cache per user |
| `cache_cleanup` | **Every hour** | Log Redis memory stats and key count (TTL expiry handled natively by Redis) |
| `event_cleanup` | **02:00 UTC** daily | Delete `UserEvent` records older than 90 days to keep the table lean |

The scheduler starts automatically with the application and stops gracefully on shutdown.

### Admin Endpoints

```bash
# Run a job immediately (synchronous)
POST /api/v1/admin/scheduler/run
Authorization: Bearer <admin-token>
{ "job_id": "daily_reco_refresh" }   # or cache_cleanup | event_cleanup

# Get scheduler status and per-job metadata
GET /api/v1/admin/scheduler/status
Authorization: Bearer <admin-token>
```

Status response includes per job:
- `next_run_time` — next scheduled execution (ISO 8601 UTC)
- `last_run` — last execution timestamp
- `last_status` — `success` / `error` / `never` / `skipped_no_redis`
- `last_duration_s` — wall-clock time in seconds
- `recommendations_generated` — count (daily job only)
- `events_archived` — count (cleanup job only)

---

## 19. LangSmith Tracing

Every LangGraph recommendation run is traced in LangSmith automatically.

### Setup

```env
LANGSMITH_API_KEY=lsv2_pt_your_key_here
LANGSMITH_TRACING=true
LANGSMITH_PROJECT=SmartReco-AI
```

### What Gets Traced

Each trace captures the full LangGraph execution including:
- `load_profile` → behavior profile dict
- `build_query` → retrieval query string
- `retrieve_products` → candidate count, fallback flag
- `evaluate_quality` → quality decision (good / poor)
- `refine_query` → refined query (if triggered)
- `generate_recommendation` → full LLM prompt + raw response
- `validate_products` → valid product count, confidence
- `store_recommendation` → persisted recommendation ID

**View traces at:** https://smith.langchain.com/projects/SmartReco-AI

---

## 20. API Endpoints

### Authentication

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/v1/auth/register` | — | Create user account |
| `POST` | `/api/v1/auth/login` | — | Exchange credentials for JWT |
| `GET` | `/api/v1/auth/me` | User | Current user profile |

### Products

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/v1/products` | — | Paginated active product list |
| `GET` | `/api/v1/products/{id}` | — | Single product by UUID |
| `POST` | `/api/v1/admin/products` | Admin | Create product + embed + index |
| `PUT` | `/api/v1/admin/products/{id}` | Admin | Replace product + re-embed |
| `DELETE` | `/api/v1/admin/products/{id}` | Admin | Delete from SQL + Qdrant |

### Events

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/v1/events/batch` | User | Ingest 1–500 events (auto-triggers recommendation) |
| `GET` | `/api/v1/events/me` | User | Paginated event history |

### Recommendations

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/v1/recommendations/generate` | Admin | Run LangGraph workflow for a user |
| `GET` | `/api/v1/recommendations/me` | User | Latest cached recommendation |
| `POST` | `/api/v1/recommendations/{id}/feedback` | User | Submit liked/disliked feedback |

### Dashboard

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/v1/dashboard` | User | Full dashboard (read-only, cache-first) |
| `GET` | `/api/v1/dashboard/analytics` | Admin | Platform-wide analytics |

### Scheduler

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/api/v1/admin/scheduler/run` | Admin | Run a job immediately (sync) |
| `GET` | `/api/v1/admin/scheduler/status` | Admin | Scheduler running state + per-job stats |

### Users & Health

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/v1/users/me/profile` | User | Computed behavioral profile |
| `GET` | `/health` | — | Liveness probe |
| `GET` | `/health/ready` | — | Readiness probe (checks DB) |

---

## 21. Development Steps

This section documents every step taken to build SmartReco AI from scratch.

### Step 1 — Project Scaffolding
- Initialised FastAPI project with clean architecture: `app/{api,auth,core,database,middleware,models,repositories,routers,schemas,services}`
- Configured Pydantic Settings (`app/core/config.py`) loading from `.env`
- Set up structured logging (`app/core/logging.py`)
- Added domain exception hierarchy (`app/core/exceptions.py`)
- Added `RequestIDMiddleware` and `AccessLogMiddleware`
- Created `docker-compose.yml` with PostgreSQL + Qdrant

### Step 2 — Database & Migrations
- Configured SQLAlchemy 2.0 with declarative base (`app/database/base.py`)
- Created `BaseModel` mixin with UUID PK + `created_at` / `updated_at` timestamps
- Set up Alembic with auto-generate support (`alembic/env.py`)
- Migration 1: `users` table — email, hashed_password, role (pgENUM), is_active
- Migration 2: `products` table — title, category, difficulty, tags (PostgreSQL ARRAY), price
- Migration 3: `user_events` table — event_type (pgENUM), product_id, search_query, event_metadata (JSONB)
- Migration 4: `recommendations` table — summary, reasoning, recommended_products (JSONB), confidence

### Step 3 — Authentication
- JWT access tokens using `python-jose` (`app/auth/jwt.py`)
- bcrypt password hashing (`app/auth/password.py`)
- `get_current_user` and `get_current_admin` FastAPI dependencies (`app/auth/dependencies.py`)
- `POST /auth/register` and `POST /auth/login` endpoints

### Step 4 — Product CRUD + Vector Store
- `ProductService` with dual-write: PostgreSQL INSERT → Qdrant upsert
- If Qdrant write fails, SQL transaction rolls back (atomic consistency)
- `EmbeddingService` with `BAAI/bge-small-en-v1.5` (384-dim, sentence-transformers)
- `VectorService` with `ensure_collection()`, `upsert()`, `delete()`, `search()`
- Admin-only routes: `POST/PUT/DELETE /admin/products`
- Fixed `metadata` column name clash with SQLAlchemy reserved attribute → renamed to `event_metadata`

### Step 5 — Event Tracking
- `UserEvent` model with 8 event types: VIEW, CLICK, SEARCH, PURCHASE, WISHLIST, RATING, SHARE, IMPRESSION
- `EventRepository.insert_batch()` — single SQL INSERT for up to 500 events
- `POST /events/batch` — validates, persists, returns accepted count + IDs
- Cross-field validation in `EventRequest`: product_id required for product events, search_query for SEARCH

### Step 6 — Behavior Intelligence Layer
- `InterestExtractor` — primary_categories, favorite_tags, top_searches, search_frequency, repeated_searches (pure Python, DB-free)
- `EngagementScorer` — engagement_score [0.0, 1.0], learning_level, top_interests
- `BehaviorAnalyzer` — orchestrates both; single DB session; builds `BehaviorProfile` schema
- `GET /users/me/profile` endpoint

### Step 7 — Recommendation Trigger
- `RecommendationTrigger` — 4 rules (new events ≥ 20, repeated search, purchase/wishlist, inactivity ≥ 10 min)
- Rules evaluated independently (OR-logic); all results returned in `rules_evaluated` dict
- Integrated into `POST /events/batch` — fires after successful ingest

### Step 8 — LangGraph Recommendation Workflow
- `RecommendationState` TypedDict — JSON-safe state bag for graph
- 8 nodes in `workflow/nodes.py`: `load_profile → build_query → retrieve_products → evaluate_quality → refine_query → generate_recommendation → validate_products → store_recommendation`
- `WorkflowDeps` dataclass — all external dependencies injected at graph build time
- Conditional edges after `evaluate_quality`: routes to `refine_query` (max 2 attempts) or falls through to `generate_recommendation`
- `workflow/graph.py` — assembles and compiles the `StateGraph`

### Step 9 — Mesh API + LangSmith
- All LLM calls use `OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)`
- `LLM_BASE_URL=https://api.meshapi.ai/v1` — all inference routes through Mesh
- LangSmith env vars wired at startup when `LANGSMITH_TRACING=true`
- Discovered free Mesh models: `minimax/m2-her` (32k, works) and `tencent/hy3` (262k, reasoning-only — empty content)
- Smoke test script: `scripts/test_mesh_langsmith.py` — 3/3 checks passing

### Step 10 — Dashboard, Caching, Guardrails, Scheduler, UI
- `DashboardService` — read-only aggregation, cache-first, never regenerates
- `CacheClient` — Redis wrapper with graceful no-op fallback (1s connect timeout, cached `None` on failure)
- Cache keys: `behavior:{user_id}`, `recommendation:{user_id}:{hash}`, `dashboard:{user_id}`
- `POST /recommendations/{id}/feedback` — converts liked/disliked to behavioral event
- `GET /dashboard/analytics` — admin-only: users, products, events, recs, top categories, top searches
- `PromptGuard`, `PromptSanitizer`, `OutputGuard` — lightweight guardrail pipeline
- APScheduler jobs: `daily_reco_refresh` (08:00 UTC), `cache_cleanup` (hourly), `event_cleanup` (02:00 UTC)
- Admin scheduler endpoints: `POST /admin/scheduler/run`, `GET /admin/scheduler/status`
- Job stats registry (`_job_stats`) tracks last run, status, duration, and generated counts per job
- Templates: `base.html`, `login.html`, `dashboard.html`, `products.html`, `product_detail.html`, `admin/dashboard.html`, `admin/products.html`
- JS: `tracker.js` (batch event sender), `dashboard.js` (data renderer), `feedback.js`
- Fixed Starlette 1.4.1 `TemplateResponse` signature: `(request, name, context)` not `(name, {"request": req})`
- Fixed missing DB migrations: `alembic upgrade head` applied `user_events` + `recommendations` tables
- Fixed Redis blocking: `CacheClient` now uses `lru_cache` to avoid repeated timeouts
- Seeded 20 AI/ML courses via `scripts/seed_products.py`
- Seeded user behavioral events + triggered first recommendation via `scripts/seed_user_events.py`

### Step 11 — Bug Fixes & Polish
- Fixed login page flickering: async token validation before redirect, `location.replace()` to prevent history loop, excluded `tracker.js` from login page
- Fixed `EventResponse` schema: added `validation_alias="event_metadata"` to map renamed ORM attribute
- Fixed scheduler card hidden inside conditional `#analytics-content` div — moved outside as always-visible section
- Added admin user picker dropdown (`GET /api/v1/admin/users`) — no more manual UUID typing
- Added `EmailService` with SMTP-based recommendation digest and welcome emails (graceful no-op if not configured)
- Added `scripts/preview_email.py` to generate and open email HTML preview locally
- Added `scripts/final_test.py` — 66-check comprehensive end-to-end test suite
- All 66/66 checks passing

---

## Docs

| Document | Description |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | Full system architecture diagrams, LangGraph workflow, data flow, cache architecture |

---

## Screenshots

> See `docs/screenshots/` for actual screenshots taken during development.

| File | Description |
|---|---|
| `docs/screenshots/HLD.png` | Architecture |
| `docs/screenshots/dashboard.png` | User AI dashboard with recommendation story |
| `docs/screenshots/admin.png` | User AI dashboard with recommendation story |
| `docs/screenshots/products.png` | Course catalogue grid |
| `docs/screenshots/mesh_api.png` | Mesh API smoke test output |
| `docs/screenshots/ls_observability.png` | LangSmith trace dashboard |
| `docs/screenshots/docker.png` | Docker containers running |
| `docs/screenshots/Swagger UI.png` | Full Swagger UI with all 23 endpoints |

---

## License

MIT © 2026 SmartReco AI

---

*Built with ❤️ using FastAPI · LangGraph · Mesh API · PostgreSQL · Qdrant · Redis · APScheduler · LangSmith*
