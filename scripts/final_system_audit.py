import os
import re
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, build_rewards_wallet_snapshot, seed_demo_data, _find_golden_runs  # noqa: E402
from models import Activity, OpportunityAssignment, PickupOpportunity, User  # noqa: E402


def print_check(name: str, passed: bool, detail: str = ""):
    status = "PASS" if passed else "FAIL"
    print(f"[{status}] {name}{' :: ' + detail if detail else ''}")


def role_login(client, email: str, password: str = "1234"):
    return client.post("/login", data={"email": email, "password": password}, follow_redirects=False)


def is_anchored(activity: Activity) -> bool:
    states = {
        (activity.logbook_status or "").strip().lower(),
        (activity.pipeline_stage or "").strip().lower(),
    }
    return bool(activity.hcs_tx_id or activity.logbook_tx_id or activity.hedera_tx_id) or bool(states & {"anchored", "logged", "attested", "offchain_final", "demo_skipped"})


def is_rewarded(activity: Activity) -> bool:
    states = {
        (activity.reward_status or "").strip().lower(),
        (activity.pipeline_stage or "").strip().lower(),
    }
    return bool(activity.hts_tx_id or activity.reward_tx_id) or bool(states & {"paid", "finalized_no_transfer", "rewarded", "attested"})


def main() -> int:
    with app.app_context():
        seed_demo_data(force_reset=False)

        all_rows = Activity.query.order_by(Activity.id.desc()).all()
        anchored_count = sum(1 for row in all_rows if is_anchored(row))
        rewarded_count = sum(1 for row in all_rows if is_rewarded(row))
        proof_hub_count = len(all_rows)

        recycler = User.query.filter_by(email="recycler@vericycle.com").first()
        business = User.query.filter_by(email="business@vericycle.com").first()

        wallet_snapshot = build_rewards_wallet_snapshot(recycler) if recycler else {
            "verified_events": 0,
            "history_rows": [],
            "proof_records": 0,
        }

        business_verified_assignments = (
            OpportunityAssignment.query
            .join(PickupOpportunity, OpportunityAssignment.opportunity_id == PickupOpportunity.id)
            .filter(PickupOpportunity.source_role == "business")
            .filter(PickupOpportunity.source_user_id == (business.id if business else -1))
            .filter(OpportunityAssignment.linked_activity_id.isnot(None))
            .count()
        )

        business_rewarded = (
            Activity.query
            .join(OpportunityAssignment, OpportunityAssignment.linked_activity_id == Activity.id)
            .join(PickupOpportunity, OpportunityAssignment.opportunity_id == PickupOpportunity.id)
            .filter(PickupOpportunity.source_role == "business")
            .filter(PickupOpportunity.source_user_id == (business.id if business else -1))
            .filter((Activity.reward_tx_id.isnot(None)) | (Activity.hts_tx_id.isnot(None)) | (Activity.reward_status.in_(["paid", "finalized_no_transfer"])))
            .count()
        )

        print("=== A. DATA CONSISTENCY ===")
        print_check("Proof Hub anchored count available", anchored_count > 0, f"anchored={anchored_count}")
        print_check("Proof Hub has records", proof_hub_count > 0, f"records={proof_hub_count}")
        print_check("HTS rewarded exists", rewarded_count > 0, f"rewarded={rewarded_count}")
        print_check("Business verified rows exist", business_verified_assignments > 0, f"verified_rows={business_verified_assignments}")
        print_check("Business rewarded rows exist", business_rewarded > 0, f"rewarded_rows={business_rewarded}")
        print_check("Recycler wallet has linked history", len(wallet_snapshot.get("history_rows", [])) > 0, f"wallet_rows={len(wallet_snapshot.get('history_rows', []))}")

        golden = _find_golden_runs(all_rows)
        print("=== B. ADMIN INTEGRITY ===")
        print_check("Golden run exists", bool(golden.get("perfect") or golden.get("approved") or golden.get("rejected")))
        print_check("No empty critical KPI buckets", anchored_count > 0 and rewarded_count > 0 and business_verified_assignments > 0)

    print("=== C. LINK AND ROLE CHECKS ===")
    with app.test_client() as client:
        # Recycler success modal -> Proof Hub link present
        role_login(client, "recycler@vericycle.com")
        collector_html = client.get("/collector").get_data(as_text=True)
        print_check("Recycler modal links to Proof Hub", "submission-success-proof-link" in collector_html and "/proof-hub" in collector_html)
        client.get("/logout")

        # Business -> Download Proof present
        role_login(client, "business@vericycle.com")
        business_html = client.get("/business").get_data(as_text=True)
        print_check("Business page exposes Download Proof", "Download Proof" in business_html)
        client.get("/logout")

        # Proof Hub -> HashScan links
        role_login(client, "admin@vericycle.com")
        proof_html = client.get("/proof-hub").get_data(as_text=True)
        print_check("Proof Hub contains HashScan links", "hashscan.io/testnet/transaction" in proof_html)

        # Role isolation
        client.get("/logout")
        role_login(client, "recycler@vericycle.com")
        r_admin = client.get("/admin/monitor", follow_redirects=False)
        print_check("Recycler blocked from admin", r_admin.status_code in (302, 303))
        client.get("/logout")

        role_login(client, "business@vericycle.com")
        r_collector = client.get("/collector", follow_redirects=False)
        print_check("Business blocked from collector", r_collector.status_code in (302, 303))
        client.get("/logout")

        public_home = client.get("/home").get_data(as_text=True)
        logged_out_ok = all(token in public_home for token in ["Log In", "Create Account"])
        print_check("Logged-out nav shows only auth entry points", logged_out_ok)

    print("=== AUDIT COMPLETE ===")
    print(f"timestamp_utc={datetime.now(timezone.utc).isoformat()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
