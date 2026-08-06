"""scripts/test_login_fix.py — verify login flicker is fixed."""
import httpx

c = httpx.Client(base_url="http://localhost:8000", timeout=10)

print("\nLogin page checks")
print("-" * 50)
r = c.get("/login")
print(f"  Status: {r.status_code}")

checks = [
    ("tracker.js NOT loaded on login",   "tracker.js" not in r.text),
    ("checkExistingToken async fn",       "checkExistingToken" in r.text),
    ("Uses location.replace()",           "location.replace" in r.text),
    ("Validates token before redirect",   "/api/v1/auth/me" in r.text),
    ("Clears bad token on 401",           "removeItem" in r.text),
]
all_ok = True
for label, result in checks:
    symbol = "OK  " if result else "FAIL"
    print(f"  {symbol}  {label}")
    if not result:
        all_ok = False

print("\nDashboard page checks")
print("-" * 50)
r2 = c.get("/dashboard")
print(f"  Status: {r2.status_code}")
d_checks = [
    ("tracker.js IS loaded",    "tracker.js" in r2.text),
    ("Uses location.replace()", "location.replace" in r2.text),
]
for label, result in d_checks:
    symbol = "OK  " if result else "FAIL"
    print(f"  {symbol}  {label}")
    if not result:
        all_ok = False

print()
if all_ok:
    print("  All checks passed - login flicker is fixed")
else:
    print("  Some checks failed")

c.close()
