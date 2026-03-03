import json
import os
import time
import requests

BASE = os.environ.get("VERICYCLE_BASE_URL", "http://127.0.0.1:5001")
EMAIL = "test@gmail.com"
PASSWORD = "Test123!"

s = requests.Session()

r = s.post(
    f"{BASE}/login",
    data={"email": EMAIL, "password": PASSWORD},
    allow_redirects=False,
    timeout=20,
)
if r.status_code not in (302, 303):
    raise RuntimeError(f"login failed status={r.status_code}")
print(f"login_redirect={r.headers.get('Location')}")

cfg = s.get(f"{BASE}/api/config", timeout=20).json()

created = s.post(f"{BASE}/api/simulate-deposit", timeout=30)
if created.status_code != 200:
    raise RuntimeError(f"deposit failed status={created.status_code} body={created.text[:300]}")
try:
    created_payload = created.json()
except Exception:
    raise RuntimeError(f"deposit non-json response status={created.status_code} body={created.text[:400]}")

activity_id = created_payload.get("activity_id")

deadline = time.time() + 180
final_row = None
while time.time() < deadline:
    rows = s.get(f"{BASE}/api/admin/activities", timeout=30).json()
    row = next((x for x in rows if int(x.get("id", -1)) == int(activity_id)), None)
    if row:
        stage = (row.get("stage") or "").lower()
        if stage in ("rewarded", "attested", "failed"):
            final_row = row
            break
    time.sleep(2)

if final_row is None:
    rows = s.get(f"{BASE}/api/admin/activities", timeout=30).json()
    final_row = next((x for x in rows if int(x.get("id", -1)) == int(activity_id)), None)

out = {
    "base": BASE,
    "account": EMAIL,
    "config": cfg,
    "activity_id": activity_id,
    "row": {
        "id": final_row.get("id") if final_row else None,
        "stage": final_row.get("stage") if final_row else None,
        "logbook_status": final_row.get("logbook_status") if final_row else None,
        "hedera_tx_id": final_row.get("hedera_tx_id") if final_row else None,
        "reward_status": final_row.get("reward_status") if final_row else None,
        "reward_tx_id": final_row.get("reward_tx_id") if final_row else None,
    },
}
print(json.dumps(out, indent=2))
