# SmartReco AI — Feature Enhancement Roadmap

> Prioritised ideas for taking SmartReco AI from hackathon to production-grade platform.

---

## Priority 1 — Production Readiness

### 1.1 Async Background Task Queue
**Current**: Recommendation generation runs synchronously inside the `/events/batch` HTTP request — LLM latency (2–10s) blocks the response.

**Enhancement**: Move generation to an async worker queue (Celery + Redis Broker, or ARQ, or FastAPI's `BackgroundTasks`).

```
POST /events/batch
    ├─ persist events (fast, <50ms)
    ├─ evaluate trigger (fast, <10ms)
    └─ push user_id to task queue  ──► worker picks up asynchronously
Return 202 immediately

Worker:
    └─ RecommendationService.generate(user_id)
    └─ Optionally: WebSocket push to client
```

**Impact**: API latency drops from 2–10s to <100ms on every event batch.

---

### 1.2 WebSocket / Server-Sent Events for Real-Time Dashboard
**Current**: Dashboard data is static — user must refresh to see new recommendations.

**Enhancement**: After a recommendation is generated, push an SSE event to the user's open browser tab.

```python
# FastAPI SSE endpoint
@router.get("/api/v1/dashboard/stream")
async def dashboard_stream(request: Request, current_user=Depends(get_current_user)):
    async def event_generator():
        while True:
            if await recommendation_ready(current_user.id):
                yield {"event": "recommendation_ready", "data": "reload"}
            await asyncio.sleep(3)
    return EventSourceResponse(event_generator())
```

---

### 1.3 Rate Limiting
**Current**: No per-user API limits.

**Enhancement**: Sliding window rate limits using Redis:

| Endpoint | Limit |
|---|---|
| `POST /events/batch` | 100 req/min per user |
| `POST /auth/register` | 5 req/hour per IP |
| `POST /recommendations/generate` | 10 req/hour per admin |

```python
# slowapi or custom Redis sliding window
@limiter.limit("100/minute")
async def ingest_batch(...):
```

---

### 1.4 Partial Product Update (PATCH)
**Current**: `PUT /admin/products/{id}` requires sending all fields (full replacement).

**Enhancement**: Add `PATCH` endpoint for partial updates — only send changed fields.

```python
class PatchProductRequest(AppBaseSchema):
    title: str | None = None
    category: str | None = None
    difficulty: str | None = None
    tags: list[str] | None = None
    is_active: bool | None = None
```

---

## Priority 2 — Recommendation Quality

### 2.1 Collaborative Filtering Layer
**Current**: Recommendations are purely content-based (user's own profile → similar products).

**Enhancement**: Add user-user and item-item collaborative filtering using matrix factorisation.

```
"Users like you also studied:" section on dashboard
    ├─ Find users with similar event patterns (cosine similarity on interaction matrices)
    ├─ Recommend products they engaged with that you haven't seen
    └─ Blend with content-based score (weighted hybrid)
```

**Approach**: Implicit feedback ALS (Alternating Least Squares) via `implicit` library, or neural collaborative filtering.

---

### 2.2 A/B Testing for Recommendation Strategies
**Current**: One recommendation strategy for all users.

**Enhancement**: Run multiple strategies simultaneously and compare CTR/conversion:

```python
class RecommendationStrategy(str, Enum):
    CONTENT_BASED = "content_based"     # current LangGraph workflow
    COLLABORATIVE  = "collaborative"     # user-user CF
    HYBRID         = "hybrid"           # blend of both
    TRENDING       = "trending"         # popularity-based fallback

# Assign strategy by user_id hash bucket
strategy = assign_strategy(user_id)
```

Track recommendation clicks → report CTR per strategy in admin analytics.

---

### 2.3 Confidence Calibration
**Current**: LLM self-reports confidence (0.0–1.0) — not calibrated against actual outcomes.

**Enhancement**: Track recommendation → click → purchase conversion. Recalibrate confidence scores using historical accuracy:

```
calibrated_confidence = model_confidence * historical_accuracy_for_similar_profiles
```

---

### 2.4 Feedback Loop Integration
**Current**: `POST /recommendations/{id}/feedback` stores a RATING event but the next recommendation generation doesn't use it differently.

**Enhancement**: Weight liked/disliked recommendations in the behavior profile:
- Liked → boost category/tags weight in interest extractor
- Disliked → penalise that category for future retrieval queries

---

### 2.5 Trending / Seasonal Recommendations
**Current**: `GET /recommendations/trending` returns a placeholder.

**Enhancement**: Implement trending based on:
- Event velocity (products gaining most interactions in last 24h)
- New courses (recently added)
- Seasonal relevance (time-of-year weighting)

---

## Priority 3 — User Experience

### 3.1 Email Notifications
**Current**: No outbound communication.

**Enhancement**: Send email when a new recommendation is ready:

```
Subject: "Your personalised learning path is ready, A Sahu!"
Body: recommendation summary + top 3 courses with CTAs
```

**Tech**: FastAPI + `fastapi-mail` + SendGrid/Mailgun. Triggered in the `store_recommendation` node.

---

### 3.2 User Onboarding Flow
**Current**: New users see "No activity yet" immediately after registration.

**Enhancement**: Add a 3-step onboarding questionnaire:
1. What topics interest you? (multi-select categories)
2. What's your current level? (beginner / intermediate / advanced)
3. What's your goal? (career change / upskill / hobby)

Store selections as synthetic events to bootstrap the behavior profile before any organic activity.

---

### 3.3 Course Progress Tracking
**Current**: Only event tracking — no concept of "enrolled" or "completed".

**Enhancement**: 
- Add `ENROLL` and `COMPLETE` event types
- Track completion rate per category
- Surface "continue learning" section on dashboard
- Adjust recommendations to avoid already-completed courses

---

### 3.4 Search with Semantic Results
**Current**: `/products` page lists all courses — basic category filter only.

**Enhancement**: Real semantic search — embed the search query and return the most similar products from Qdrant:

```python
GET /api/v1/products/search?q=build+chatbots+with+python
# → returns semantically relevant courses, not just keyword matches
```

---

## Priority 4 — Observability & Operations

### 4.1 Structured Metrics with Prometheus
**Current**: Logs only.

**Enhancement**: Expose Prometheus metrics at `/metrics`:

```
smartreco_recommendations_total{status="success", model="minimax/m2-her"}
smartreco_recommendation_confidence_histogram
smartreco_cache_hit_rate{cache="dashboard"}
smartreco_event_ingest_rate
smartreco_trigger_fires_total{rule="purchase_or_wishlist"}
```

Use `prometheus-fastapi-instrumentator` for automatic HTTP metrics.

---

### 4.2 LangSmith Metadata Enrichment
**Current**: Basic LangGraph traces captured.

**Enhancement**: Add rich metadata to every trace:

```python
@traceable(
    name="SmartReco-AI/recommendation",
    metadata={
        "user_id": str(user_id),
        "cache_hit": was_cached,
        "trigger_rule": trigger_reason,
        "behavior_score": profile.engagement_score,
        "candidate_count": len(candidates),
        "retrieval_attempts": attempts,
        "workflow_version": "v2",
    }
)
def _run_workflow(...):
```

Enables filtering traces by trigger rule, confidence range, user segment, etc.

---

### 4.3 Health Check Enhancement
**Current**: `/health/ready` checks DB only.

**Enhancement**: Add dependency checks to readiness probe:

```json
GET /health/ready
{
  "status": "ready",
  "checks": {
    "database": "ok",
    "redis": "ok",
    "qdrant": "ok",
    "llm_api": "ok"
  }
}
```

Return `degraded` (not `503`) when non-critical services (Redis, LLM) are unavailable.

---

### 4.4 Event Archival Pipeline
**Current**: `event_cleanup` job only logs the count of old events.

**Enhancement**: Actually archive events older than 90 days to a cold storage table or S3:

```sql
-- Archive to a partitioned cold storage table
INSERT INTO user_events_archive SELECT * FROM user_events WHERE created_at < NOW() - INTERVAL '90 days';
DELETE FROM user_events WHERE created_at < NOW() - INTERVAL '90 days';
```

Keeps the hot `user_events` table lean for fast analytics queries.

---

## Priority 5 — Scale & Internationalisation

### 5.1 Multi-Language Support
**Current**: English-only product descriptions and recommendations.

**Enhancement**: 
- Use multilingual embedding model (`paraphrase-multilingual-MiniLM-L12-v2`)
- Detect user's locale from browser `Accept-Language` header
- Pass locale to LLM prompt for localised recommendation stories

---

### 5.2 LLM Fine-Tuning
**Current**: Zero-shot prompting with `minimax/m2-her`.

**Enhancement**: Fine-tune a smaller model on high-quality recommendation examples:

1. Collect 1,000+ human-validated recommendation pairs (profile → story)
2. Fine-tune `Llama-3-8B` or `Mistral-7B` via LoRA
3. Host on Together AI or deploy locally
4. Replace `minimax/m2-her` with fine-tuned model for lower latency + higher quality

---

### 5.3 Multi-Tenant Support
**Current**: Single-tenant — all users and products share one namespace.

**Enhancement**: Add `tenant_id` to users, products, and events to support multiple organisations on one deployment. Each tenant gets isolated:
- Product catalogue
- Recommendation models
- Analytics dashboards
- Cache namespaces: `{tenant_id}:behavior:{user_id}`

---

### 5.4 Vector Index Optimisation
**Current**: Flat cosine similarity search in Qdrant.

**Enhancement**: 
- Add HNSW index tuning (`m=16`, `ef_construct=100`) for faster search at scale
- Implement payload filtering in Qdrant to pre-filter by `is_active` and `category` before vector similarity
- Add vector quantisation (scalar or product) to reduce memory footprint at 100k+ products

---

## Summary Table

| Enhancement | Priority | Effort | Impact |
|---|---|---|---|
| Async background tasks | 1 | Medium | Very High |
| WebSocket real-time push | 1 | Medium | High |
| Rate limiting | 1 | Low | High |
| PATCH product update | 1 | Low | Medium |
| Collaborative filtering | 2 | High | Very High |
| A/B testing strategies | 2 | High | High |
| Feedback loop integration | 2 | Medium | High |
| Trending recommendations | 2 | Medium | Medium |
| Email notifications | 3 | Low | Medium |
| Onboarding flow | 3 | Medium | High |
| Semantic search | 3 | Low | High |
| Prometheus metrics | 4 | Low | High |
| LangSmith enrichment | 4 | Low | Medium |
| Event archival | 4 | Medium | Medium |
| Multi-language | 5 | High | High |
| LLM fine-tuning | 5 | Very High | Very High |
| Multi-tenant | 5 | Very High | High |
