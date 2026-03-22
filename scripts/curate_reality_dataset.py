#!/usr/bin/env python
"""Curate a realistic pre-deployment demo dataset through app workflows (UI-backed routes)."""

import os
import sys
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, seed_demo_data  # noqa: E402
from models import Activity, OpportunityAssignment, PickupOpportunity, User  # noqa: E402


DEFAULT_PASSWORD = "1234"


class FlowError(RuntimeError):
    pass


def _json(response):
    try:
        return response.get_json(silent=True)
    except Exception:
        return None


def ensure_ok(response, context: str) -> dict[str, Any]:
    payload = _json(response)
    if response.status_code >= 400:
        raise FlowError(f"{context} failed: HTTP {response.status_code} payload={payload}")
    if isinstance(payload, dict) and payload.get("ok") is False:
        raise FlowError(f"{context} failed: payload={payload}")
    return payload or {}


def login(client, email: str, password: str = DEFAULT_PASSWORD):
    response = client.post("/login", data={"email": email, "password": password}, follow_redirects=False)
    if response.status_code not in (302, 303):
        raise FlowError(f"Login failed for {email}: HTTP {response.status_code}")


def logout(client):
    client.get("/logout", follow_redirects=False)


def upsert_profile(client, *, full_name: str, phone: str, address: str, id_number: str):
    response = client.post(
        "/profile",
        data={
            "full_name": full_name,
            "phone_number": phone,
            "address": address,
            "id_number": id_number,
        },
        follow_redirects=False,
    )
    if response.status_code not in (302, 303):
        raise FlowError(f"Profile update failed: HTTP {response.status_code}")


def create_opportunity(client, *, material: str, kg: float, window: str, notes: str = "") -> int:
    response = client.post(
        "/api/opportunities/create",
        json={
            "material_type": material,
            "estimated_kg": kg,
            "requested_window": window,
            "notes": notes,
        },
    )
    payload = ensure_ok(response, f"create opportunity {material} {kg}")
    opportunity_id = payload.get("opportunity_id")
    if not opportunity_id:
        raise FlowError(f"Missing opportunity_id for {material} {kg}: payload={payload}")
    return int(opportunity_id)


def accept_opportunity(client, opportunity_id: int) -> int:
    response = client.post(f"/api/opportunities/{opportunity_id}/accept")
    payload = ensure_ok(response, f"accept opportunity {opportunity_id}")
    assignment_id = payload.get("assignment_id")
    if not assignment_id:
        raise FlowError(f"Missing assignment_id when accepting {opportunity_id}: payload={payload}")
    return int(assignment_id)


def confirm_handover(client, assignment_id: int):
    response = client.post(f"/business/assignments/{assignment_id}/confirm-handover", follow_redirects=False)
    if response.status_code not in (302, 303):
        raise FlowError(f"confirm handover failed for assignment {assignment_id}: HTTP {response.status_code}")


def submit_assignment(client, assignment_id: int, material: str, kg: float):
    response = client.post(
        f"/api/assignments/{assignment_id}/submit",
        json={"material_type": material, "weight_kg": kg},
    )
    ensure_ok(response, f"submit assignment {assignment_id}")


def verify_assignment(client, assignment_id: int):
    response = client.post(f"/api/center/assignments/{assignment_id}/verify")
    ensure_ok(response, f"verify assignment {assignment_id}")


def direct_deposit(client, *, collector_id: str, material: str, kg: float):
    response = client.post(
        "/verify-and-anchor/direct",
        data={
            "collector_id": collector_id,
            "material": material,
            "weight": str(kg),
        },
    )
    payload = _json(response) or {}
    if response.status_code >= 400 or payload.get("success") is False:
        raise FlowError(f"direct deposit failed material={material} kg={kg}: HTTP {response.status_code} payload={payload}")


def signup_recycler2_if_needed(client):
    with app.app_context():
        existing = User.query.filter_by(email="recycler2@vericycle.com").first()
        if existing:
            return

    response = client.post(
        "/signup",
        data={
            "email": "recycler2@vericycle.com",
            "password": DEFAULT_PASSWORD,
            "role": "recycler",
            "auth_source": "home-modal",
        },
        follow_redirects=False,
    )
    if response.status_code not in (302, 303):
        raise FlowError(f"signup recycler2 failed: HTTP {response.status_code}")

    # After signup user is logged in; complete profile so recycler dashboard access works.
    upsert_profile(
        client,
        full_name="Demo Recycler Two",
        phone="0820000002",
        address="Johannesburg CBD, Gauteng",
        id_number="9202020002088",
    )
    logout(client)



def summarize_states() -> dict[str, Any]:
    with app.app_context():
        open_jobs = PickupOpportunity.query.filter_by(status="open").count()
        accepted_not_submitted = OpportunityAssignment.query.filter_by(status="accepted").count()
        submitted_not_verified = OpportunityAssignment.query.filter_by(status="submitted").count()
        fully_verified = Activity.query.filter(Activity.pipeline_stage.in_(["attested", "rewarded", "logged", "verified"])).count()
        flagged = Activity.query.filter_by(pipeline_stage="needs_review").count()
        community_active = (
            PickupOpportunity.query
            .filter_by(source_role="resident")
            .filter(PickupOpportunity.status.in_(["open", "submitted", "accepted", "in_transit"]))
            .count()
        )
        community_resolved = PickupOpportunity.query.filter_by(source_role="resident", status="completed").count()
        recycler2_exists = User.query.filter_by(email="recycler2@vericycle.com").count() > 0

    return {
        "open_jobs": open_jobs,
        "accepted_not_submitted": accepted_not_submitted,
        "submitted_not_verified": submitted_not_verified,
        "fully_verified_flows": fully_verified,
        "flagged_events": flagged,
        "community_active": community_active,
        "community_resolved": community_resolved,
        "recycler2_exists": recycler2_exists,
    }


def main() -> int:
    print("[dataset] starting curated flow setup")
    with app.app_context():
        seed_demo_data(force_reset=False)

    with app.test_client() as client:
        # Ensure profile data exists for role flows that require address/profile completion.
        login(client, "business@vericycle.com")
        upsert_profile(
            client,
            full_name="Demo Business",
            phone="0820001000",
            address="Sandton, Johannesburg",
            id_number="8201010001088",
        )
        logout(client)

        login(client, "resident@vericycle.com")
        upsert_profile(
            client,
            full_name="Demo Resident",
            phone="0820002000",
            address="Soweto, Johannesburg",
            id_number="8301010002088",
        )
        logout(client)

        login(client, "recycler@vericycle.com")
        upsert_profile(
            client,
            full_name="Demo Recycler",
            phone="0820003000",
            address="Randburg, Johannesburg",
            id_number="8401010003088",
        )
        logout(client)

        # Create recycler2 account via signup flow if missing.
        signup_recycler2_if_needed(client)

        # A1 Open business opportunity (unassigned/open).
        login(client, "business@vericycle.com")
        open_opp = create_opportunity(
            client,
            material="Cardboard",
            kg=25.0,
            window="Tomorrow 09:00-12:00",
            notes="Sandton Mall Cardboard Batch",
        )
        print(f"[dataset] created open business opportunity id={open_opp}")
        logout(client)

        # A2 Accepted but not submitted.
        login(client, "business@vericycle.com")
        accepted_only_opp = create_opportunity(
            client,
            material="Plastic",
            kg=18.0,
            window="Tomorrow 13:00-15:00",
            notes="Rosebank Office Plastic Pickup",
        )
        logout(client)

        login(client, "recycler@vericycle.com")
        accepted_only_assignment = accept_opportunity(client, accepted_only_opp)
        print(f"[dataset] accepted-only assignment id={accepted_only_assignment}")
        logout(client)

        # A3 Full business pipeline (golden run contributor).
        login(client, "business@vericycle.com")
        full_opp = create_opportunity(
            client,
            material="Glass",
            kg=12.0,
            window="Today 10:00-12:00",
            notes="Midrand Glass Recycling",
        )
        logout(client)

        login(client, "recycler@vericycle.com")
        full_assignment = accept_opportunity(client, full_opp)
        logout(client)

        login(client, "business@vericycle.com")
        confirm_handover(client, full_assignment)
        logout(client)

        login(client, "recycler@vericycle.com")
        submit_assignment(client, full_assignment, "Glass", 12.0)
        logout(client)

        login(client, "center@vericycle.com")
        verify_assignment(client, full_assignment)
        logout(client)

        # B4 Community active hotspot (not resolved).
        login(client, "resident@vericycle.com")
        community_active = create_opportunity(
            client,
            material="Mixed Recyclables",
            kg=30.0,
            window="Today 15:00-17:00",
            notes="[Community Hotspot] Illegal Dumping - Soweto Field :: Community reports recurring illegal dumping near the football field.",
        )
        print(f"[dataset] created active community hotspot id={community_active}")
        logout(client)

        # B5 Community resolved flow.
        login(client, "resident@vericycle.com")
        community_resolve_opp = create_opportunity(
            client,
            material="Mixed Recyclables",
            kg=15.0,
            window="Today 12:00-14:00",
            notes="[Community Hotspot] Park Cleanup - Randburg :: Weekend cleanup request for central park litter zone.",
        )
        logout(client)

        login(client, "recycler@vericycle.com")
        community_resolve_assignment = accept_opportunity(client, community_resolve_opp)
        submit_assignment(client, community_resolve_assignment, "Mixed Recyclables", 15.0)
        logout(client)

        login(client, "center@vericycle.com")
        verify_assignment(client, community_resolve_assignment)
        logout(client)

        # Resident confirms resolved community hotspot.
        login(client, "resident@vericycle.com")
        board_response = client.get("/api/community/hotspots/board?audience=community")
        board_payload = ensure_ok(board_response, "load community board")
        rows = board_payload.get("rows") or []
        target_key = None
        for row in rows:
            title = (row.get("title") or "").lower()
            if "park cleanup" in title and "randburg" in (row.get("location") or "").lower():
                target_key = row.get("hotspot_key")
                break
        if target_key:
            confirm_response = client.post(
                "/api/community/hotspots/confirm",
                json={"hotspot_key": target_key, "outcome": "confirmed"},
            )
            ensure_ok(confirm_response, "confirm community hotspot completion")
        logout(client)

        # C6 valid direct center deposit.
        login(client, "center@vericycle.com")
        direct_deposit(client, collector_id="0.0.7267109", material="E-Waste", kg=5.4)

        # C7 suspicious direct center deposit.
        direct_deposit(client, collector_id="0.0.7267109", material="Test Fraud Batch", kg=999.0)
        logout(client)

        # D recycler diversity: recycler2 accepts one incomplete job.
        login(client, "business@vericycle.com")
        r2_opp = create_opportunity(
            client,
            material="Plastic",
            kg=14.0,
            window="Tomorrow 11:00-13:00",
            notes="Recycler2 diversity acceptance job",
        )
        logout(client)

        login(client, "recycler2@vericycle.com")
        r2_assignment = accept_opportunity(client, r2_opp)
        print(f"[dataset] recycler2 accepted assignment id={r2_assignment}")
        logout(client)

        # E submitted but not verified.
        login(client, "business@vericycle.com")
        partial_opp = create_opportunity(
            client,
            material="Metal",
            kg=10.0,
            window="Today 16:00-18:00",
            notes="Incomplete Pipeline Test",
        )
        logout(client)

        login(client, "recycler@vericycle.com")
        partial_assignment = accept_opportunity(client, partial_opp)
        logout(client)

        login(client, "business@vericycle.com")
        confirm_handover(client, partial_assignment)
        logout(client)

        login(client, "recycler@vericycle.com")
        submit_assignment(client, partial_assignment, "Metal", 10.0)
        logout(client)

    summary = summarize_states()
    print("[dataset] completed scenario build")
    for key, value in summary.items():
        print(f"{key}={value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
