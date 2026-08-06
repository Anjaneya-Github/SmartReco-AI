"""scripts/test_scheduler_ui.py — Verify scheduler dashboard section and API."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import httpx

BASE  = "http://localhost:8000"
ADMIN = {"email": "admin@smartreco.ai", "password": "Admin1234!"}

GRN, RED, YLW, BLD, RST = "\033[92m", "\033[91m", "\033[93m", "\033[1m", "\033[0m"

def ok(msg, note=""):
    print(f"  {GRN}OK{RST}  {msg}" + (f"  {YLW}-> {note}{RST}" if note else ""))

def fail(msg, note=""):
    print(f"  {RED}FAIL{RST}  {msg}" + (f"  {YLW}-> {note}{RST}" if note else ""))
    sys.exit(1)

def section(title):
    print(f"\n{BLD}{'─'*60}{RST}")
    print(f"{BLD}  {title}{RST}")
    print(f"{BLD}{'─'*60}{RST}")

c = httpx.Client(base_url=BASE, timeout=30)

# Login
section("1 · Login as admin")
r = c.post("/api/v1/auth/login", json=ADMIN)
if r.status_code != 200:
    fail("Admin login", r.text[:100])
token = r.json()["access_token"]
ah = {"Authorization": f"Bearer {token}"}
ok("Admin login", "token acquired")

# Check HTML page contains scheduler section
section("2 · Admin dashboard HTML")
r = c.get("/admin/dashboard")
if r.status_code != 200:
    fail("Page load", str(r.status_code))

checks = ["APScheduler", "Run Now", "loadScheduler", "runJob", "sched-tbody", "sched-status-badge"]
for keyword in checks:
    if keyword in r.text:
        ok(f"HTML contains '{keyword}'")
    else:
        fail(f"HTML missing '{keyword}'")

# Scheduler status API
section("3 · GET /api/v1/admin/scheduler/status")
r = c.get("/api/v1/admin/scheduler/status", headers=ah)
if r.status_code != 200:
    fail("Status endpoint", str(r.status_code))

d = r.json()
ok("Endpoint reachable", f"running={d['scheduler_running']}")
if not d["scheduler_running"]:
    fail("Scheduler not running")
ok("Scheduler is running")

if d["registered_jobs"] != 3:
    fail("Job count", str(d["registered_jobs"]))
ok("3 jobs registered")

print()
print(f"  {'Job ID':<25} {'Name':<35} {'Next Run':<22} Status")
print(f"  {'-'*24} {'-'*34} {'-'*21} ------")
for job in d["jobs"]:
    nxt = (job["next_run_time"] or "none")[:19]
    status = job["last_status"] or "never"
    print(f"  {job['id']:<25} {job['name']:<35} {nxt:<22} {status}")
    if job["next_run_time"] is None:
        fail(f"Job {job['id']} has no next_run_time")

# Run cache_cleanup
section("4 · Run cache_cleanup immediately")
r = c.post("/api/v1/admin/scheduler/run", json={"job_id": "cache_cleanup"}, headers=ah)
if r.status_code != 202:
    fail("Run cache_cleanup", r.text[:100])
d = r.json()
ok(f"cache_cleanup triggered", f"status={d['status']}  at={d['triggered_at'][:19]}")

# Run event_cleanup
section("5 · Run event_cleanup immediately")
r = c.post("/api/v1/admin/scheduler/run", json={"job_id": "event_cleanup"}, headers=ah)
if r.status_code != 202:
    fail("Run event_cleanup", r.text[:100])
d = r.json()
ok(f"event_cleanup triggered", f"status={d['status']}  at={d['triggered_at'][:19]}")

# Run daily_reco_refresh
section("6 · Run daily_reco_refresh immediately")
print(f"  {YLW}Note: this runs the LangGraph workflow for all active users — may take a moment{RST}")
r = c.post("/api/v1/admin/scheduler/run", json={"job_id": "daily_reco_refresh"}, headers=ah, timeout=120)
if r.status_code != 202:
    fail("Run daily_reco_refresh", r.text[:100])
d = r.json()
ok(f"daily_reco_refresh triggered", f"status={d['status']}  at={d['triggered_at'][:19]}")

# Verify stats updated after runs
section("7 · Verify updated stats")
r = c.get("/api/v1/admin/scheduler/status", headers=ah)
d = r.json()
print()
for job in d["jobs"]:
    last_run = (job["last_run"] or "never")[:19]
    dur = f"{job['last_duration_s']:.2f}s" if job["last_duration_s"] else "-"
    status = job["last_status"] or "never"
    color = GRN if status in ("success", "triggered", "skipped_no_redis") else RED
    detail = ""
    if job["id"] == "daily_reco_refresh" and job.get("recommendations_generated") is not None:
        detail = f"  recs_generated={job['recommendations_generated']}"
    if job["id"] == "event_cleanup" and job.get("events_archived") is not None:
        detail = f"  archived={job['events_archived']}"
    if job["id"] == "cache_cleanup" and job.get("keys_found") is not None:
        detail = f"  redis_keys={job['keys_found']}"
    print(f"  {color}{job['id']:<25}{RST}  last_run={last_run}  dur={dur:<8}  status={status}{detail}")
    if job["last_run"] is None:
        fail(f"{job['id']} last_run still None after manual trigger")
    ok(f"{job['id']} stats updated")

# Invalid job
section("8 · Invalid job returns 400")
r = c.post("/api/v1/admin/scheduler/run", json={"job_id": "fake_job"}, headers=ah)
if r.status_code != 400:
    fail("Invalid job", str(r.status_code))
ok("Invalid job rejected with 400", r.json().get("detail", "")[:60])

print(f"\n  {GRN}{BLD}All scheduler tests passed!{RST}\n")
print(f"  Open {YLW}http://localhost:8000/admin/dashboard{RST} and use the")
print(f"  {BLD}APScheduler{RST} section to run jobs from the browser.\n")

c.close()
