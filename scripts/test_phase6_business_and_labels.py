#!/usr/bin/env python
"""Phase 6 smoke checks for Business Hub rendering and reward fallback labels."""

import os
import sys
from uuid import uuid4

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.chdir(ROOT)

from app import app, db, reward_status_label
from extensions import bcrypt
from models import OpportunityAssignment, PickupOpportunity, User

TEST_PASSWORD = "Phase6Smoke!pass"


def ensure_user(email: str, role: str, name: str) -> User:
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User(email=email)
        db.session.add(user)

    user.password_hash = bcrypt.generate_password_hash(TEST_PASSWORD).decode("utf-8")
    user.role = role
    user.full_name = name
    user.phone_number = "0000000000"
    user.id_number = f"ID-{uuid4().hex[:8]}"
    if role == "business":
        user.address = "Phase 6 Business Address"
    elif role == "resident":
        user.address = "Phase 6 Resident Address"
    db.session.commit()
    return user


def login(client, email: str, role: str):
    res = client.post(
        "/login",
        data={"email": email, "password": TEST_PASSWORD, "role": role},
        follow_redirects=False,
    )
    if res.status_code not in (302, 303):
        raise RuntimeError(f"login failed for {email} ({role}): {res.status_code}")


def assert_ok(resp, label: str):
    if resp.status_code != 200:
        raise RuntimeError(f"{label} returned {resp.status_code}: {resp.get_data(as_text=True)[:300]}")


def main():
    suffix = uuid4().hex[:6]

    with app.app_context():
        business = ensure_user(f"phase6.business.{suffix}@example.com", "business", "Phase 6 Business")
        recycler = ensure_user(f"phase6.recycler.{suffix}@example.com", "collector", "Phase 6 Recycler")
        center = ensure_user(f"phase6.center.{suffix}@example.com", "center", "Phase 6 Center")

        with app.test_client() as client:
            login(client, business.email, "business")
            create_res = client.post(
                "/api/opportunities/create",
                json={
                    "material_type": "Mixed recyclables",
                    "estimated_kg": 22,
                    "location": "Phase 6 Business Site",
                    "requested_window": "Tomorrow 09:00 - 11:00",
                    "notes": "phase6 business dashboard check",
                },
            )
            assert_ok(create_res, "business create")
            create_payload = create_res.get_json() or {}
            if not create_payload.get("ok"):
                raise RuntimeError(f"business create failed: {create_payload}")
            opportunity_id = int(create_payload["opportunity_id"])

        with app.test_client() as client:
            login(client, recycler.email, "recycler")
            accept_res = client.post(f"/api/opportunities/{opportunity_id}/accept")
            assert_ok(accept_res, "opportunity accept")
            accept_payload = accept_res.get_json() or {}
            if not accept_payload.get("ok"):
                raise RuntimeError(f"opportunity accept failed: {accept_payload}")
            assignment_id = int(accept_payload["assignment_id"])

            submit_res = client.post(
                f"/api/assignments/{assignment_id}/submit",
                json={
                    "material_type": "Mixed recyclables",
                    "weight_kg": 21.5,
                    "notes": "phase6 submit",
                },
            )
            assert_ok(submit_res, "assignment submit")
            submit_payload = submit_res.get_json() or {}
            if not submit_payload.get("ok"):
                raise RuntimeError(f"assignment submit failed: {submit_payload}")

        with app.test_client() as client:
            login(client, center.email, "center")
            verify_res = client.post(f"/api/center/assignments/{assignment_id}/verify")
            assert_ok(verify_res, "center verify")
            verify_payload = verify_res.get_json() or {}
            if not verify_payload.get("ok"):
                raise RuntimeError(f"center verify failed: {verify_payload}")
            activity_id = int(verify_payload["activity_id"])

        with app.test_client() as client:
            login(client, business.email, "business")
            business_page = client.get("/business")
            assert_ok(business_page, "business page")
            body = business_page.get_data(as_text=True)

            for required_text in [
                "Business Hub",
                "Create Pickup Request",
                "Recent Pickup Requests",
                "Verified Events",
                f"#{opportunity_id}",
            ]:
                if required_text not in body:
                    raise RuntimeError(f"business page missing expected text: {required_text}")

            proof_res = client.get(f"/api/proof-bundle/{activity_id}")
            assert_ok(proof_res, "proof bundle")

        assignment = db.session.get(OpportunityAssignment, assignment_id)
        opportunity = db.session.get(PickupOpportunity, opportunity_id)
        if not assignment or assignment.status != "completed":
            raise RuntimeError("assignment did not persist completed status")
        if not opportunity or opportunity.status != "completed":
            raise RuntimeError("opportunity did not persist completed status")

        treasury_label = reward_status_label(
            "finalized_no_transfer",
            "treasury has zero eco balance",
            "rewarded",
        )
        no_transfer_label = reward_status_label("finalized_no_transfer", None, "rewarded")
        if treasury_label != "Reward recorded, treasury refill required":
            raise RuntimeError(f"unexpected treasury fallback label: {treasury_label}")
        if no_transfer_label != "Reward finalized (no transfer)":
            raise RuntimeError(f"unexpected no-transfer label: {no_transfer_label}")

    print("PHASE6_BUSINESS_AND_LABEL_SMOKE: PASS")


if __name__ == "__main__":
    main()