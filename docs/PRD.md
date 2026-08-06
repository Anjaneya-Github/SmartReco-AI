# SmartReco AI — Product Requirements Document (PRD)

**Version:** 1.0.0  
**Date:** August 2026  
**Status:** Implemented ✅

---

## 1. Product Overview

SmartReco AI is an **AI-powered personalised learning recommendation platform** built for the Advanced AI/ML Hackathon. It tracks every user interaction with a course catalogue, builds a real-time behavioural profile, and uses a **LangGraph multi-agent workflow** calling a **Mesh API LLM** to generate contextualised course recommendations.

The platform is designed to never call the AI on every action — recommendations are triggered intelligently based on behavioural signals, cached in Redis, and served from a Bootstrap 5 dashboard.

---

## 2. Goals

| Goal | Metric |
|---|---|
| Personalised recommendations | Confidence score ≥ 0.70 for users with ≥ 10 interactions |
| Low dashboard latency | < 100ms for cached responses |
| Trigger accuracy | Recommendation fires only when meaningful signal accumulates |
| Zero hallucination | No invented product IDs in recommendations (validated by OutputGuard) |
| Observability | Every LLM call traced in LangSmith |

---

## 3. User Roles

### 3.1 User (standard)
| Capability | Endpoint |
|---|---|
| Register account | `POST /api/v1/auth/register` |
| Login | `POST /api/v1/auth/login` |
| View own profile | `GET /api/v1/auth/me` |
| Browse course catalogue | `GET /api/v1/products` |
| View course detail | `GET /api/v1/products/{id}` |
| Track interactions | `POST /api/v1/events/batch` |
| View event history | `GET /api/v1/events/me` |
| View behavioural profile | `GET /api/v1/users/me/profile` |
| View AI dashboard | `GET /api/v1/dashboard` |
| View latest recommendation | `GET /api/v1/recommendations/me` |
| Submit feedback | `POST /api/v1/recommendations/{id}/feedback` |

### 3.2 Admin
Everything a User can do, plus:

| Capability | Endpoint |
|---|---|
| Create product + embed + index | `POST /api/v1/admin/products` |
| Update product + re-embed | `PUT /api/v1/admin/products/{id}` |
| Delete product | `DELETE /api/v1/admin/products/{id}` |
| List all users | `GET /api/v1/admin/users` |
| Generate recommendation for any user | `POST /api/v1/recommendations/generate` |
| View platform analytics | `GET /api/v1/dashboard/analytics` |
| Trigger scheduler job manually | `POST /api/v1/admin/scheduler/run` |
| View scheduler status | `GET /api/v1/admin/scheduler/status` |

---

## 4. Functional Requirements

### 4.1 Authentication
- **FR-AUTH-1:** Users register with email + password (min 8 chars, 1 uppercase, 1 digit).
- **FR-AUTH-2:** Login returns a signed JWT (HS256, configurable expiry).
- **FR-AUTH-3:** All protected endpoints validate the JWT on every request.
- **FR-AUTH-4:** Admin role is enforced at the dependency level — not just route-level checks.
- **FR-AUTH-5:** Inactive accounts are rejected at auth time, not just at registration.

### 4.2 Product Management
- **FR-PROD-1:** Admin creates a product → PostgreSQL INSERT + Qdrant vector upsert (atomic: if either fails, both roll back).
- **FR-PROD-2:** Product update triggers re-embedding and Qdrant re-index.
- **FR-PROD-3:** Product deletion removes both the SQL row and the Qdrant vector point.
- **FR-PROD-4:** Public users can list and view products without authentication.
- **FR-PROD-5:** Products have: title, description, category, difficulty (beginner/intermediate/advanced), duration, price (null = free), tags (array), is_active.

### 4.3 Behavioural Event Tracking
- **FR-EVT-1:** Users submit events in batches (1–500 per request).
- **FR-EVT-2:** Supported event types: VIEW, CLICK, SEARCH, PURCHASE, WISHLIST, RATING, SHARE, IMPRESSION.
- **FR-EVT-3:** Events are validated — product-related types require `product_id`; SEARCH requires `search_query`.
- **FR-EVT-4:** Events are persisted atomically (all-or-nothing per batch).
- **FR-EVT-5:** `user_id` is always taken from the JWT — clients cannot inject it.
- **FR-EVT-6:** The client-side `tracker.js` batches events every 5 seconds or 20 events and sends to `POST /events/batch` in the background without blocking the UI.

### 4.4 Behaviour Intelligence
- **FR-BEH-1:** `BehaviorAnalyzer` builds a `BehaviorProfile` from the user's most recent 200 events.
- **FR-BEH-2:** `InterestExtractor` computes primary_categories, favorite_tags, top_searches, search_frequency — pure Python, no DB access.
- **FR-BEH-3:** `EngagementScorer` computes engagement_score [0.0, 1.0] and learning_level — pure Python.
- **FR-BEH-4:** Profile is computed fresh on demand; cached in Redis for 10 minutes.

### 4.5 Recommendation Trigger
- **FR-TRIG-1:** After every event batch ingest, the system evaluates 4 trigger rules (OR logic):
  1. ≥ 20 new events since last recommendation
  2. Repeated search query in the window
  3. Any PURCHASE or WISHLIST event present
  4. User inactive for ≥ 10 minutes
- **FR-TRIG-2:** If any rule fires, `RecommendationService.generate()` is called.
- **FR-TRIG-3:** If no rule fires, no LLM call is made — the existing recommendation is served.

### 4.6 Recommendation Engine (LangGraph Workflow)
- **FR-REC-1:** The workflow has 8 nodes: `load_profile → build_query → retrieve_products → evaluate_quality → refine_query (conditional) → generate_recommendation → validate_products → store_recommendation`.
- **FR-REC-2:** Vector similarity search uses Qdrant; falls back to DB listing if Qdrant is unavailable.
- **FR-REC-3:** Retrieval quality is evaluated (candidate count + category overlap). Poor quality triggers up to 2 refinement attempts.
- **FR-REC-4:** The LLM call routes through Mesh API (`OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)`).
- **FR-REC-5:** `OutputGuard` validates the LLM response — strips hallucinated product IDs, deduplicates, clamps confidence.
- **FR-REC-6:** Recommendations are persisted as immutable rows. Re-generation creates a new row; `GET /me` returns the latest.
- **FR-REC-7:** Every workflow run is traced in LangSmith automatically.

### 4.7 AI Guardrails
- **FR-GUARD-1:** `PromptGuard` detects and rejects 10 injection patterns before any LLM call.
- **FR-GUARD-2:** `PromptSanitizer` strips HTML, removes control characters, normalises whitespace, truncates to 2000 chars.
- **FR-GUARD-3:** `OutputGuard` validates: confidence in [0.0, 1.0], no duplicate IDs, all IDs exist in the candidate set, max 5 products.

### 4.8 Recommendation Dashboard
- **FR-DASH-1:** `GET /api/v1/dashboard` is read-only — it never triggers the LLM.
- **FR-DASH-2:** Response includes: user info, behavior profile, latest recommendation, confidence label, evidence used, recent activity timeline, cache status.
- **FR-DASH-3:** Dashboard is cache-first (Redis TTL 5 min); falls back to DB on cache miss.
- **FR-DASH-4:** The Jinja2 dashboard UI renders all data client-side via JS from the JSON API.

### 4.9 Admin Analytics
- **FR-ANAL-1:** `GET /api/v1/dashboard/analytics` returns: total users, products, events, recommendations, top categories, top searches, most viewed products.
- **FR-ANAL-2:** Analytics are cached in Redis for 5 minutes.
- **FR-ANAL-3:** Analytics are restricted to admin role.

### 4.10 Scheduler
- **FR-SCHED-1:** APScheduler runs 3 jobs automatically at startup:
  - `daily_reco_refresh` — 08:00 UTC, generates recommendations for active users without recent ones
  - `cache_cleanup` — hourly, logs Redis memory stats
  - `event_cleanup` — 02:00 UTC, deletes events older than 90 days
- **FR-SCHED-2:** Admin can trigger any job manually via `POST /api/v1/admin/scheduler/run`.
- **FR-SCHED-3:** `GET /api/v1/admin/scheduler/status` returns: running state, 3 jobs with next_run_time, last_run, last_status, duration, and job-specific counts.

### 4.11 Email Notifications
- **FR-EMAIL-1:** After each successful recommendation generation, an HTML email digest is sent to the user.
- **FR-EMAIL-2:** Email includes: personalised story, confidence badge, 5 recommended courses, "View Dashboard" CTA.
- **FR-EMAIL-3:** Email service is a graceful no-op when SMTP is not configured — never crashes the recommendation workflow.

---

## 5. Non-Functional Requirements

| Requirement | Specification |
|---|---|
| **Performance** | Cached dashboard responses < 100ms; LLM calls 2–10s (async trigger, not blocking) |
| **Availability** | Graceful degradation if Redis/Qdrant/LLM unavailable — core CRUD always works |
| **Security** | JWT, bcrypt, RBAC, prompt injection detection, no secrets in codebase |
| **Observability** | Structured logging (all requests), LangSmith tracing (all LLM calls), scheduler job stats |
| **Scalability** | Stateless FastAPI + Redis cache enables horizontal scaling; background jobs are thread-safe |
| **Maintainability** | Clean Architecture — routers thin, services own logic, repositories own SQL, nodes own workflow steps |
| **Testability** | Pure Python behavior components, WorkflowDeps injection, 66-check final test suite |

---

## 6. Technical Stack

| Layer | Technology |
|---|---|
| API Framework | FastAPI 0.115 |
| Language | Python 3.12 |
| ORM | SQLAlchemy 2.0 |
| Database | PostgreSQL 16 |
| Migrations | Alembic |
| Vector Store | Qdrant |
| Embeddings | sentence-transformers (`BAAI/bge-small-en-v1.5`, 384-dim) |
| Cache | Redis 7 |
| AI Workflow | LangGraph 0.2 |
| LLM Provider | Mesh API (`minimax/m2-her`, OpenAI-compatible) |
| Observability | LangSmith |
| Scheduler | APScheduler 3.x |
| Frontend | Jinja2 + Bootstrap 5 + Vanilla JS |
| Auth | python-jose (JWT) + passlib (bcrypt) |
| Validation | Pydantic v2 |

---

## 7. Data Model Summary

| Table | Rows (at demo) | Purpose |
|---|---|---|
| `users` | 2 (1 admin, 1 user) | Authentication + RBAC |
| `products` | 20 AI/ML courses | Content catalogue |
| `user_events` | ~30+ | Behavioral signal stream |
| `recommendations` | ~10 | Persisted AI results |

---

## 8. Acceptance Criteria

All acceptance criteria verified by `scripts/final_test.py` — **66/66 checks passing**.

| ID | Criteria | Status |
|---|---|---|
| AC-1 | Root `/` returns app name and version | ✅ |
| AC-2 | `/health/ready` returns `database: ok` | ✅ |
| AC-3 | Register endpoint validates password rules (422 on invalid) | ✅ |
| AC-4 | Login with wrong credentials returns 401 | ✅ |
| AC-5 | Admin login succeeds and returns JWT | ✅ |
| AC-6 | Product list returns 20 seeded courses | ✅ |
| AC-7 | Event batch ingest returns 202 | ✅ |
| AC-8 | Behavior profile returns engagement score and learning level | ✅ |
| AC-9 | Dashboard returns full response with all required fields | ✅ |
| AC-10 | Dashboard includes has_recommendation=true after generation | ✅ |
| AC-11 | Recommendation confidence > 0 | ✅ |
| AC-12 | Feedback endpoint returns 202 | ✅ |
| AC-13 | Analytics endpoint returns users, products, events counts | ✅ |
| AC-14 | Analytics is forbidden for non-admin (403) | ✅ |
| AC-15 | Scheduler status returns running=true and 3 jobs | ✅ |
| AC-16 | Run cache_cleanup returns 202 and triggered status | ✅ |
| AC-17 | All 5 HTML pages return 200 | ✅ |
| AC-18 | All 3 JS files served correctly | ✅ |
| AC-19 | PromptGuard blocks injection patterns | ✅ |
| AC-20 | OutputGuard strips hallucinated product IDs | ✅ |

---

## 9. Out of Scope (v1.0)

- Real-time WebSocket push notifications
- Collaborative filtering (user-user / item-item)
- A/B testing for recommendation strategies
- Course progress tracking (enroll / complete events)
- Multi-tenant support
- Payment integration
- Mobile app

See [`docs/feature_enhancements.md`](feature_enhancements.md) for the full roadmap.
