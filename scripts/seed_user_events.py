"""
scripts/seed_user_events.py
-----------------------------
Seed realistic behavioral events for a user directly via DB,
then trigger an AI recommendation via the admin API.

Usage:
    python scripts/seed_user_events.py <user_email>

Defaults to asahu11348@gmail.com if no argument given.
"""
from __future__ import annotations
import sys, pathlib, uuid
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(".env", override=True)

import httpx
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from app.database.session import SessionLocal
from app.models.event import EventType, UserEvent
from app.models.product import Product
from app.models.user import User
from app.repositories.event_repository import EventRepository

BASE = "http://localhost:8000"
ADMIN_EMAIL    = "admin@smartreco.ai"
ADMIN_PASSWORD = "Admin1234!"

TARGET_EMAIL = sys.argv[1] if len(sys.argv) > 1 else "asahu11348@gmail.com"


def get_admin_token() -> str:
    r = httpx.post(f"{BASE}/api/v1/auth/login",
                   json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=10)
    r.raise_for_status()
    return r.json()["access_token"]


def seed_events(user_id: uuid.UUID, products: list[Product]) -> None:
    db = SessionLocal()
    repo = EventRepository(db)
    now = datetime.now(tz=timezone.utc)

    # Pick ML/AI-focused products to simulate an ML learner
    ml_products  = [p for p in products if p.category in ("machine-learning", "deep-learning")]
    nlp_products = [p for p in products if p.category == "nlp"]
    gen_products = [p for p in products if p.category == "generative-ai"]
    all_products = products

    def ts(minutes_ago: int) -> datetime:
        return now - timedelta(minutes=minutes_ago)

    session = f"seed-{uuid.uuid4().hex[:8]}"

    # Build a realistic event stream — ML learner browsing and engaging
    rows = []

    # 1. Series of views (browsing the catalogue)
    for i, p in enumerate(all_products[:8]):
        rows.append({"user_id": user_id, "session_id": session,
                     "event_type": EventType.VIEW, "product_id": p.id,
                     "search_query": None, "metadata": {"position": i},
                     "created_at": ts(120 - i * 5)})

    # 2. Searches — clear ML interest signal
    for i, q in enumerate(["machine learning python", "deep learning pytorch",
                            "nlp transformers", "machine learning python"]):  # repeated!
        rows.append({"user_id": user_id, "session_id": session,
                     "event_type": EventType.SEARCH, "product_id": None,
                     "search_query": q, "metadata": {},
                     "created_at": ts(90 - i * 8)})

    # 3. Clicks on ML products
    for i, p in enumerate((ml_products + nlp_products)[:5]):
        rows.append({"user_id": user_id, "session_id": session,
                     "event_type": EventType.CLICK, "product_id": p.id,
                     "search_query": None, "metadata": {},
                     "created_at": ts(60 - i * 4)})

    # 4. Wishlist a deep learning course
    if ml_products:
        rows.append({"user_id": user_id, "session_id": session,
                     "event_type": EventType.WISHLIST, "product_id": ml_products[0].id,
                     "search_query": None, "metadata": {},
                     "created_at": ts(30)})

    # 5. A purchase — highest intent signal
    if gen_products:
        rows.append({"user_id": user_id, "session_id": session,
                     "event_type": EventType.PURCHASE, "product_id": gen_products[0].id,
                     "search_query": None, "metadata": {"price": 59.99},
                     "created_at": ts(15)})

    # 6. Rating
    if ml_products:
        rows.append({"user_id": user_id, "session_id": session,
                     "event_type": EventType.RATING, "product_id": ml_products[0].id,
                     "search_query": None, "metadata": {"score": 5},
                     "created_at": ts(10)})

    # Inject timestamps directly (bypass the API to set exact times)
    now_utc = datetime.now(tz=timezone.utc)
    enriched = []
    for row in rows:
        created_at = row.pop("created_at", now_utc)
        eid = uuid.uuid4()
        enriched.append({
            "id": eid,
            "user_id": row["user_id"],
            "session_id": row["session_id"],
            "event_type": row["event_type"],
            "product_id": row.get("product_id"),
            "search_query": row.get("search_query"),
            "metadata": row.get("metadata", {}),
            "created_at": created_at,
        })

    db.bulk_insert_mappings(UserEvent, enriched)  # type: ignore
    db.commit()
    print(f"  Seeded {len(enriched)} events for {TARGET_EMAIL}")
    db.close()


def trigger_recommendation(user_id: str, token: str) -> None:
    print("  Triggering AI recommendation workflow…")
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    with httpx.Client(timeout=120) as client:
        r = client.post(f"{BASE}/api/v1/recommendations/generate",
                        json={"user_id": user_id, "max_products": 20},
                        headers=headers)
    if r.status_code == 201:
        d = r.json()
        print(f"  Recommendation generated!")
        print(f"    confidence  : {d.get('confidence_score', d.get('confidence', 0)):.2f}")
        print(f"    products    : {len(d.get('recommended_products', []))}")
        if d.get('summary'):
            print(f"    summary     : {d['summary'][:120]}")
    else:
        print(f"  Reco failed [{r.status_code}]: {r.text[:200]}")


def main() -> None:
    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.email == TARGET_EMAIL)).scalar_one_or_none()
        if not user:
            print(f"User '{TARGET_EMAIL}' not found in DB.")
            print("Available users:")
            for u in db.execute(select(User)).scalars().all():
                print(f"  {u.email} ({u.role.value})")
            sys.exit(1)

        products = db.execute(select(Product).where(Product.is_active == True)).scalars().all()
        if not products:
            print("No products found. Run seed_products.py first.")
            sys.exit(1)

        print(f"\nSeeding events for: {user.email}  (id={user.id})")
        print(f"Using {len(products)} products from catalogue\n")

        seed_events(user.id, list(products))

        admin_token = get_admin_token()
        trigger_recommendation(str(user.id), admin_token)

        print(f"\nDone! Refresh the dashboard at http://localhost:8000/dashboard\n")
    finally:
        db.close()


if __name__ == "__main__":
    main()
