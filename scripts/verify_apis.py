"""
scripts/verify_apis.py
=======================
End-to-end manual verification of all SmartReco AI APIs.

Runs the FastAPI app in-process via ASGI transport — no external
server process needed.  Uses the real PostgreSQL and Qdrant instances
configured in .env.

Endpoints covered
-----------------
Authentication
  POST /api/v1/auth/register
  POST /api/v1/auth/login
  GET  /api/v1/auth/me

Products (admin — dual-write PostgreSQL + Qdrant)
  POST   /api/v1/admin/products
  GET    /api/v1/products
  GET    /api/v1/products/{id}
  PUT    /api/v1/admin/products/{id}
  DELETE /api/v1/admin/products/{id}

Storage verification
  PostgreSQL: row exists / was updated / was deleted
  Qdrant:     point exists / payload correct / was deleted

Usage
-----
    python scripts/verify_apis.py
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

# ── Project root on sys.path ──────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio

import httpx
import psycopg2
from asgi_lifespan import LifespanManager
from qdrant_client import QdrantClient

from app.main import app
from app.core.config import settings
from app.services.vector_service import _get_qdrant_client

# ── ANSI colour helpers ───────────────────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

_pass = 0
_fail = 0


def _ok(label: str, detail: str = "") -> None:
    global _pass
    _pass += 1
    suffix = f"  {YELLOW}{detail}{RESET}" if detail else ""
    print(f"  {GREEN}✓{RESET}  {label}{suffix}")


def _fail_check(label: str, detail: str = "") -> None:
    global _fail
    _fail += 1
    suffix = f"  {RED}{detail}{RESET}" if detail else ""
    print(f"  {RED}✗{RESET}  {label}{suffix}")


def section(title: str) -> None:
    bar = "─" * 58
    print(f"\n{BOLD}{CYAN}{bar}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{bar}{RESET}")


def check(label: str, got: object, expected: object, show: bool = True) -> None:
    detail = repr(got)[:70] if show else ""
    if got == expected:
        _ok(label, detail)
    else:
        _fail_check(label, f"expected {repr(expected)!r}, got {repr(got)!r}")


def has_key(label: str, key: str, obj: dict) -> None:
    if key in obj:
        _ok(label, repr(obj[key])[:60])
    else:
        _fail_check(label, f"key '{key}' missing")


# ── PostgreSQL direct-query helpers ──────────────────────────────────────────

def _pg() -> psycopg2.extensions.connection:
    u = urlparse(settings.DATABASE_URL)
    return psycopg2.connect(
        host=u.hostname, port=u.port or 5432,
        dbname=u.path.lstrip("/"),
        user=u.username, password=u.password,
        connect_timeout=5,
    )


def pg_get_product(product_id: str) -> dict | None:
    with _pg() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, category, difficulty, price, is_active "
            "FROM products WHERE id = %s",
            (product_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "title": row[1],
        "category": row[2],
        "difficulty": row[3],
        "price": float(row[4]) if row[4] is not None else None,
        "is_active": row[5],
    }


def pg_product_exists(product_id: str) -> bool:
    with _pg() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM products WHERE id = %s", (product_id,))
        return cur.fetchone() is not None


# ── Qdrant direct-query helpers ───────────────────────────────────────────────

def _qdrant() -> QdrantClient:
    return _get_qdrant_client()


def qdrant_get_point(product_id: str) -> dict | None:
    try:
        results = _qdrant().retrieve(
            collection_name=settings.QDRANT_COLLECTION,
            ids=[product_id],
            with_vectors=True,
            with_payload=True,
        )
        if not results:
            return None
        p = results[0]
        return {
            "id": p.id,
            "payload": p.payload or {},
            "vector_dim": len(p.vector) if p.vector else 0,
        }
    except Exception as exc:
        print(f"  {RED}[qdrant_get_point error] {exc}{RESET}")
        return None


def qdrant_point_exists(product_id: str) -> bool:
    return qdrant_get_point(product_id) is not None


# ── Main test coroutine ───────────────────────────────────────────────────────

async def run() -> None:
    transport = httpx.ASGITransport(app=app)

    async with LifespanManager(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            timeout=120.0,
        ) as client:

            # ============================================================
            section("1. AUTHENTICATION")
            # ============================================================

            # 1-a  Register a new user
            email = f"tester_{uuid.uuid4().hex[:8]}@example.com"
            reg = await client.post("/api/v1/auth/register", json={
                "email": email,
                "password": "Test1234!",
                "full_name": "API Tester",
            })
            check("POST /auth/register → 201", reg.status_code, 201)
            rb = reg.json()
            has_key("  response.id",    "id",    rb)
            has_key("  response.email", "email", rb)
            check("  role = user",      rb.get("role"), "user")
            check("  no hashed_password in body",
                  "hashed_password" not in rb, True, show=False)

            # 1-b  Duplicate email → 409
            dup = await client.post("/api/v1/auth/register", json={
                "email": email, "password": "Test1234!",
            })
            check("POST /auth/register duplicate → 409", dup.status_code, 409)

            # 1-c  Admin login (seeded by seed_admin.py)
            login = await client.post("/api/v1/auth/login", json={
                "email": "admin@smartreco.ai",
                "password": "Admin1234!",
            })
            check("POST /auth/login (admin) → 200", login.status_code, 200)
            lb = login.json()
            has_key("  access_token",  "access_token", lb)
            check("  token_type = bearer", lb.get("token_type"), "bearer")
            admin_token = lb["access_token"]

            # 1-d  Wrong password → 401
            bad = await client.post("/api/v1/auth/login", json={
                "email": "admin@smartreco.ai", "password": "WrongPass99",
            })
            check("POST /auth/login wrong pw → 401", bad.status_code, 401)

            # 1-e  GET /me authenticated
            me = await client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            check("GET  /auth/me → 200", me.status_code, 200)
            check("  email = admin@smartreco.ai",
                  me.json().get("email"), "admin@smartreco.ai")
            check("  role = admin", me.json().get("role"), "admin")

            # 1-f  GET /me unauthenticated → 401
            unauth_me = await client.get("/api/v1/auth/me")
            check("GET  /auth/me no token → 401", unauth_me.status_code, 401)

            # ============================================================
            section("2. CREATE PRODUCT  (dual-write)")
            # ============================================================

            product_payload = {
                "title":       "Python for Machine Learning",
                "description": "Covers scikit-learn, pandas, and numpy in depth.",
                "category":    "machine-learning",
                "difficulty":  "beginner",
                "duration":    420,
                "price":       49.99,
                "tags":        ["python", "ml", "scikit-learn", "pandas"],
                "is_active":   True,
            }

            create = await client.post(
                "/api/v1/admin/products",
                json=product_payload,
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            check("POST /admin/products → 201", create.status_code, 201)
            prod = create.json()
            has_key("  response.id",         "id",         prod)
            has_key("  response.created_at", "created_at", prod)
            check("  title",      prod.get("title"),      product_payload["title"])
            check("  category",   prod.get("category"),   "machine-learning")
            check("  difficulty", prod.get("difficulty"), "beginner")
            check("  price",      prod.get("price"),      49.99)
            check("  is_active",  prod.get("is_active"),  True)

            pid = prod["id"]
            print(f"\n  {YELLOW}▸ Product ID: {pid}{RESET}\n")

            # ── PostgreSQL verification ──────────────────────────────────
            pg = pg_get_product(pid)
            if pg:
                _ok("  PostgreSQL row exists",
                    f"title={pg['title']!r}  active={pg['is_active']}")
                check("  PG title", pg["title"], product_payload["title"], show=False)
                check("  PG is_active", pg["is_active"], True, show=False)
            else:
                _fail_check("  PostgreSQL row MISSING", pid)

            # ── Qdrant verification ──────────────────────────────────────
            qp = qdrant_get_point(pid)
            if qp:
                _ok("  Qdrant point exists",
                    f"dim={qp['vector_dim']}  "
                    f"payload_keys={list(qp['payload'].keys())}")
                check("  vector dim = 384",
                      qp["vector_dim"], settings.EMBEDDING_DIMENSION)
                check("  Qdrant payload title",
                      qp["payload"].get("title"),
                      product_payload["title"], show=False)
                check("  Qdrant payload category",
                      qp["payload"].get("category"),
                      "machine-learning", show=False)
            else:
                _fail_check("  Qdrant point MISSING", pid)

            # ── Auth guards ──────────────────────────────────────────────
            no_tok = await client.post("/api/v1/admin/products",
                                       json=product_payload)
            check("POST /admin/products no token → 401", no_tok.status_code, 401)

            user_login = await client.post("/api/v1/auth/login", json={
                "email": email, "password": "Test1234!",
            })
            user_token = user_login.json().get("access_token", "")
            forbidden = await client.post(
                "/api/v1/admin/products",
                json=product_payload,
                headers={"Authorization": f"Bearer {user_token}"},
            )
            check("POST /admin/products user token → 403", forbidden.status_code, 403)

            # ============================================================
            section("3. LIST & GET PRODUCTS  (public)")
            # ============================================================

            lst = await client.get("/api/v1/products")
            check("GET  /products → 200", lst.status_code, 200)
            lb2 = lst.json()
            has_key("  has items", "items", lb2)
            has_key("  has total", "total", lb2)
            has_key("  has pages", "pages", lb2)
            check("  total >= 1", lb2.get("total", 0) >= 1, True, show=False)
            found = any(p["id"] == pid for p in lb2.get("items", []))
            (_ok if found else _fail_check)("  new product in listing")

            get1 = await client.get(f"/api/v1/products/{pid}")
            check("GET  /products/{id} → 200", get1.status_code, 200)
            check("  id matches", get1.json().get("id"), pid)

            get404 = await client.get(f"/api/v1/products/{uuid.uuid4()}")
            check("GET  /products/{bad_id} → 404", get404.status_code, 404)

            # ============================================================
            section("4. UPDATE PRODUCT  (dual-write)")
            # ============================================================

            update_payload = {
                "title":       "Python for Machine Learning — Updated",
                "description": "Advanced topics: deep learning, PyTorch, and MLOps.",
                "category":    "machine-learning",
                "difficulty":  "intermediate",
                "duration":    600,
                "price":       79.99,
                "tags":        ["python", "ml", "deep-learning", "pytorch"],
                "is_active":   True,
            }

            upd = await client.put(
                f"/api/v1/admin/products/{pid}",
                json=update_payload,
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            check("PUT  /admin/products/{id} → 200", upd.status_code, 200)
            upd_body = upd.json()
            check("  title updated",
                  upd_body.get("title"), update_payload["title"])
            check("  difficulty updated",
                  upd_body.get("difficulty"), "intermediate")
            check("  price updated",
                  upd_body.get("price"), 79.99)

            # PostgreSQL after update
            pg2 = pg_get_product(pid)
            if pg2:
                _ok("  PostgreSQL row updated",
                    f"title={pg2['title']!r}")
                check("  PG title updated",
                      pg2["title"], update_payload["title"], show=False)
            else:
                _fail_check("  PostgreSQL row MISSING after update")

            # Qdrant after update
            qp2 = qdrant_get_point(pid)
            if qp2:
                _ok("  Qdrant point present after update",
                    f"dim={qp2['vector_dim']}")
                check("  Qdrant title updated",
                      qp2["payload"].get("title"),
                      update_payload["title"], show=False)
                check("  Qdrant difficulty updated",
                      qp2["payload"].get("difficulty"),
                      "intermediate", show=False)
            else:
                _fail_check("  Qdrant point MISSING after update")

            # ============================================================
            section("5. DELETE PRODUCT  (dual-write)")
            # ============================================================

            delr = await client.delete(
                f"/api/v1/admin/products/{pid}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            check("DELETE /admin/products/{id} → 204", delr.status_code, 204)

            # PostgreSQL after delete
            if not pg_product_exists(pid):
                _ok("  PostgreSQL row deleted")
            else:
                _fail_check("  PostgreSQL row STILL EXISTS after delete")

            # Qdrant after delete
            if not qdrant_point_exists(pid):
                _ok("  Qdrant point deleted")
            else:
                _fail_check("  Qdrant point STILL EXISTS after delete")

            # GET deleted → 404
            del404 = await client.get(f"/api/v1/products/{pid}")
            check("GET  /products/{deleted} → 404", del404.status_code, 404)

            # DELETE non-existent → 404
            del_miss = await client.delete(
                f"/api/v1/admin/products/{uuid.uuid4()}",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            check("DELETE non-existent → 404", del_miss.status_code, 404)

            # ============================================================
            section("SUMMARY")
            # ============================================================
            total = _pass + _fail
            colour = GREEN if _fail == 0 else RED
            print(f"\n  {colour}{BOLD}{_pass}/{total} checks passed{RESET}")
            if _fail:
                print(f"  {RED}{_fail} check(s) FAILED ✗{RESET}\n")
                sys.exit(1)
            else:
                print(f"  {GREEN}All checks passed ✓{RESET}\n")


if __name__ == "__main__":
    asyncio.run(run())
