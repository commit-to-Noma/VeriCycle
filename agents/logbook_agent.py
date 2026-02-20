"""
LogbookAgent: HCS submission + transaction tracking
Calls submit-record.js and stores the transaction ID.
Uses per-user Hedera credentials (not the shared operator).
"""

import subprocess
import re
import os
from typing import Optional
from extensions import db
from models import Activity, User

def _extract_tx_id(stdout: str) -> str | None:
    m = re.search(r"TX_ID=([0-9]+\.[0-9]+\.[0-9]+@[0-9]+\.[0-9]+)", stdout)
    return m.group(1) if m else None


def submit_to_hcs_for_activity(activity: Activity) -> Optional[str]:
    """
    Submit activity to Hedera HCS using the activity owner's Hedera credentials.
    
    Args:
        activity: Activity object to submit
        
    Returns:
        Transaction ID string, or None if failed
    """
    user = User.query.get(activity.user_id)
    if not user or not user.hedera_account_id or not user.hedera_private_key:
        activity.status = "failed"
        activity.pipeline_stage = "failed"
        activity.last_error = "Missing user Hedera credentials"
        db.session.commit()
        print(f"[LOGBOOK AGENT ERROR] User {activity.user_id} missing Hedera credentials", flush=True)
        return None

    print(f"[LOGBOOK AGENT] Using user's Hedera account: {user.hedera_account_id}", flush=True)

    # Create environment with per-user credentials
    env = os.environ.copy()
    env["OPERATOR_ID"] = user.hedera_account_id
    env["OPERATOR_KEY"] = user.hedera_private_key
    # Keep shared topic ID from .env

    result = subprocess.run(
        ["node", "submit-record.js", str(activity.id)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=30,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    stdout = result.stdout or ""
    stderr = result.stderr or ""

    if result.returncode != 0:
        error_msg = f"HCS submit failed (rc={result.returncode}). stdout={stdout.strip()[:200]}"
        print(f"[LOGBOOK AGENT ERROR] {error_msg}", flush=True)
        if stderr:
            print(f"[LOGBOOK AGENT ERROR] stderr: {stderr.strip()[:200]}", flush=True)
        activity.status = "failed"
        activity.pipeline_stage = "failed"
        activity.last_error = error_msg
        db.session.commit()
        return None

    tx_id = _extract_tx_id(stdout)
    if not tx_id:
        error_msg = f"Logbook failed: TX_ID not found. stdout='{stdout.strip()}' stderr='{stderr.strip()}'"
        print(f"[LOGBOOK AGENT ERROR] {error_msg}", flush=True)
        activity.status = "failed"
        activity.pipeline_stage = "failed"
        activity.last_error = "TX_ID parse failed"
        db.session.commit()
        return None

    return tx_id


class LogbookAgent:
    name = "LogbookAgent"

    def process(self, activity_id: int) -> bool:
        """
        Submit verified activity to Hedera HCS and store transaction ID.
        Uses per-user Hedera credentials for isolation.
        Returns True if successful, False on failure.
        """
        from app import app

        print(f"\n{'='*80}", flush=True)
        print(f"[LOGBOOK AGENT] Processing activity_id={activity_id}", flush=True)
        print(f"{'='*80}\n", flush=True)

        with app.app_context():
            try:
                activity = Activity.query.get(activity_id)

                if not activity:
                    print(f"[LOGBOOK AGENT ERROR] Activity {activity_id} not found", flush=True)
                    return "done"  # nothing to do

                # Idempotency: if already logged to HCS, skip
                if activity.hedera_tx_id:
                    print("[LOGBOOK AGENT] Already logged; skipping", flush=True)
                    return "done"

                # Only process if exactly verified
                if activity.pipeline_stage != "verified":
                    print(f"[LOGBOOK AGENT] Skipping (stage={activity.pipeline_stage})", flush=True)
                    return "skip"

                print(f"[LOGBOOK AGENT] Submitting to Hedera HCS...", flush=True)

                # Use per-user credentials for submission
                tx_id = submit_to_hcs_for_activity(activity)
                
                if not tx_id:
                    print(f"[LOGBOOK AGENT] Submission failed (see details above)", flush=True)
                    print(f"{'='*80}\n", flush=True)
                    return False

                print(f"[LOGBOOK AGENT] ✓ HCS submission successful", flush=True)
                print(f"[LOGBOOK AGENT] Transaction ID: {tx_id}", flush=True)

                activity.hedera_tx_id = tx_id
                activity.pipeline_stage = "logged"
                activity.status = "verified"
                db.session.commit()

                print(f"[LOGBOOK AGENT] Activity logged with tx_id", flush=True)
                print(f"{'='*80}\n", flush=True)

                return True

            except subprocess.TimeoutExpired:
                print(f"[LOGBOOK AGENT ERROR] Hedera script timed out", flush=True)
                try:
                    if activity:
                        activity.status = "failed"
                        activity.pipeline_stage = "failed"
                        activity.last_error = "HCS submission timeout"
                        db.session.commit()
                except:
                    pass
                print(f"{'='*80}\n", flush=True)
                return False

            except Exception as e:
                print(f"[LOGBOOK AGENT ERROR] {type(e).__name__}: {str(e)}", flush=True)
                import traceback
                traceback.print_exc()
                try:
                    if activity:
                        activity.status = "failed"
                        activity.pipeline_stage = "failed"
                        activity.last_error = str(e)
                        db.session.commit()
                except:
                    pass
                print(f"{'='*80}\n", flush=True)
                return False
