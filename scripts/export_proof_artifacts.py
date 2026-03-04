import json
import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app import app, db
from models import Activity, User, AgentTask

ARTIFACTS_DIR = os.path.join(ROOT, "artifacts")


def _hashscan_link(tx_id: str | None) -> str | None:
    if not tx_id:
        return None
    return f"https://hashscan.io/testnet/transaction/{tx_id}"


def _load_activity(activity_id: int):
    activity = db.session.get(Activity, activity_id)
    if activity:
        return activity

    # Fallback for safety: export the newest activity if 55 is missing.
    return Activity.query.order_by(Activity.id.desc()).first()


def main():
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)

    with app.app_context():
        requested_id = 55
        activity = _load_activity(requested_id)

        if not activity:
            payload = {
                "requested_activity_id": requested_id,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "error": "No activity rows found in DB",
            }
        else:
            user = db.session.get(User, activity.user_id)
            tasks = (
                AgentTask.query
                .filter_by(activity_id=activity.id)
                .order_by(AgentTask.id.asc())
                .all()
            )

            payload = {
                "requested_activity_id": requested_id,
                "exported_activity_id": activity.id,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "collector_email": user.email if user else None,
                "timestamp": activity.timestamp,
                "description": activity.desc,
                "amount": activity.amount,
                "pipeline_stage": activity.pipeline_stage,
                "trust_weight": activity.trust_weight,
                "proof_hash": activity.proof_hash,
                "statuses": {
                    "logbook_status": activity.logbook_status,
                    "reward_status": activity.reward_status,
                },
                "tx_ids": {
                    "hcs_tx_id": getattr(activity, "hcs_tx_id", None) or activity.logbook_tx_id or activity.hedera_tx_id,
                    "hts_tx_id": getattr(activity, "hts_tx_id", None) or activity.reward_tx_id,
                    "compliance_tx_id": getattr(activity, "compliance_tx_id", None),
                },
                "hashscan_links": {
                    "hcs": _hashscan_link(getattr(activity, "hcs_tx_id", None) or activity.logbook_tx_id or activity.hedera_tx_id),
                    "hts": _hashscan_link(getattr(activity, "hts_tx_id", None) or activity.reward_tx_id),
                },
                "agent_tasks": [
                    {
                        "id": t.id,
                        "agent": t.agent_name,
                        "task_type": t.task_type,
                        "status": t.status,
                        "attempts": t.attempts,
                        "last_error": t.last_error,
                        "updated_at": t.updated_at.isoformat() if getattr(t, "updated_at", None) else None,
                    }
                    for t in tasks
                ],
            }

    proof_path = os.path.join(ARTIFACTS_DIR, "proof_deposit55.json")
    with open(proof_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    screenshot_path = os.path.join(ARTIFACTS_DIR, "screenshots_required.txt")
    hcs_link = payload.get("hashscan_links", {}).get("hcs")
    hts_link = payload.get("hashscan_links", {}).get("hts")
    with open(screenshot_path, "w", encoding="utf-8") as f:
        f.write("VeriCycle judge proof checklist\n")
        f.write("===============================\n\n")
        f.write("1) Admin monitor activity detail for Deposit 55 (or exported fallback id)\n")
        f.write("2) Proof bundle JSON download / hash verification badge\n")
        f.write("3) HashScan page for HCS tx\n")
        f.write(f"   {hcs_link or '[missing]'}\n")
        f.write("4) HashScan page for HTS tx\n")
        f.write(f"   {hts_link or '[missing]'}\n")
        f.write("5) Any compliance completion evidence (tx id / offchain id)\n")

    print("WROTE artifacts/proof_deposit55.json")
    print("WROTE artifacts/screenshots_required.txt")


if __name__ == "__main__":
    main()
