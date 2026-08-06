# SmartReco AI — Challenges & Solutions

A honest account of every significant problem encountered while building this project, and how each was resolved.

---

## 1. SQLAlchemy `metadata` Reserved Attribute Clash

**When:** During behavior analysis — the first time events were queried after the `UserEvent` model was created.

**Problem:** The `UserEvent` ORM model had a column named `metadata` (a JSONB column). SQLAlchemy 2.0's `DeclarativeBase` reserves the name `metadata` on every mapped class for its own internal table metadata object. Defining a mapped column with that name caused a hard `InvalidRequestError` at class registration time — the app couldn't import the model at all.

**Error:**
```
sqlalchemy.exc.InvalidRequestError: Attribute name 'metadata' is reserved
when using the Declarative API.
```

**Solution:** Renamed the Python attribute to `event_metadata` while keeping the DB column name as `metadata` using SQLAlchemy's positional column name argument:

```python
event_metadata: Mapped[dict] = mapped_column(
    "metadata",   # DB column stays "metadata"
    JSONB, ...
)
```

Updated all test files that set `e.metadata = {}` to `e.event_metadata = {}`.

**Lesson:** Never name a SQLAlchemy mapped attribute `metadata`, `registry`, `__table__`, or any other SQLAlchemy-reserved identifier.

---

## 2. Starlette 1.4 `TemplateResponse` Signature Change

**When:** When the Jinja2 HTML pages (login, dashboard, products) returned HTTP 500.

**Problem:** The dashboard router called `TemplateResponse` using the old Starlette signature:
```python
# Old (Starlette < 1.0)
templates.TemplateResponse("login.html", {"request": request})
```
In Starlette 1.4.1, the signature changed to positional `(request, name, context)`. Passing a dict as the first positional argument caused Jinja2's LRU cache to receive a dict as a key → `TypeError: unhashable type: 'dict'`.

**Error:**
```
TypeError: unhashable type: 'dict'
  File "starlette/templating.py", TemplateResponse
  self.env.get_template(name)
```

**Solution:**
```python
# New (Starlette 1.4+)
templates.TemplateResponse(request, "login.html")
templates.TemplateResponse(request, "product_detail.html", {"product_id": pid})
```

**Lesson:** Always check library changelogs when upgrading. Starlette 1.x introduced breaking changes to Jinja2 response signatures.

---

## 3. Missing Database Migrations (Tables Not Created)

**When:** Dashboard returned 500 after Alembic was initially run only partially.

**Problem:** Alembic's migration history showed the DB was at revision `b2c3d4e5f6a7` (products table), but `user_events` and `recommendations` tables had not been created. Any query to those tables caused:
```
psycopg2.errors.UndefinedTable: relation "user_events" does not exist
```

The `metadata` attribute rename had caused an import error during earlier migration runs, leaving the DB at an intermediate state.

**Solution:**
```bash
alembic upgrade head
```
This applied the two pending migrations (`c3d4e5f6a7b8` → user_events, `d4e5f6a7b8c9` → recommendations).

**Lesson:** Always run `alembic current` and `alembic upgrade head` after any model change. A failed migration leaves the DB in an inconsistent state that must be diagnosed before any app logic runs.

---

## 4. Redis Blocking the Dashboard on Unavailability

**When:** After migrations were applied, the dashboard API timed out (15+ seconds) even though the DB was now working.

**Problem:** The `CacheClient` was connecting to Redis using `socket_connect_timeout=2`. Even though Redis wasn't running, every cache operation was waiting 2 seconds before failing. Since the dashboard service called the cache multiple times, a single request was stalling for 10+ seconds.

**Solution:** Changed the `CacheClient` to test connectivity once at instantiation (1s timeout), cache the result as `None` via `@lru_cache`, and short-circuit all subsequent calls:

```python
@lru_cache(maxsize=1)
def _get_redis_or_none():
    try:
        client = redis.Redis.from_url(url, socket_connect_timeout=1, socket_timeout=1)
        client.ping()
        return client
    except Exception:
        return None  # cached — no further connection attempts

class CacheClient:
    def __init__(self):
        self._r = _get_redis_or_none()
        self._enabled = self._r is not None

    def get(self, key):
        if not self._enabled:
            return None  # instant no-op
        ...
```

**Lesson:** Any optional external service must fail fast and stay failed. Never retry a connection inside a hot request path.

---

## 5. LangGraph Node Signature — `functools.partial` vs Direct Injection

**When:** Designing the LangGraph workflow nodes.

**Problem:** LangGraph nodes must be unary callables `(state) → partial_state`. But our nodes needed access to repositories and services (DB session, product repo, rec repo). Two approaches were considered:

- **Global singletons**: would have made testing impossible and tied nodes to the request lifecycle.
- **Closures**: verbose and hard to inspect.

**Solution:** Used a `WorkflowDeps` dataclass and `functools.partial` to bind deps as the second argument at graph-build time:

```python
@dataclass
class WorkflowDeps:
    analyzer: BehaviorAnalyzer
    product_repo: ProductRepository
    rec_repo: RecommendationRepository
    db: Any

def _bind(fn):
    return functools.partial(fn, deps=deps)

graph.add_node("load_profile", _bind(load_profile))
```

Each node signature is `(state, deps)`, making it trivially unit-testable by passing mock deps.

**Lesson:** Dependency injection at the graph boundary keeps nodes pure and testable. Use `functools.partial` to bind deps without closures.

---

## 6. Mesh API Model Selection — Empty Responses from Reasoning Model

**When:** Testing the free Mesh API models for the recommendation workflow.

**Problem:** `tencent/hy3` was listed as a free model with a 262k context window — ideal for large prompts. But every completion returned an empty `content` field:

```python
response.choices[0].message.content  # → ""
```

The token usage showed all tokens consumed as `reasoning_tokens`, with 0 `text_tokens` — the model was doing internal chain-of-thought but not surfacing its output in the standard content field (OpenAI-compatible format).

**Solution:** Switched to `minimax/m2-her` (the other free model, 32k context). This model correctly populates `choices[0].message.content`. Updated `LLM_MODEL` in `.env` and `config.py` default.

**Lesson:** Always smoke-test LLM providers before integrating them into a workflow. An OpenAI-compatible API does not guarantee identical response structure for all models.

---

## 7. PowerShell `Out-File` Creates UTF-16 Files with Null Bytes

**When:** Creating `__init__.py` files via PowerShell's `Out-File`.

**Problem:** PowerShell's default `Out-File` encoding is UTF-16 LE (BOM included), which Python's import system cannot parse. The null bytes between characters cause:

```
SyntaxError: source code string cannot contain null bytes
```

**Error triggered on:** `from app.dashboard.dashboard_router import router`

**Solution:** Always use `Set-Content -Encoding UTF8` when writing Python files from PowerShell, or use the project's file tools which write UTF-8 by default.

**Lesson:** On Windows, PowerShell file output defaults are dangerous for Python source files. Always specify encoding explicitly.

---

## 8. APScheduler Job Isolation — DB Session Lifecycle

**When:** Implementing the `daily_recommendation_refresh` job.

**Problem:** The scheduler runs in a background thread separate from the FastAPI request lifecycle. FastAPI's `get_db` dependency (which yields a session and closes it after the request) cannot be used in scheduler jobs.

**Solution:** Each job creates its own `SessionLocal()` session and closes it in a `finally` block:

```python
def daily_recommendation_refresh():
    db = SessionLocal()
    try:
        svc = RecommendationService(db)
        svc.generate(user.id)
    finally:
        db.close()
```

**Lesson:** Scheduler jobs live outside the FastAPI request lifecycle. They must manage their own DB sessions, transactions, and cleanup explicitly.

---

## 9. LangSmith Tracing — Environment Variables Must Be Set Before Import

**When:** Enabling LangSmith tracing at application startup.

**Problem:** LangSmith reads `LANGCHAIN_API_KEY`, `LANGCHAIN_TRACING_V2`, and `LANGCHAIN_PROJECT` from the environment at import time (when `langsmith` is first imported). Setting them after the import had no effect.

**Solution:** Wire the environment variables in the FastAPI `lifespan` startup handler — before any LangChain/LangSmith code runs:

```python
@asynccontextmanager
async def lifespan(app):
    if settings.LANGSMITH_TRACING and settings.LANGSMITH_API_KEY:
        os.environ["LANGCHAIN_API_KEY"] = settings.LANGSMITH_API_KEY
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = settings.LANGSMITH_PROJECT
    yield
```

**Lesson:** LangSmith (and LangChain) read configuration from `os.environ`, not from Python variables. Set them early in the process lifecycle.

---

## 10. Sentence-Transformers Model Load Time on First Request

**When:** Seeding products — the first `POST /admin/products` timed out at 30 seconds.

**Problem:** `EmbeddingService._get_model()` is decorated with `@lru_cache` so the model loads once. But on first call, downloading and loading `BAAI/bge-small-en-v1.5` (~100 MB) takes 20–40 seconds. The default `httpx` timeout (5s) was too short for the first product creation request.

**Solution:** Used an `httpx.Client` with `timeout=120` for the seed script, and the model is now cached after first load:

```python
with httpx.Client(timeout=120) as client:
    for course in COURSES:
        r = client.post(...)
```

**Lesson:** Any heavyweight model should either be pre-loaded at startup (via lifespan) or callers must account for the cold-start latency on the first request.

---

## 11. Login Page Flickering (Redirect Loop)

**When:** After the Jinja2 templates were wired up and the login page was tested in the browser.

**Problem:** The login page had this synchronous check at the top:
```js
if(localStorage.getItem('access_token')) window.location='/dashboard';
```
This ran on every page load — including when the dashboard redirected back to `/login` because the token was expired. The result was a visible flash of the login page followed by an instant redirect, creating an infinite loop when the token was invalid.

Additionally, `tracker.js` was loading on the login page and immediately firing a page-view event with no token, causing a failed API call on every load.

**Solution:**
1. Replaced the synchronous redirect with an async token validation call to `/api/v1/auth/me`. Only redirect if the server confirms the token is valid.
2. Used `window.location.replace('/dashboard')` instead of `window.location = '/dashboard'` — `replace()` doesn't add a history entry, breaking the back-button loop.
3. Excluded `tracker.js` from the login page using Jinja2 conditional: `{% if request.url.path != '/login' %}`.
4. Added `localStorage.removeItem('access_token')` on any `/auth/me` 401 response so stale tokens are always cleared.

**Lesson:** Auth redirect logic must be async (validate before redirecting) and use `location.replace()` to prevent history-based loops. Never load event-tracking scripts on public pages.

---

## 12. Scheduler Card Hidden Inside Conditional Analytics Section

**When:** Testing the admin dashboard scheduler UI.

**Problem:** The APScheduler card was placed inside `#analytics-content` which starts with Bootstrap's `d-none` class and only becomes visible after `loadAnalytics()` succeeds. If analytics loaded slowly or the user wasn't admin, the entire section — including the scheduler card — was never shown.

**Solution:** Moved the scheduler card **outside** `#analytics-content` as a standalone always-visible section. It loads independently via `loadScheduler()` which is called at page init regardless of analytics state.

**Lesson:** UI sections that are independent of each other must not be nested inside conditionally-visible containers.

---

## 13. Auto-Trigger Overwriting High-Confidence Recommendations

**When:** After feedback events were submitted, the dashboard showed `LOW 10%` confidence.

**Problem:** The feedback events (liked/disliked) pushed the user's event count over the 20-event threshold, triggering a new `daily_reco_refresh` workflow run. The LLM model (`minimax/m2-her`) returned empty content for that run, causing the `validate_products` node to fall back to top-N candidates with confidence 0.3. Since `GET /recommendations/me` returns the **latest** row, the high-confidence (0.85) recommendation was effectively overwritten by the low-confidence fallback.

**Solution (short-term):** Manually regenerate via admin dashboard → Run AI Workflow. The system correctly shows the latest row.

**Solution (long-term — future enhancement):** Add a quality gate in `RecommendationService.generate()` — only store a new recommendation if `confidence > current_best OR forced=True`.

**Lesson:** Append-only recommendation rows need a quality gate. The most recent row is not always the best row.

---

## 14. Windows Console Encoding Breaking Python Scripts

**When:** Running scripts with `print()` statements containing Unicode characters (✓, ─, ✗) in PowerShell.

**Problem:** Python 3.12 on Windows uses the system's default `cp1252` codec for stdout, which cannot encode Unicode box-drawing characters or emoji used in test output scripts.

```
UnicodeEncodeError: 'charmap' codec can't encode character '\u2705'
```

**Solution:** Set `PYTHONIOENCODING=utf-8` before running scripts:
```powershell
$env:PYTHONIOENCODING="utf-8"; python scripts/test_mesh_langsmith.py
```
Or replace Unicode characters with ASCII equivalents in script output.

**Lesson:** On Windows, always set `PYTHONIOENCODING=utf-8` for scripts that use non-ASCII characters. Alternatively, avoid emoji and box-drawing characters in Python scripts that run on Windows.

---

## 15. EventResponse Schema Mapping After ORM Rename

**When:** `GET /api/v1/events/me` returned HTTP 500 after the `metadata` → `event_metadata` rename.

**Problem:** The `EventResponse` Pydantic schema had `metadata: dict` which Pydantic tried to read from the ORM object as `.metadata`. After renaming the ORM attribute to `event_metadata`, `.metadata` now resolved to SQLAlchemy's internal `MetaData` object — not a dict.

**Error:**
```
pydantic_core.ValidationError: 1 validation error for EventResponse
metadata
  Input should be a valid dictionary [type=dict_type, input_value=MetaData()]
```

**Solution:** Added `validation_alias` to tell Pydantic to read from `event_metadata` on the ORM object, while keeping `metadata` as the JSON key:
```python
metadata: dict[str, Any] = Field(
    default_factory=dict,
    validation_alias="event_metadata",
)
```

**Lesson:** When renaming ORM attributes, always audit all Pydantic schemas that `model_validate` from that ORM class. `from_attributes=True` reads by Python attribute name, not DB column name.
