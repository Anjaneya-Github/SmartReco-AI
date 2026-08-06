"""scripts/preview_email.py — Generate email HTML preview and open in browser."""
import sys, pathlib, webbrowser, os
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from dotenv import load_dotenv; load_dotenv(".env", override=True)

from app.database.session import SessionLocal
from app.models.user import User
from app.models.recommendation import Recommendation
from app.models.product import Product
from app.services.email_service import EmailService
from sqlalchemy import select
import uuid

db = SessionLocal()
user = db.execute(select(User).where(User.email == "asahu11348@gmail.com")).scalar_one()
rec  = db.execute(
    select(Recommendation)
    .where(Recommendation.user_id == user.id)
    .order_by(Recommendation.generated_at.desc())
    .limit(1)
).scalar_one()

# Re-hydrate product details
pids = [uuid.UUID(p["product_id"]) for p in rec.recommended_products if isinstance(p, dict)]
products_orm = db.execute(select(Product).where(Product.id.in_(pids))).scalars().all()
pm = {str(p.id): p for p in products_orm}

products = []
for item in rec.recommended_products:
    pid = item.get("product_id", "") if isinstance(item, dict) else str(item)
    p = pm.get(pid)
    products.append({
        "title":      p.title      if p else item.get("title", ""),
        "category":   p.category   if p else "",
        "difficulty": p.difficulty if p else "",
    })

db.close()

svc  = EmailService()
html = svc._build_html(
    name       = user.full_name or user.email.split("@")[0],
    summary    = rec.summary,
    products   = products,
    confidence = rec.confidence,
    url        = "http://localhost:8000/dashboard",
)

# Save preview
out = pathlib.Path(__file__).parent / "email_preview.html"
out.write_text(html, encoding="utf-8")
print(f"Email preview saved: {out}")
print(f"User         : {user.email}")
print(f"Confidence   : {rec.confidence:.2f} ({int(rec.confidence*100)}%)")
print(f"Products     : {len(products)}")
print(f"Summary      : {rec.summary[:100]}")

# Open in default browser
webbrowser.open(out.as_uri())
print("\nOpened in browser!")
