#!/usr/bin/env python
"""Phase 3 smoke checks for pickup opportunity create/list/accept flows."""

import os
import sys
from uuid import uuid4

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, db
from extensions import bcrypt
from models import User, PickupOpportunity, OpportunityAssignment

TEST_PASSWORD = "Phase3Smoke!pass"


def create_test_user(email: str, role: str, name: str) -> User:
    user = User.query.filter_by(email=email).first()
    if not user:
        user = User()
        user.email = email
        db.session.add(user)

    user.password_hash = bcrypt.generate_password_hash(TEST_PASSWORD).decode("utf-8")
    user.role = role
    user.full_name = name
    user.phone_number = "0000000000"
    user.id_number = f"ID-{uuid4().hex[:8]}"
    if role == "business":
        user.address = "Phase 3 Business Address"
    elif role == "resident":
        user.address = "Phase 3 Resident Address"
    db.session.commit()
    return user


def assert_ok(resp, expected_code=200, label="request"):
    if resp.status_code != expected_code:
        raise RuntimeError(f"{label} expected {expected_code}, got {resp.status_code}: {resp.get_data(as_text=True)[:300]}")


def login_for_role(client, email: str, role: str):
    resp = client.post(
        "/login",
        data={
            "email": email,
            "password": TEST_PASSWORD,
            "role": role,
        },
        follow_redirects=False,
    )
    if resp.status_code not in (302, 303):
        raise RuntimeError(f"login failed for {email} ({role}): {resp.status_code}")


def main():
    suffix = uuid4().hex[:8]

    with app.app_context():
        business = create_test_user(f"phase3.business.{suffix}@example.com", "business", "Phase 3 Business")
        resident = create_test_user(f"phase3.resident.{suffix}@example.com", "resident", "Phase 3 Resident")
        recycler = create_test_user(f"phase3.recycler.{suffix}@example.com", "collector", "Phase 3 Recycler")

        # Keep this run scoped so we can validate exact IDs deterministically.
        created_ids = []

        with app.test_client() as client:
            login_for_role(client, business.email, "business")
            create_business = client.post(
                "/api/opportunities/create",
                json={
                    "material_type": "Mixed (Paper, Plastic, Cans)",
                    "estimated_kg": 18,
                    "location": "Randburg",
                    "requested_window": "Tomorrow 10:00 - 12:00",
                    "notes": "Phase 3 smoke business",
                },
            )
            assert_ok(create_business, 200, "business create")
            payload = create_business.get_json() or {}
            if not payload.get("ok"):
                raise RuntimeError(f"business create failed payload: {payload}")
            created_ids.append(int(payload["opportunity_id"]))

        with app.test_client() as client:
            login_for_role(client, resident.email, "resident")
            create_resident = client.post(
                "/api/opportunities/create",
                json={
                    "material_type": "Mainly Plastic",
                    "estimated_kg": 8,
                    "location": "Roodepoort",
                    "requested_window": "Day After 09:00 - 11:00",
                    "notes": "Phase 3 smoke resident",
                },
            )
            assert_ok(create_resident, 200, "resident create")
            payload = create_resident.get_json() or {}
            if not payload.get("ok"):
                raise RuntimeError(f"resident create failed payload: {payload}")
            created_ids.append(int(payload["opportunity_id"]))

        with app.test_client() as client:
            login_for_role(client, recycler.email, "recycler")
            collector_page = client.get("/collector", follow_redirects=False)
            if collector_page.status_code != 200:
                raise RuntimeError(f"recycler dashboard check failed with {collector_page.status_code}")

            open_before = client.get("/api/opportunities/open")
            assert_ok(open_before, 200, "open list before accept")
            rows_before = (open_before.get_json() or {}).get("rows") or []
            open_ids_before = {int(row["id"]) for row in rows_before if row.get("id") is not None}

            for expected_id in created_ids:
                if expected_id not in open_ids_before:
                    raise RuntimeError(f"created opportunity {expected_id} not present in open list")

            accept_res = client.post(f"/api/opportunities/{created_ids[0]}/accept")
            assert_ok(accept_res, 200, "accept opportunity")
            accept_payload = accept_res.get_json() or {}
            if not accept_payload.get("ok"):
                raise RuntimeError(f"accept failed payload: {accept_payload}")

            open_after = client.get("/api/opportunities/open")
            assert_ok(open_after, 200, "open list after accept")
            rows_after = (open_after.get_json() or {}).get("rows") or []
            open_ids_after = {int(row["id"]) for row in rows_after if row.get("id") is not None}

            if created_ids[0] in open_ids_after:
                raise RuntimeError("accepted opportunity still appears in open list")
            if created_ids[1] not in open_ids_after:
                raise RuntimeError("non-accepted opportunity disappeared unexpectedly")

        accepted = db.session.get(PickupOpportunity, created_ids[0])
        remaining = db.session.get(PickupOpportunity, created_ids[1])
        assignment = OpportunityAssignment.query.filter_by(
            opportunity_id=created_ids[0], recycler_user_id=recycler.id
        ).first()

        if not accepted or accepted.status != "accepted":
            raise RuntimeError("accepted opportunity did not persist accepted status")
        if not remaining or remaining.status != "open":
            raise RuntimeError("remaining opportunity is not open")
        if not assignment:
            raise RuntimeError("opportunity assignment row was not created")

    print("PHASE3_OPPORTUNITIES_SMOKE: PASS")


if __name__ == "__main__":
    main()
