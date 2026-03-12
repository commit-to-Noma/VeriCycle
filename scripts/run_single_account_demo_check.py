#!/usr/bin/env python
import json
import os
import sys
import time
from typing import Any, NoReturn

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)


def fail(msg: str) -> NoReturn:
    raise RuntimeError(msg)


def run_internal_mode() -> dict:
    from app import app, db
    from models import Activity, User

    with app.app_context():
        collector = User.query.filter_by(role="collector").order_by(User.id.asc()).first()
        if not collector:
            fail("No collector user found in database")
        collector_id = int(collector.id)

        with app.test_client() as client:
            with client.session_transaction() as sess:
                sess["_user_id"] = str(collector_id)
                sess["_fresh"] = True

            cfg_res = client.get("/api/config")
            if cfg_res.status_code != 200:
                fail(f"/api/config failed status={cfg_res.status_code}")
            cfg = cfg_res.get_json(silent=True) or {}

            created = client.post("/api/simulate-deposit")
            if created.status_code != 200:
                fail(f"deposit failed status={created.status_code}")

            created_payload: Any = created.get_json(silent=True)
            if not isinstance(created_payload, dict):
                fail("deposit returned non-JSON payload")

            activity_id = created_payload.get("activity_id")
            if not activity_id:
                fail("deposit did not return activity_id")
            activity_id = int(activity_id)

            deadline = time.time() + 180
            final_row = None
            while time.time() < deadline:
                db.session.expire_all()
                row = db.session.get(Activity, activity_id)
                if row:
                    stage = (row.pipeline_stage or "").lower()
                    if stage in ("rewarded", "attested", "failed"):
                        final_row = row
                        break
                time.sleep(2)

            if final_row is None:
                db.session.expire_all()
                final_row = db.session.get(Activity, activity_id)

            return {
                "mode": "internal",
                "account": collector.email,
                "config": cfg,
                "activity_id": activity_id,
                "row": {
                    "id": getattr(final_row, "id", None) if final_row else None,
                    "stage": getattr(final_row, "pipeline_stage", None) if final_row else None,
                    "logbook_status": getattr(final_row, "logbook_status", None) if final_row else None,
                    "hedera_tx_id": getattr(final_row, "hedera_tx_id", None) if final_row else None,
                    "reward_status": getattr(final_row, "reward_status", None) if final_row else None,
                    "reward_tx_id": getattr(final_row, "reward_tx_id", None) if final_row else None,
                },
            }


def run_http_mode() -> dict:
    import requests
    from requests import exceptions as req_exc

    base = os.environ.get("VERICYCLE_BASE_URL", "http://127.0.0.1:5000")
    email = os.environ.get("VERICYCLE_CHECK_EMAIL", "")
    password = os.environ.get("VERICYCLE_CHECK_PASSWORD", "")

    s = requests.Session()

    try:
        r = s.get(f"{base}/api/config", timeout=10)
        if r.status_code != 200:
            fail(f"server responded with status={r.status_code} on /api/config")
    except req_exc.RequestException as exc:
        fail(f"cannot connect to {base}. Start the app first (python app.py). Details: {exc}")

    def can_read_dashboard_data() -> bool:
        try:
            res = s.get(f"{base}/api/my-dashboard-data", timeout=15)
            if res.status_code != 200:
                return False
            payload = res.json()
            return isinstance(payload, dict) and "timeline" in payload
        except Exception:
            return False

    def try_login(candidate_email: str, candidate_password: str) -> bool:
        try:
            res = s.post(
                f"{base}/login",
                data={"email": candidate_email, "password": candidate_password},
                allow_redirects=False,
                timeout=20,
            )
        except req_exc.RequestException:
            return False

        if res.status_code not in (302, 303):
            return False

        return can_read_dashboard_data()

    credential_candidates = []
    if email and password:
        credential_candidates.append((email, password))

    credential_candidates.extend([
        ("test@gmail.com", "Test123!"),
        ("demo@vericycle.com", "H3dera!2025"),
        ("admin@vericycle.com", "Admin123!"),
        ("mpact@vericycle.com", "Centerh3dera!"),
    ])

    active_email = None
    for candidate_email, candidate_password in credential_candidates:
        if try_login(candidate_email, candidate_password):
            active_email = candidate_email
            break

    if not active_email:
        fail(
            "unable to authenticate with any known seeded credentials. "
            "Set VERICYCLE_CHECK_EMAIL and VERICYCLE_CHECK_PASSWORD explicitly."
        )

    cfg = s.get(f"{base}/api/config", timeout=20).json()

    created = s.post(f"{base}/api/simulate-deposit", timeout=30)
    if created.status_code != 200:
        fail(f"deposit failed status={created.status_code} body={created.text[:300]}")

    created_payload = created.json()
    activity_id = created_payload.get("activity_id")

    deadline = time.time() + 180
    final_row = None
    while time.time() < deadline:
        rows = s.get(f"{base}/api/my-dashboard-data", timeout=30).json().get("timeline", [])
        row = next((x for x in rows if int(x.get("id", -1)) == int(activity_id)), None)
        if row:
            stage = (row.get("pipeline_stage") or row.get("stage") or "").lower()
            if stage in ("rewarded", "attested", "failed"):
                final_row = row
                break
        time.sleep(2)

    if final_row is None:
        rows = s.get(f"{base}/api/my-dashboard-data", timeout=30).json().get("timeline", [])
        final_row = next((x for x in rows if int(x.get("id", -1)) == int(activity_id)), None)

    return {
        "mode": "http",
        "base": base,
        "account": active_email,
        "config": cfg,
        "activity_id": activity_id,
        "row": {
            "id": final_row.get("id") if final_row else None,
            "stage": (final_row.get("pipeline_stage") if final_row else None),
            "logbook_status": final_row.get("logbook_status") if final_row else None,
            "hedera_tx_id": final_row.get("hedera_tx_id") if final_row else None,
            "reward_status": final_row.get("reward_status") if final_row else None,
            "reward_tx_id": final_row.get("reward_tx_id") if final_row else None,
        },
    }


def main():
    mode = (os.environ.get("VERICYCLE_CHECK_MODE") or "internal").strip().lower()
    if mode == "http":
        out = run_http_mode()
    else:
        out = run_internal_mode()
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
