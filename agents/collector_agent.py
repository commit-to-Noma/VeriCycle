import subprocess
from extensions import db
from models import Activity
import os
import sys
import re

class CollectorAgent:

    def process(self, activity_id):
        # Import the Flask app here to avoid circular imports at module import time
        from app import app

        print(f"\n{'='*80}", flush=True)
        print(f"[AGENT] Starting CollectorAgent.process() for activity_id={activity_id}", flush=True)
        print(f"{'='*80}\n", flush=True)

        # Ensure this background thread has an application context for DB access
        with app.app_context():
            try:
                activity = Activity.query.get(activity_id)

                if not activity:
                    print(f"[AGENT ERROR] Activity {activity_id} not found in database", flush=True)
                    return {"success": False, "error": "Activity not found"}

                print(f"[AGENT] Activity loaded: desc='{activity.desc}', amount={activity.amount}, status={activity.status}", flush=True)

                if activity.agent_processed:
                    print(f"[AGENT WARNING] Activity {activity_id} already processed", flush=True)
                    return {"success": False, "error": "Already processed"}

                # Validation logic
                print(f"[AGENT] Validating amount: {activity.amount} (must be > 0 and <= 200)", flush=True)
                if activity.amount <= 0 or activity.amount > 200:
                    activity.verified_status = "rejected"
                    activity.status = "rejected"
                    activity.agent_processed = True
                    db.session.commit()
                    print(f"[AGENT] Activity {activity_id} REJECTED due to invalid amount", flush=True)
                    return {"success": False, "error": "Invalid weight"}

                print(f"[AGENT] Amount validation PASSED ✓", flush=True)

                # Get Hedera credentials
                operator_id = os.getenv("OPERATOR_ID")
                operator_key = os.getenv("OPERATOR_KEY")

                if not operator_id or not operator_key:
                    raise Exception("Missing OPERATOR_ID or OPERATOR_KEY environment variables")

                print(f"[AGENT] Hedera credentials loaded (operator_id={operator_id[:10]}...)", flush=True)

                # Call Hedera submission script (real HCS write to topic)
                print(f"[AGENT] Calling Hedera submission script: node submit-record.js", flush=True)
                result = subprocess.run(
                    ["node", "submit-record.js", str(activity_id)],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                )

                stdout = (result.stdout or "").strip()
                stderr = (result.stderr or "").strip()
                
                # Parse TX_ID from stdout
                TX_ID_PATTERN = re.compile(r"TX_ID=(.+)")
                tx_id = None
                for line in stdout.split('\n'):
                    match = TX_ID_PATTERN.search(line.strip())
                    if match:
                        tx_id = match.group(1).strip()
                        break

                if result.returncode != 0 or not tx_id:
                    print(f"[AGENT ERROR] Hedera script failed with return code {result.returncode}", flush=True)
                    if stderr:
                        print(f"[AGENT ERROR] stderr: {stderr}", flush=True)
                    if stdout:
                        print(f"[AGENT ERROR] stdout: {stdout}", flush=True)
                    raise Exception(f"Hedera submission failed: {stderr or stdout or 'unknown error'}")

                print(f"[AGENT] Hedera HCS submission SUCCESSFUL ✓", flush=True)
                print(f"[AGENT] Transaction ID: {tx_id}", flush=True)

                # Update DB with verified status and parsed TX ID
                activity.verified_status = "verified"
                activity.status = "verified"
                activity.agent_processed = True
                activity.hedera_tx_id = tx_id

                print(f"[AGENT] Updating database: status=verified, hedera_tx_id={tx_id}", flush=True)
                db.session.commit()
                print(f"[AGENT] Database commit SUCCESSFUL ✓", flush=True)

                print(f"[AGENT] ✅ Activity {activity_id} processing COMPLETE", flush=True)
                print(f"{'='*80}\n", flush=True)

                return {"success": True, "tx_id": tx_id}

            except subprocess.TimeoutExpired:
                print(f"[AGENT ERROR] Hedera script timed out after 30 seconds", flush=True)
                try:
                    activity.status = "failed"
                    activity.hedera_tx_id = None
                    db.session.commit()
                except:
                    pass
                return {"success": False, "error": "Hedera submission timeout"}

            except Exception as e:
                print(f"[AGENT ERROR] Unexpected exception: {type(e).__name__}: {str(e)}", flush=True)
                import traceback
                traceback.print_exc()
                try:
                    activity.status = "failed"
                    activity.hedera_tx_id = None
                    db.session.commit()
                except:
                    pass
                print(f"{'='*80}\n", flush=True)
                return {"success": False, "error": str(e)}
