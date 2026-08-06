# SmartReco AI — Architecture Flow Diagram

> Full system architecture showing every component, data flow, and integration point.

---

## High-Level System Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          SMARTRECO AI SYSTEM                                 │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │                        PRESENTATION LAYER                            │    │
│  │                                                                      │    │
│  │  Browser ──────────────────────────────────────────────────────┐    │    │
│  │    │  GET /login, /dashboard, /products, /admin/*              │    │    │
│  │    │  [Jinja2 + Bootstrap 5 dark theme]                        │    │    │
│  │    │                                                            │    │    │
│  │    │  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  │    │    │
│  │    │  │  tracker.js  │  │ dashboard.js │  │   feedback.js    │  │    │    │
│  │    │  │ batch events │  │ render data  │  │ submit feedback  │  │    │    │
│  │    │  │ every 5s/20  │  │ from API     │  │ as rating event  │  │    │    │
│  │    │  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │    │    │
│  │    └─────────┼────────────────┼────────────────────┼────────────┘    │    │
│  └─────────────┼────────────────┼────────────────────┼─────────────────┘    │
│                │                │                     │                       │
│                ▼                ▼                     ▼                       │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │                          API GATEWAY LAYER                           │    │
│  │                     FastAPI  (port 8000)                             │    │
│  │                                                                      │    │
│  │   ┌────────────────────────────────────────────────────────────┐    │    │
│  │   │                     MIDDLEWARE CHAIN                        │    │    │
│  │   │  RequestIDMiddleware → AccessLogMiddleware → CORSMiddleware │    │    │
│  │   └────────────────────────────────────────────────────────────┘    │    │
│  │                                                                      │    │
│  │   ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐  │    │
│  │   │  /auth   │ │/products │ │ /events  │ │  /reco   │ │/dash   │  │    │
│  │   │ register │ │ list     │ │  batch   │ │ generate │ │board   │  │    │
│  │   │ login    │ │ detail   │ │  me      │ │  me      │ │analytics│  │    │
│  │   │ me       │ │/admin    │ │          │ │ feedback │ │        │  │    │
│  │   └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘  │    │
│  └────────┼────────────┼────────────┼────────────┼────────────┼───────┘    │
│           │            │            │            │            │              │
│           ▼            ▼            ▼            ▼            ▼              │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │                         SERVICE LAYER                                │    │
│  │                                                                      │    │
│  │  ┌──────────┐ ┌─────────────┐ ┌──────────────┐ ┌────────────────┐  │    │
│  │  │   Auth   │ │   Product   │ │    Event     │ │  Dashboard     │  │    │
│  │  │ Service  │ │   Service   │ │   Service    │ │  Service       │  │    │
│  │  │          │ │ dual-write  │ │ batch ingest │ │  read-only     │  │    │
│  │  │ JWT+bcrypt│ │ SQL+Qdrant │ │ auto-trigger │ │  cache-first   │  │    │
│  │  └──────────┘ └─────────────┘ └──────┬───────┘ └────────────────┘  │    │
│  │                                       │                              │    │
│  │              ┌────────────────────────┘                             │    │
│  │              ▼                                                       │    │
│  │  ┌───────────────────────────────────────────────────────────────┐  │    │
│  │  │              BEHAVIOR INTELLIGENCE LAYER                      │  │    │
│  │  │                                                               │  │    │
│  │  │  BehaviorAnalyzer                                             │  │    │
│  │  │       ├── InterestExtractor  (categories, tags, searches)     │  │    │
│  │  │       └── EngagementScorer   (score [0-1], learning level)    │  │    │
│  │  │                                                               │  │    │
│  │  │  RecommendationTrigger (4 rules — OR logic)                   │  │    │
│  │  │       ├── Rule 1: ≥ 20 new events since last recommendation   │  │    │
│  │  │       ├── Rule 2: repeated search query                       │  │    │
│  │  │       ├── Rule 3: purchase or wishlist event present          │  │    │
│  │  │       └── Rule 4: inactive ≥ 10 minutes                       │  │    │
│  │  └───────────────────────┬───────────────────────────────────────┘  │    │
│  │                          │ trigger fires                             │    │
│  │                          ▼                                           │    │
│  │  ┌───────────────────────────────────────────────────────────────┐  │    │
│  │  │            LANGGRAPH RECOMMENDATION WORKFLOW                  │  │    │
│  │  │                                                               │  │    │
│  │  │  load_profile → build_query → retrieve_products              │  │    │
│  │  │                                      ↑                       │  │    │
│  │  │                               evaluate_quality               │  │    │
│  │  │                              ↙ good        ↘ poor            │  │    │
│  │  │                        (continue)     refine_query ──────────┘  │    │
│  │  │                              ↓                                   │  │    │
│  │  │                 generate_recommendation                         │  │    │
│  │  │                 [MESH API LLM call]                             │  │    │
│  │  │                 [LangSmith trace]                               │  │    │
│  │  │                              ↓                                   │  │    │
│  │  │                 validate_products (output guard)                │  │    │
│  │  │                              ↓                                   │  │    │
│  │  │                 store_recommendation → PostgreSQL               │  │    │
│  │  └───────────────────────────────────────────────────────────────┘  │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │                      DATA & INFRASTRUCTURE LAYER                     │    │
│  │                                                                      │    │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────┐  ┌────────────┐  │    │
│  │  │ PostgreSQL 16 │  │    Qdrant    │  │  Redis 7 │  │ APScheduler│  │    │
│  │  │               │  │  (vectors)   │  │  (cache) │  │  (jobs)    │  │    │
│  │  │ • users       │  │              │  │          │  │            │  │    │
│  │  │ • products    │  │ • 384-dim    │  │ behavior │  │ daily reco │  │    │
│  │  │ • user_events │  │   embeddings │  │  10 min  │  │ refresh    │  │    │
│  │  │ • recommenda- │  │ • cosine     │  │ reco     │  │ hourly     │  │    │
│  │  │   tions       │  │   similarity │  │  30 min  │  │ cache log  │  │    │
│  │  │               │  │ • BGE model  │  │ dashboard│  │ daily      │  │    │
│  │  │               │  │              │  │  5 min   │  │ event GC   │  │    │
│  │  └──────────────┘  └──────────────┘  └──────────┘  └────────────┘  │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────┐    │
│  │                      EXTERNAL SERVICES                               │    │
│  │                                                                      │    │
│  │  ┌────────────────────────┐      ┌──────────────────────────────┐   │    │
│  │  │      MESH API           │      │         LANGSMITH            │   │    │
│  │  │  api.meshapi.ai/v1      │      │   smith.langchain.com        │   │    │
│  │  │                         │      │                              │   │    │
│  │  │  OpenAI-compatible LLM  │      │  Trace collection for        │   │    │
│  │  │  Model: minimax/m2-her  │      │  every LangGraph run         │   │    │
│  │  │  Free · 32k context     │      │  Project: SmartReco-AI       │   │    │
│  │  └────────────────────────┘      └──────────────────────────────┘   │    │
│  └──────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Request Flow: Dashboard Load

```
User opens /dashboard
     │
     ▼
GET /api/v1/dashboard  (Bearer token)
     │
     ├─ JWT verify → get user_id
     │
     ▼
DashboardService.get_dashboard(user_id)
     │
     ├─ Redis.get("dashboard:{user_id}")
     │       │
     │   HIT ◄──── return cached DashboardResponse (cache_hit=True)
     │       │
     │   MISS
     │       │
     │       ├─ Redis.get("behavior:{user_id}")
     │       │       │
     │       │   HIT ◄── return cached profile dict
     │       │       │
     │       │   MISS
     │       │       │
     │       │       └─ BehaviorAnalyzer.build_profile(user_id)
     │       │               ├─ EventRepository.get_recent_events(200)
     │       │               ├─ ProductRepository.get_by_ids(product_ids)
     │       │               ├─ InterestExtractor → categories, tags, searches
     │       │               └─ EngagementScorer  → score, learning_level
     │       │           Redis.set("behavior:{user_id}", TTL=600)
     │       │
     │       ├─ RecommendationRepository.get_latest_for_user(user_id)
     │       │   (DB read only — no LLM call)
     │       │
     │       ├─ EventRepository.get_recent_events(10) → timeline
     │       │
     │       └─ Assemble DashboardResponse
     │           Redis.set("dashboard:{user_id}", TTL=300)
     │
     ▼
Return DashboardResponse (200 OK)
     │
     ▼
dashboard.js renders:
     ├─ Welcome banner + engagement bar
     ├─ Behavior summary (categories, tags, level)
     ├─ AI recommendation story + confidence badge
     ├─ Recommended courses grid (top 5)
     ├─ Recent searches tags
     └─ Activity timeline (last 10 events)
```

---

## Request Flow: Event Ingest → Auto-Trigger

```
User clicks a course / searches / makes a purchase
     │
     ▼
tracker.js buffers event → flushes every 5s or 20 events
     │
     ▼
POST /api/v1/events/batch  { events: [...] }
     │
     ▼
EventService.ingest_batch()
     ├─ EventRepository.insert_batch()  ──► PostgreSQL (single INSERT)
     └─ db.commit()
     │
     ▼
RecommendationService.should_generate(user_id)
     │
     ├─ EventRepository.get_recent_events(200)
     ├─ RecommendationRepository.get_latest_for_user()
     │
     └─ RecommendationTrigger.evaluate()
           ├─ Rule 1: events_since_last_reco ≥ 20  ?
           ├─ Rule 2: repeated search query         ?
           ├─ Rule 3: purchase or wishlist event    ?
           └─ Rule 4: inactive ≥ 10 minutes         ?
                 │
            any TRUE
                 │
                 ▼
         RecommendationService.generate(user_id)
                 │
                 ▼
         LangGraph Workflow (8 nodes)
                 │
                 ├─ Mesh API call  ──► minimax/m2-her
                 ├─ LangSmith trace sent
                 └─ Recommendation persisted to PostgreSQL
                       │
                       ▼
                 Redis.delete("dashboard:{user_id}")
                 Redis.delete("behavior:{user_id}")
     │
     ▼
Return BatchEventResponse (202 Accepted)
```
