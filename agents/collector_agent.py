import subprocess
from extensions import db
from models import Activity
import os

class CollectorAgent:

    def process(self, activity_id):
        activity = Activity.query.get(activity_id)

        if not activity:
            return {"success": False, "error": "Activity not found"}

        if activity.agent_processed:
            return {"success": False, "error": "Already processed"}

        # Validation logic
        if activity.amount <= 0 or activity.amount > 200:
            activity.verified_status = "rejected"
            activity.status = "rejected"
            activity.agent_processed = True
            db.session.commit()
            print(f"CollectorAgent: activity {activity_id} rejected (invalid weight)")
            return {"success": False, "error": "Invalid weight"}

        try:
            print(f"CollectorAgent triggered for activity {activity_id}")
            print("Processing activity...")
            # Call your existing JS script
            operator_id = os.getenv("OPERATOR_ID")
            operator_key = os.getenv("OPERATOR_KEY")

            print("Submitting to Hedera...")
            result = subprocess.run(
                ["node", "hedera-scripts/submit-record.js", operator_id, operator_key],
                check=True,
                capture_output=True,
                text=True
            )

            tx_output = result.stdout.strip()

            # Update DB
            activity.verified_status = "verified"
            activity.agent_processed = True
            activity.status = "processed"
            activity.hedera_tx_id = tx_output

            db.session.commit()

            print(f"CollectorAgent: activity {activity_id} processed, tx: {tx_output}")
            return {"success": True, "tx_id": tx_output}

        except Exception as e:
            # mark as errored so it's visible
            try:
                activity.status = "error"
                activity.agent_processed = True
                db.session.commit()
            except Exception:
                pass
            return {"success": False, "error": str(e)}
