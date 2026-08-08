# SmartReco AI — Architecture Reference

> **Audience:** Developers, architects, and reviewers who want to understand how the system is structured.
>
> **What's here:** System-level diagrams, LangGraph workflow detail, full data flow, and cache architecture — all as ASCII art that renders in any Markdown viewer.
>
> **Related docs:**
> - [`docs/prd.md`](prd.md) — What the system does (requirements)
> - [`docs/feature_enhancements.md`](feature_enhancements.md) — What's built and what's planned
> - [`README.md`](../README.md) — Full setup and API guide

---

## 1. System Architecture

> **Frontend note:** Bootstrap 5.3.3 and Bootstrap Icons are loaded from **jsDelivr CDN**
> (no npm/pip install). The templates are server-rendered Jinja2 HTML.
> All dashboard data is loaded client-side via `fetch()` calls to the JSON API.
> Vanilla JS only — no React, Vue, or Angular.

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT LAYER                                        │
│                                                                                  │
│   Browser (Bootstrap 5 UI — CDN)    API Consumer (Swagger / curl / SDK)         │
│   /login  /dashboard  /products     /api/v1/...                                 │
│   /admin/dashboard  /admin/products                                              │
└─────────────────────────────┬───────────────────────────────────────────────────┘
                              │  HTTPS / HTTP
                              ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           FASTAPI APPLICATION  (port 8000)                       │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  MIDDLEWARE STACK  (outermost → innermost)                                │   │
│  │  RequestIDMiddleware → AccessLogMiddleware → CORSMiddleware               │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                  │
│  ┌───────────────┐  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐  │
│  │  /auth        │  │  /products   │  │  /events      │  │  /recommendations│  │
│  │  register     │  │  list        │  │  batch ingest │  │  generate        │  │
│  │  login        │  │  get by id   │  │  my events    │  │  my latest       │  │
│  │  me           │  │              │  │               │  │  feedback        │  │
│  └───────┬───────┘  └──────┬───────┘  └───────┬───────┘  └────────┬─────────┘  │
│          │                 │                  │                    │            │
│  ┌───────▼───────┐  ┌──────▼───────┐  ┌───────▼───────┐  ┌────────▼─────────┐  │
│  │  AuthService  │  │ProductService│  │ EventService  │  │Recommendation    │  │
│  │               │  │  dual-write  │  │               │  │Service           │  │
│  │  JWT + bcrypt │  │  SQL+Qdrant  │  │  bulk insert  │  │  LangGraph       │  │
│  └───────┬───────┘  └──────┬───────┘  └───────┬───────┘  │  Workflow        │  │
│          │                 │                  │           │  orchestrator    │  │
│  ┌───────▼──────────────────────────────────────────────  └────────┬─────────┘  │
│  │                   BEHAVIOR INTELLIGENCE LAYER                   │            │
│  │   BehaviorAnalyzer                                              │            │
│  │     └─ InterestExtractor   (categories, tags, searches)        │            │
│  │     └─ EngagementScorer    (score, learning level)             │            │
│  │     └─ RecommendationTrigger  (4 rules, DB-free)               │            │
│  └────────────────────────────────────────────────────────────────┘            │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │  DASHBOARD + ANALYTICS           │  SCHEDULER (APScheduler)             │    │
│  │  DashboardService (read-only)    │  daily_reco_refresh  08:00 UTC       │    │
│  │  cache-first aggregation         │  cache_cleanup       every hour      │    │
│  │  GET /api/v1/dashboard           │  event_cleanup       02:00 UTC       │    │
│  │  GET /api/v1/dashboard/analytics │  POST /admin/scheduler/run           │    │
│  └──────────────────────────────────┴──────────────────────────────────────┘    │
│                                                                                  │
│  ┌─────────────────────────────────────────────────────────────────────────┐    │
│  │  AI GUARDRAILS                                                           │    │
│  │  PromptGuard → PromptSanitizer → OutputGuard                            │    │
│  └─────────────────────────────────────────────────────────────────────────┘    │
└──────────────┬──────────────────┬──────────────────┬──────────────────┬─────────┘
               │                  │                  │                  │
               ▼                  ▼                  ▼                  ▼
┌──────────────────┐  ┌───────────────────┐  ┌────────────┐  ┌─────────────────┐
│  PostgreSQL 16   │  │   Qdrant           │  │  Redis 7   │  │  Mesh API       │
│                  │  │   Vector Store     │  │            │  │  (LLM Gateway)  │
│  users           │  │   BAAI/bge-small   │  │  behavior  │  │                 │
│  products        │  │   384-dim          │  │  reco      │  │  minimax/m2-her │
│  user_events     │  │   cosine similarity│  │  dashboard │  │  32k context    │
│  recommendations │  │   HNSW index       │  │  search    │  │                 │
└──────────────────┘  └───────────────────┘  └────────────┘  └────────┬────────┘
                                                                        │
                                                              ┌─────────▼────────┐
                                                              │  LangSmith        │
                                                              │  Trace Collection │
                                                              │  per LangGraph    │
                                                              │  run              │
                                                              └──────────────────┘
```

---

## LangGraph Recommendation Workflow (Detailed)

```
     RecommendationService.generate(user_id)
                    │
                    ▼
         ┌──────────────────┐
         │  WorkflowDeps    │  ← BehaviorAnalyzer, ProductRepo,
         │  (dependency     │     RecRepo, DB Session
         │   injection)     │
         └────────┬─────────┘
                  │
                  ▼
         ┌──────────────────┐
     ┌──►│   StateGraph     │◄─── RecommendationState (TypedDict)
     │   │   (compiled)     │     user_id, profile, candidates,
     │   └────────┬─────────┘     retrieval_quality, llm_raw,
     │            │               parsed, result, error
     │            ▼
     │   ┌──────────────────┐
     │   │  load_profile    │  EventRepo.get_recent_events()
     │   │                  │  ProductRepo.get_by_ids()
     │   │  → profile dict  │  BehaviorAnalyzer.build_profile()
     │   └────────┬─────────┘
     │            ▼
     │   ┌──────────────────┐
     │   │  build_query     │  profile → pipe-delimited search string
     │   │                  │  "categories: ml | topics: pytorch | level: intermediate"
     │   │  → query string  │
     │   └────────┬─────────┘
     │            ▼
     │   ┌──────────────────┐
     │   │retrieve_products │  EmbeddingService.embed_query()
     │   │                  │  VectorService.search() → Qdrant
     │   │  → candidates{}  │  Fallback: ProductRepo.list_active()
     │   └────────┬─────────┘
     │            ▼
     │   ┌──────────────────┐
     │   │evaluate_quality  │  count ≥ 3?  AND  category overlap?
     │   │                  │
     │   │  → "good"/"poor" │
     │   └────────┬─────────┘
     │            │
     │     ┌──────┴──────┐
     │   "good"        "poor" + attempts < 2
     │     │               │
     │     │        ┌──────▼──────────┐
     │     │        │  refine_query   │  drop categories, keep searches + level
     │     │        │                 │  → broader query string
     │     │        └──────┬──────────┘
     └─────┼───────────────┘  loop back to retrieve_products
           │
           ▼ (quality "good" OR attempts exhausted)
   ┌──────────────────────┐
   │generate_recommendation│  OpenAI(
   │                       │    api_key=LLM_API_KEY,       ← Mesh API key
   │  Mesh API call        │    base_url=LLM_BASE_URL,     ← https://api.meshapi.ai/v1
   │  LangSmith trace      │    model=minimax/m2-her
   │                       │  ).chat.completions.create()
   │  → llm_raw string     │
   └────────┬──────────────┘
            ▼
   ┌──────────────────────┐
   │  validate_products   │  JSON parse  → strip hallucinated IDs
   │                      │  OutputGuard → confidence clamp, dedup
   │  → parsed dict       │  Fallback to top-N candidates if all invalid
   └────────┬─────────────┘
            ▼
   ┌──────────────────────┐
   │  store_recommendation│  RecRepo.create() → PostgreSQL COMMIT
   │                      │  Re-hydrate product details from ORM
   │  → result dict       │
   └────────┬─────────────┘
            ▼
           END  →  RecommendationResult schema
```

---

## Data Flow: Event → Trigger → Recommendation → Dashboard

```
User browses a course
        │
        ▼  tracker.js (batch every 5s / 20 events)
POST /api/v1/events/batch
        │
        ▼
EventService.ingest_batch()
  └─ bulk INSERT into user_events
  └─ DB COMMIT
        │
        ▼
RecommendationService.should_generate()
  └─ EventRepository.get_recent_events(limit=200)
  └─ RecommendationTrigger.evaluate()
        │
        ├── Rule 1: events_since_last_reco ≥ 20
        ├── Rule 2: repeated search query
        ├── Rule 3: purchase or wishlist event
        └── Rule 4: inactive ≥ 10 minutes
              │
              │ any rule fires
              ▼
        RecommendationService.generate()
          └─ LangGraph workflow (8 nodes)
          └─ Mesh API LLM call
          └─ Recommendation persisted to DB
          └─ Dashboard cache invalidated
              │
              ▼
GET /api/v1/dashboard
  └─ CacheClient.get("dashboard:{user_id}")  ← HIT: return immediately
  └─ MISS: BehaviorAnalyzer + RecRepo reads  ← MISS: compute + cache
  └─ DashboardResponse { cache_hit: true/false }
              │
              ▼
        Browser renders:
          - Recommendation Story
          - Confidence Score
          - Top 5 Courses
          - Behavior Summary
          - Activity Timeline
```

---

## Cache Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    Redis Cache Layers                     │
├──────────────────┬───────┬──────────────────────────────┤
│ Key Pattern      │  TTL  │ Invalidated By                │
├──────────────────┼───────┼──────────────────────────────┤
│ behavior:{uid}   │ 10min │ New events ingested           │
│ recommendation:  │ 30min │ New recommendation generated  │
│  {uid}:{hash}    │       │                               │
│ dashboard:{uid}  │  5min │ Feedback / new recommendation │
│ search:{hash}    │ 30min │ Product catalogue updated     │
│ analytics:global │  5min │ Time-based expiry only        │
└──────────────────┴───────┴──────────────────────────────┘

Graceful degradation: if Redis is unavailable,
CacheClient disables itself (1s connect timeout,
cached None via lru_cache). All operations become
transparent no-ops. App continues without caching.
```
