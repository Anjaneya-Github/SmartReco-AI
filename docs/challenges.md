# SmartReco AI — Engineering Challenges & Solutions

> Every significant challenge encountered during development, the root cause, and how it was resolved.

---

## 1. SQLAlchemy Reserved Column Name: `metadata`

**Challenge**  
The `UserEvent` model had a column named `metadata` (a JSONB column for event context). SQLAlchemy's `DeclarativeBase` reserves the name `metadata` internally as a class-level attribute for table metadata. Defining a mapped column with the same name caused:

```
sqlalchemy.exc.InvalidRequestError: Attribute name 'metadata' is reserved
when using the Declarative API.
```

This broke every model import — the entire app failed to start.

**Root Cause**  
SQLAlchemy 2.0's declarative system uses `metadata` as a special attribute that holds the `MetaData` object. Any `mapped_column` with that name collides with it.

**Solution**  
Renamed the Python attribute to `event_metadata` while keeping the DB column name as `metadata` using SQLAlchemy's column name override:

```python
event_metadata: Mapped[dict] = mapped_column(
    "metadata",   # ← DB column name stays "metadata"
    JSONB,
    nullable=False,
    default=dict,
    server_default="{}",
)
```

`bulk_insert_mappings` uses DB column names so existing migration SQL was unaffected. Updated all test files that assigned `e.metadata = {}` to use `e.event_metadata = {}`.

---

## 2. Starlette 1.4.1 — TemplateResponse Signature Change

**Challenge**  
All HTML pages returned HTTP 500 with a cryptic error:

```
TypeError: unhashable type: 'dict'
```

The Jinja2 `LRUCache` was receiving a `dict` as a cache key.

**Root Cause**  
Starlette 1.4.1 changed the `TemplateResponse` constructor signature. The old pattern:

```python
# OLD — breaks in Starlette 1.4.1
return templates.TemplateResponse("login.html", {"request": request})
```

The first positional argument is now interpreted as the name, but `{"request": request}` (a dict) was being passed as the template name — Jinja2 then tried to use the dict as a cache key.

**Solution**  
Updated all template response calls to the new signature:

```python
# NEW — correct for Starlette 1.4.1+
return templates.TemplateResponse(request, "login.html")
return templates.TemplateResponse(request, "product_detail.html", {"product_id": str(pid)})
```

---

## 3. Missing Database Migrations — Tables Don't Exist

**Challenge**  
After adding the `user_events` and `recommendations` tables, the dashboard returned 500 with:

```
sqlalchemy.exc.ProgrammingError: relation "user_events" does not exist
```

**Root Cause**  
The Alembic migration chain had only been applied up to `b2c3d4e5f6a7` (products table). The two newer migrations (`c3d4e5f6a7b8` for user_events, `d4e5f6a7b8c9` for recommendations) had never been run against the live database.

**Solution**  
```bash
alembic upgrade head
```

This applied both pending migrations. The `alembic current` command confirms the active revision.

**Prevention**  
Always run `alembic upgrade head` after pulling new migrations. The CI pipeline should run this automatically before tests.

---

## 4. Redis Blocking the Dashboard on Connection Failure

**Challenge**  
When Redis was not running, the dashboard API endpoint timed out entirely. Every request hung for 30+ seconds before returning 500.

**Root Cause**  
The original `CacheClient` used `redis.Redis.from_url()` with default timeouts (`socket_connect_timeout=2`, `socket_timeout=2`). But the connection attempt happened on every cache operation, not just at startup. Each `.get()` and `.set()` call triggered a 2-second timeout, stacking multiple times per request.

**Solution**  
Rewrote `CacheClient` to:
1. Attempt connection **once** at init with a 1-second timeout
2. Cache the result (`None` if failed) via `@lru_cache` on the factory function
3. Make every method a **true no-op** when `self._enabled = False`

```python
@lru_cache(maxsize=1)
def _get_redis_or_none():
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        return client
    except Exception:
        logger.warning("Redis unavailable — caching disabled.")
        return None
```

Result: one 1-second timeout at startup, then instant no-ops for the rest of the process lifetime.

---

## 5. PowerShell `Out-File` Creates Files with Null Bytes

**Challenge**  
Several `__init__.py` files created using PowerShell's `Out-File` command contained null bytes (UTF-16 BOM or zero-padded encoding). Python rejected them with:

```
SyntaxError: source code string cannot contain null bytes
```

**Root Cause**  
PowerShell's `Out-File` defaults to UTF-16 LE encoding on Windows, which adds a BOM (0xFF 0xFE) and null bytes between characters. Python's source code parser only accepts UTF-8 without BOM.

**Solution**  
Replaced `Out-File` with `Set-Content -Encoding UTF8`:

```powershell
Set-Content -Path "app/cache/__init__.py" -Value "" -Encoding UTF8
```

Or better: used Kiro's `fs_write` tool which always writes UTF-8.

---

## 6. Embedding Model Load Timeout on First Product Creation

**Challenge**  
The first `POST /admin/products` call timed out. `httpx` requests with `timeout=30` failed while seeding the product catalogue.

**Root Cause**  
The `EmbeddingService` uses `sentence-transformers` with `BAAI/bge-small-en-v1.5`. The model is loaded lazily on first use via `@lru_cache`. The initial load downloads weights (~120 MB) and initialises the model — taking 20–60 seconds depending on network and hardware.

**Solution**  
Increased the `httpx` timeout to 120 seconds for seeding scripts and used a persistent `httpx.Client` across all 20 products:

```python
with httpx.Client(timeout=120) as client:
    for course in COURSES:
        r = client.post(url, json=course, headers=headers)
```

Subsequent calls are fast (~1–2s) since the model stays in memory.

---

## 7. `tencent/hy3` Returns Empty Content Field

**Challenge**  
After discovering that the Mesh account had insufficient balance for paid models, we switched to `tencent/hy3` (a free model). All dashboard tests showed empty recommendation text — `reply = ""` despite the model returning 120 tokens.

**Root Cause**  
`tencent/hy3` is a **reasoning model** (similar to o1/o3). It uses all output tokens for internal chain-of-thought reasoning stored in `completion_tokens_details.reasoning_tokens`. The `message.content` field is always empty — only the final answer would appear in a `reasoning_content` field if exposed.

```
finish_reason: length
content: ''
usage: CompletionUsage(
    completion_tokens=120,
    completion_tokens_details=CompletionTokensDetails(reasoning_tokens=120, text_tokens=0)
)
```

**Solution**  
Switched to `minimax/m2-her` — the other available free model (32k context, text output). Verified it correctly responds to `system` + `user` prompt structure and returns proper text content.

---

## 8. LangGraph `TemplateResponse` / `functools.partial` Node Binding

**Challenge**  
LangGraph nodes must be unary callables `(state) → partial_state`. Our nodes needed injected dependencies (`WorkflowDeps`). Initial attempts to register bound methods caused graph compile errors.

**Root Cause**  
LangGraph's `StateGraph.add_node()` expects exactly one positional argument (the state). Passing `deps` as a second argument caused type errors at graph invocation time.

**Solution**  
Used `functools.partial` to pre-bind `deps` as a keyword argument, producing a clean unary callable:

```python
def _bind(fn: Callable) -> Callable:
    return functools.partial(fn, deps=deps)

graph.add_node("load_profile", _bind(load_profile))
```

Each node signature is `(state: RecommendationState, deps: WorkflowDeps) -> dict`, and `_bind` turns it into `(state) -> dict`.

---

## 9. `EventResponse` Schema References `metadata` Field

**Challenge**  
After renaming `UserEvent.metadata` to `event_metadata`, the `EventResponse` Pydantic schema still had a field named `metadata`. When constructing `EventResponse.model_validate(event)`, Pydantic tried to read `.metadata` from the ORM object — which no longer existed.

**Root Cause**  
`AppBaseSchema` uses `from_attributes=True` — Pydantic reads values by attribute name from ORM objects. The schema field `metadata` would attempt to read `orm_obj.metadata`, which is now `None` (SQLAlchemy's table metadata descriptor) not the JSONB value.

**Solution**  
Added a `field_serializer` / `model_validator` approach: the `EventResponse.metadata` field maps to `event_metadata` on the ORM model using `alias` or a custom validator. The simplest fix was keeping `metadata` as the field name in the schema (since clients expect it) but populating it from `event_metadata` via a `computed_field` approach, or simply mapping it in the service layer when building responses.

---

## 10. Admin Products Page — `/api/v1/admin/products` Returns 405

**Challenge**  
The admin products UI called `GET /api/v1/admin/products?limit=100` but received a 405 Method Not Allowed.

**Root Cause**  
The admin router only had `POST`, `PUT`, and `DELETE` endpoints for products. There was no `GET` list endpoint — admin product listing reuses the public `GET /api/v1/products` endpoint with pagination. The frontend template was calling the wrong path.

**Solution**  
Updated the admin products template to call `GET /api/v1/products?page_size=100` (the public, non-auth-required endpoint) for listing, while still using the admin endpoints for CRUD operations.

---

## 11. APScheduler Blocking Startup on DB Connection Issues

**Challenge**  
The `daily_recommendation_refresh` job ran immediately on scheduler start (misfire recovery) and hung the application startup when the DB was unavailable.

**Root Cause**  
APScheduler's default `misfire_grace_time` was not set, causing missed jobs to run immediately on startup. If the DB wasn't ready (e.g., Docker Compose starting order), the job blocked.

**Solution**  
Added `misfire_grace_time=600` (10 minutes) to all cron jobs, preventing immediate execution of missed jobs. Also wrapped the scheduler start in a try/except in the lifespan handler so a scheduler failure never prevents the API from starting:

```python
try:
    from app.scheduler.scheduler import start_scheduler
    start_scheduler()
except Exception as exc:
    logger.warning("Scheduler failed to start. error=%s", exc)
```

---

## 12. Qdrant Vector Mode Discovery

**Challenge**  
During development, Qdrant was sometimes unavailable (Docker not running). The `VectorService` would throw unhandled exceptions propagating to the API layer.

**Solution**  
`VECTOR_MODE=memory` provides an in-process Qdrant client for dev/CI — zero external dependencies, data lost on restart. Startup logs a prominent warning:

```
⚠ Qdrant running in IN-MEMORY mode. Data will be lost on restart. NOT for production.
```

The `retrieve_products` LangGraph node also has a graceful fallback to DB listing when Qdrant is unreachable:

```python
except Exception as exc:
    logger.warning("vector search failed, using DB fallback. error=%s", exc)
    fallback, _ = deps.product_repo.list_active(limit=max_products)
    product_map = {str(p.id): _product_to_dict(p) for p in fallback}
```
