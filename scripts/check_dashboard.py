"""scripts/check_dashboard.py — quick dashboard state check."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
import httpx

c = httpx.Client(base_url="http://localhost:8000", timeout=15)

r1 = c.post("/api/v1/auth/login", json={"email":"asahu11348@gmail.com","password":"Demo@1234"})
token = r1.json()["access_token"]

r2 = c.get("/api/v1/dashboard", headers={"Authorization":"Bearer "+token})
d = r2.json()

print("Dashboard status :", r2.status_code)
print("Confidence score :", d["confidence_score"], "(", d["confidence_label"].upper(), ")")
print("Has recommendation:", d["has_recommendation"])
print("AI model         :", d["ai_model"])
print("Generated at     :", str(d.get("generated_at",""))[:19])
print("Products         :", len(d["recommended_products"]))
print("Cache hit        :", d["cache_hit"])
print()
print("Recommended courses:")
for i, p in enumerate(d["recommended_products"], 1):
    title = p.get("title","?")
    diff  = p.get("difficulty","?")
    cat   = p.get("category","?")
    print(f"  {i}. {title} ({diff}) [{cat}]")

print()
print("Top searches:", d.get("top_searches",[])[:3])
print("Learning lvl :", d.get("learning_level"))
print("Engagement   :", round(d.get("engagement_score",0)*100), "%")

c.close()
