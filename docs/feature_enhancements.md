# SmartReco AI — Feature Enhancements

> What was built, what was added during development, and what remains on the roadmap.

---

## Status Legend

| Symbol | Meaning |
|---|---|
| ✅ | Implemented and tested |
| 🔶 | Partially implemented |
| 🔲 | Planned / future enhancement |

---

## COMPLETED FEATURES (Built During Hackathon)

### ✅ Core Platform
| Feature | Notes |
|---|---|
| FastAPI REST API | 23 endpoints, full OpenAPI spec |
| JWT Authentication + RBAC | user / admin roles, bcrypt, token refresh |
| PostgreSQL via SQLAlchemy 2.0 | 4 tables, Alembic migrations |
| Qdrant Vector Store | 384-dim embeddings, HNSW, dual-write pattern |
| Redis Caching | behavior (10m), recommendation (30m), dashboard (5m); graceful no-op if unavailable |
| Product CRUD | admin-only, PostgreSQL + Qdrant atomic dual-write |
| Behavioral Event Tracking | 8 event types, batch ingest up to 500, JSONB metadata |
| Behavior Intelligence Layer | InterestExtractor, EngagementScorer, BehaviorAnalyzer — pure Python, DB-free |

### ✅ AI Recommendation Engine
| Feature | Notes |
|---|---|
| LangGraph Workflow | 8 nodes, retrieval quality loop with conditional edges, up to 2 refinement attempts |
| Mesh API Integration | `minimax/m2-her` free model, 32k context, OpenAI-compatible via `base_url` |
| LangSmith Tracing | Auto-captured via `LANGCHAIN_TRACING_V2=true` on every graph run |
| Recommendation Trigger | 4 rules: ≥20 events, repeated search, purchase/wishlist, 10-min inactivity |
| AI Guardrails | PromptGuard (injection detection), PromptSanitizer (HTML strip, truncate), OutputGuard (dedup, ID validation, confidence clamp) |
| Recommendation Persistence | Immutable rows in PostgreSQL, dashboard reads latest |

### ✅ Dashboard & UI
| Feature | Notes |
|---|---|
| User Dashboard API | `GET /api/v1/dashboard` — read-only, cache-first, never regenerates |
| Admin Analytics API | `GET /api/v1/dashboard/analytics` — users, products, events, recommendations, top categories/searches |
| Bootstrap 5 Jinja2 UI | login, dashboard, products, product_detail, admin/dashboard, admin/products |
| JavaScript Event Tracker | `tracker.js` — batches events every 5s or 20 events, fire-and-forget |
| Feedback System | `POST /recommendations/{id}/feedback` — liked/disliked → converted to behavioral event |
| Admin User Picker | Dropdown in admin dashboard — select user without typing UUID |

### ✅ Scheduler (APScheduler)
| Job | Schedule | What it does |
|---|---|---|
| `daily_reco_refresh` | 08:00 UTC daily | Generate recommendations for active users who haven't had one in 23h; invalidate dashboard cache |
| `cache_cleanup` | Every hour | Log Redis memory stats and key count |
| `event_cleanup` | 02:00 UTC daily | Delete `UserEvent` records older than 90 days |

Admin endpoints:
- `POST /api/v1/admin/scheduler/run` — trigger any job immediately
- `GET /api/v1/admin/scheduler/status` — scheduler state + per-job stats (next run, last run, duration, counts)

### ✅ Email Notifications
| Feature | Notes |
|---|---|
| `EmailService` | `app/services/email_service.py` — SMTP-based, HTML + plain text |
| Recommendation digest email | Sent after every successful recommendation generation |
| Welcome email | Sent after registration |
| Email preview | `scripts/preview_email.py` — renders HTML locally in browser |
| Graceful no-op | If SMTP not configured, all email calls silently skip |

**To enable:** Set `EMAIL_ENABLED=true` + SMTP credentials in `.env`.

### ✅ Developer Tools
| Tool | Purpose |
|---|---|
| `scripts/seed_admin.py` | Create first admin account |
| `scripts/seed_products.py` | Seed 20 AI/ML courses via Admin API |
| `scripts/seed_user_events.py` | Seed behavioral events + trigger first recommendation |
| `scripts/test_mesh_langsmith.py` | Smoke-test Mesh API + LangSmith connectivity |
| `scripts/test_scheduler_ui.py` | Verify scheduler dashboard section and all 3 jobs |
| `scripts/final_test.py` | Comprehensive 66-check end-to-end test suite |
| `scripts/preview_email.py` | Generate + open email preview in browser |

---

## PARTIALLY IMPLEMENTED

### 🔶 Recommendation Quality Gate
**What exists:** Every trigger generates a new recommendation row regardless of quality.

**Problem:** Auto-triggered runs sometimes produce empty content (model returns blank), creating low-confidence rows that overwrite good ones.

**What's needed:** Only store a new recommendation if `confidence >= threshold` OR `force=True`.

```python
# In RecommendationService.generate()
if result.confidence < 0.4 and not force:
    logger.info("Low confidence result not stored. confidence=%.2f", result.confidence)
    return existing_latest  # return the previous good result
```

### 🔶 LangSmith Metadata Enrichment
**What exists:** Basic auto-tracing of every LangGraph run via `LANGCHAIN_TRACING_V2=true`.

**What's needed:** Add rich metadata per trace:
```python
@traceable(metadata={
    "user_id": str(user_id),
    "trigger_rule": trigger_reason,
    "behavior_score": profile.engagement_score,
    "candidate_count": len(candidates),
    "retrieval_attempts": attempts,
    "workflow_version": "v2",
    "cache_hit": was_cached,
})
```

---

## ROADMAP (Future Enhancements)

### Priority 1 — Production Readiness

#### 🔲 Async Background Task Queue
Move recommendation generation off the HTTP request thread.
```
POST /events/batch → persist → evaluate trigger → push user_id to queue → return 202
Worker → RecommendationService.generate() → optionally push WebSocket notification
```
**Tech:** ARQ (asyncio), Celery + Redis, or FastAPI `BackgroundTasks`.
**Impact:** API latency drops from 2–10s to <100ms.

#### 🔲 WebSocket / Server-Sent Events
Push recommendation-ready notification to open browser tabs.

#### 🔲 Rate Limiting
Per-user sliding window limits on event ingest and recommendation generation.

#### 🔲 PATCH Product Endpoint
Partial product updates — currently only full PUT replacement.

---

### Priority 2 — Recommendation Quality

#### 🔲 Collaborative Filtering
User-user and item-item similarity for "users like you also studied" section.

#### 🔲 A/B Testing for Recommendation Strategies
Run multiple strategies (content-based, collaborative, trending) and compare CTR.

#### 🔲 Feedback Loop Integration
Use liked/disliked signals to re-weight categories and tags in future retrieval queries.

#### 🔲 Trending Recommendations
Implement `GET /recommendations/trending` based on event velocity in last 24h.

#### 🔲 Confidence Calibration
Track recommendation → click → purchase conversion and calibrate LLM confidence scores against actual outcomes.

---

### Priority 3 — User Experience

#### 🔲 User Onboarding Questionnaire
3-step onboarding after registration to bootstrap the behavior profile before organic activity.

#### 🔲 Semantic Search
`GET /api/v1/products/search?q=` — embed query and return similar products from Qdrant rather than keyword filtering.

#### 🔲 Course Progress Tracking
Add `ENROLL` and `COMPLETE` event types. Surface "continue learning" section on dashboard.

#### 🔲 Push Notifications (Web Push API)
Browser notifications when a new recommendation is ready — works even when the tab is closed.

---

### Priority 4 — Observability

#### 🔲 Prometheus Metrics
Expose `/metrics` with recommendation counts, confidence histograms, cache hit rates, trigger fire counts.

#### 🔲 Enhanced Health Check
`/health/ready` should check Redis, Qdrant, and LLM API reachability — not just PostgreSQL.

#### 🔲 Event Archival Pipeline
Actual archive-and-delete for events older than 90 days (currently only logged).

---

### Priority 5 — Scale

#### 🔲 Multi-Language Support
Multilingual embedding model, locale detection, localised recommendation stories.

#### 🔲 LLM Fine-Tuning
Fine-tune `Llama-3-8B` or `Mistral-7B` on validated recommendation pairs for lower latency + higher quality than zero-shot prompting.

#### 🔲 Multi-Tenant Support
Add `tenant_id` to isolate product catalogues, recommendations, and analytics per organisation.

---

## Summary Table

| Feature | Status | Priority |
|---|---|---|
| Async background tasks | 🔲 | 1 — High |
| Recommendation quality gate | 🔶 | 1 — High |
| WebSocket real-time push | 🔲 | 1 — Medium |
| Rate limiting | 🔲 | 1 — Medium |
| PATCH product update | 🔲 | 1 — Low |
| Collaborative filtering | 🔲 | 2 — Very High |
| A/B testing | 🔲 | 2 — High |
| Feedback loop re-weighting | 🔶 | 2 — High |
| Trending recommendations | 🔲 | 2 — Medium |
| Confidence calibration | 🔲 | 2 — Medium |
| LangSmith metadata enrichment | 🔶 | 2 — Medium |
| Onboarding questionnaire | 🔲 | 3 — High |
| Semantic search | 🔲 | 3 — High |
| Course progress tracking | 🔲 | 3 — Medium |
| Email notifications | ✅ | 3 — Done |
| Prometheus metrics | 🔲 | 4 — Medium |
| Enhanced health check | 🔲 | 4 — Low |
| Event archival | 🔲 | 4 — Low |
| Multi-language | 🔲 | 5 — High |
| LLM fine-tuning | 🔲 | 5 — Very High |
| Multi-tenant | 🔲 | 5 — High |
