"""
scripts/test_mesh_langsmith.py
--------------------------------
Smoke-tests for Mesh API connectivity and LangSmith tracing.

Run from the project root:

    python scripts/test_mesh_langsmith.py

What this tests
~~~~~~~~~~~~~~~
1. Mesh API connectivity
   - Calls /models to verify the key and base_url are reachable.
   - Attempts a chat completion — reports billing vs. auth separately.
   - 402 spend_limit_exceeded = key valid, account needs top-up.
   - 401 unauthorized        = wrong key.

2. LangSmith tracing
   - Verifies the API key can reach smith.langchain.com.
   - Lists recent projects to confirm auth works.
   - Wraps a @traceable function — falls back gracefully if Mesh is out
     of credits (the trace is still submitted with the error captured).
"""

from __future__ import annotations

import os
import sys
import textwrap
import time

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv
load_dotenv(_ROOT / ".env", override=True)

from app.core.config import settings   # noqa: E402

# ------------------------------------------------------------------ #
# Terminal helpers                                                     #
# ------------------------------------------------------------------ #

_GREEN  = "\033[92m"
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_CYAN   = "\033[96m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"

def _pass(label: str, detail: str = "") -> None:
    print(f"  {_GREEN}{_BOLD}✓ PASS{_RESET}  {label}")
    if detail:
        for line in textwrap.wrap(detail, 76):
            print(f"          {line}")

def _warn(label: str, detail: str = "") -> None:
    """Used for billing/quota issues — connectivity confirmed but blocked."""
    print(f"  {_YELLOW}{_BOLD}⚠ WARN{_RESET}  {label}")
    if detail:
        for line in textwrap.wrap(detail, 76):
            print(f"          {line}")

def _fail(label: str, error: str) -> None:
    print(f"  {_RED}{_BOLD}✗ FAIL{_RESET}  {label}")
    for line in str(error).splitlines()[:8]:
        print(f"          {line}")

def _info(key: str, val: str) -> None:
    print(f"  {_CYAN}ℹ{_RESET}  {key:<12} {val}")

def _header(title: str) -> None:
    bar = "─" * 62
    print(f"\n{_BOLD}{bar}{_RESET}")
    print(f"{_BOLD}  {title}{_RESET}")
    print(f"{_BOLD}{bar}{_RESET}")

def _mask(key: str) -> str:
    if len(key) < 8:
        return "(too short)"
    return f"{key[:8]}…{key[-4:]}"


# ------------------------------------------------------------------ #
# Test 1 — Mesh API                                                   #
# ------------------------------------------------------------------ #

def test_mesh_api() -> tuple[bool, bool]:
    """
    Returns (connectivity_ok, completion_ok).
    connectivity_ok = endpoint reachable + key recognised
    completion_ok   = a chat completion actually succeeded
    """
    _header("Test 1 · Mesh API")

    api_key  = settings.LLM_API_KEY
    base_url = settings.LLM_BASE_URL
    model    = settings.LLM_MODEL

    _info("base_url",  base_url  or "(empty)")
    _info("model",     model     or "(empty)")
    _info("api_key",   _mask(api_key))

    if not api_key:
        _fail("Mesh API key", "LLM_API_KEY is empty — set it in .env")
        return False, False
    if not base_url:
        _fail("Mesh base URL", "LLM_BASE_URL is empty — expected https://api.meshapi.ai/v1")
        return False, False

    from openai import OpenAI, AuthenticationError, PermissionDeniedError

    client = OpenAI(api_key=api_key, base_url=base_url)

    # ── Step A: raw GET /models (lightweight — no token spend) ─────
    print()
    try:
        import httpx
        headers = {"Authorization": f"Bearer {api_key}"}
        r = httpx.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=15)

        if r.status_code == 401:
            _fail("Mesh auth failed", f"401 Unauthorized — check LLM_API_KEY")
            return False, False

        if r.status_code in (200, 404):
            # 404 is fine — endpoint exists, just no /models route on this provider
            try:
                data = r.json()
                model_ids = [m.get("id", "?") for m in (data.get("data") or [])[:5]]
                detail = f"returned {len(model_ids)} model(s)" + (
                    f": {', '.join(model_ids)}" if model_ids else ""
                )
            except Exception:
                detail = f"HTTP {r.status_code} — endpoint reachable"
            _pass("Mesh endpoint reachable", detail)
            connectivity_ok = True

        elif r.status_code == 402:
            # Billing error on /models — key is valid, endpoint reachable
            _pass("Mesh endpoint reachable", "HTTP 402 on /models — key recognised, account needs top-up")
            connectivity_ok = True

        else:
            _fail("Mesh /models call", f"HTTP {r.status_code}: {r.text[:200]}")
            return False, False

    except Exception as exc:
        _fail("Mesh /models call", str(exc))
        return False, False

    # ── Step B: chat completion ──────────────────────────────────────
    try:
        t0 = time.perf_counter()
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system",  "content": "Reply in one short sentence."},
                {"role": "user",    "content": "Name one Python ML library."},
            ],
            temperature=0.0,
            max_tokens=60,
        )
        elapsed = time.perf_counter() - t0
        content = (response.choices[0].message.content or "").strip()
        usage   = response.usage

        _pass(
            "Chat completion succeeded",
            f"model={response.model}  "
            f"tokens={usage.total_tokens if usage else 'n/a'}  "
            f"latency={elapsed:.2f}s",
        )
        print(f"\n          {_YELLOW}Reply:{_RESET} {content[:200]}\n")
        return True, True

    except PermissionDeniedError as exc:
        # 402 spend_limit_exceeded — key works, just no credits
        body = str(exc)
        if "spend_limit_exceeded" in body or "402" in body:
            _warn(
                "Chat completion blocked — insufficient balance",
                "Key is valid and endpoint is reachable. "
                "Top up your Mesh account at https://app.meshapi.ai to run completions.",
            )
        else:
            _warn("Chat completion blocked", body[:200])
        return True, False

    except Exception as exc:
        _fail("Chat completion", str(exc))
        return connectivity_ok, False


# ------------------------------------------------------------------ #
# Test 2 — LangSmith                                                  #
# ------------------------------------------------------------------ #

def test_langsmith(mesh_completion_ok: bool) -> bool:
    _header("Test 2 · LangSmith tracing")

    ls_key     = settings.LANGSMITH_API_KEY
    ls_project = settings.LANGSMITH_PROJECT

    _info("project",  ls_project)
    _info("tracing",  str(settings.LANGSMITH_TRACING))
    _info("api_key",  _mask(ls_key))

    if not ls_key:
        _fail("LangSmith API key", "LANGSMITH_API_KEY is empty — set it in .env")
        return False

    # Configure env vars that the LangSmith SDK reads
    os.environ["LANGCHAIN_API_KEY"]    = ls_key
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"]    = ls_project

    print()

    # ── Step A: verify auth by listing projects ──────────────────────
    try:
        from langsmith import Client as LSClient
        ls_client = LSClient(api_key=ls_key)
        projects  = list(ls_client.list_projects())
        names     = [p.name for p in projects[:5]]
        _pass(
            "LangSmith auth OK",
            f"reachable — {len(projects)} project(s) found: {', '.join(names) or '(none yet)'}",
        )
    except Exception as exc:
        _fail("LangSmith auth", str(exc))
        return False

    # ── Step B: submit a trace ───────────────────────────────────────
    try:
        from langsmith import traceable

        @traceable(name="SmartReco-AI/smoke-test", run_type="chain")
        def _smoke_run(prompt: str) -> str:
            """
            Wraps either a real Mesh call (if credits available) or a
            local echo so we can always submit a trace regardless of
            Mesh account balance.
            """
            if mesh_completion_ok:
                from openai import OpenAI
                c = OpenAI(
                    api_key=settings.LLM_API_KEY,
                    base_url=settings.LLM_BASE_URL or None,
                )
                resp = c.chat.completions.create(
                    model=settings.LLM_MODEL,
                    messages=[
                        {"role": "system", "content": "Be concise."},
                        {"role": "user",   "content": prompt},
                    ],
                    temperature=0.0,
                    max_tokens=40,
                )
                return resp.choices[0].message.content or ""
            else:
                # Mesh has no credits — return a local echo so the trace
                # is still submitted to LangSmith with the input/output recorded
                return f"[local-echo] prompt received: {prompt}"

        t0    = time.perf_counter()
        reply = _smoke_run("What is collaborative filtering? One sentence.")
        elapsed = time.perf_counter() - t0

        source = "Mesh" if mesh_completion_ok else "local echo (Mesh credits exhausted)"
        _pass(
            f"Trace submitted to LangSmith  [{source}]",
            f"project={ls_project}  latency={elapsed:.2f}s",
        )
        print(f"\n          {_YELLOW}Output:{_RESET} {reply.strip()[:200]}")
        print(
            f"\n          {_CYAN}View traces:{_RESET} "
            f"https://smith.langchain.com/projects/{ls_project}\n"
        )
        return True

    except Exception as exc:
        _fail("LangSmith trace submission", str(exc))
        return False


# ------------------------------------------------------------------ #
# Main                                                                #
# ------------------------------------------------------------------ #

def main() -> None:
    print(f"\n{_BOLD}SmartReco-AI — Mesh API + LangSmith smoke test{_RESET}")

    mesh_conn_ok, mesh_completion_ok = test_mesh_api()
    langsmith_ok = test_langsmith(mesh_completion_ok)

    _header("Summary")
    rows = [
        ("Mesh endpoint reachable",       mesh_conn_ok),
        ("Mesh chat completion",           mesh_completion_ok),
        ("LangSmith auth + trace",         langsmith_ok),
    ]
    for label, ok in rows:
        icon = f"{_GREEN}✓{_RESET}" if ok else f"{_YELLOW}⚠{_RESET}"
        print(f"  {icon}  {label}")

    critical_pass = mesh_conn_ok and langsmith_ok
    colour = _GREEN if critical_pass else _RED
    status = "READY" if critical_pass else "NEEDS ATTENTION"
    print(f"\n  {colour}{_BOLD}Status: {status}{_RESET}")

    if not mesh_completion_ok and mesh_conn_ok:
        print(
            f"\n  {_YELLOW}Note:{_RESET} Mesh key is valid but account balance is zero.\n"
            "  Top up at https://app.meshapi.ai — completions will work immediately.\n"
        )
    print()
    sys.exit(0 if critical_pass else 1)


if __name__ == "__main__":
    main()
