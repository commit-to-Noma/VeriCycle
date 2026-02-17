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
            activity.agent_processed = True
            db.session.commit()
            return {"success": False, "error": "Invalid weight"}

        try:
            # Call your existing JS script
            operator_id = os.getenv("OPERATOR_ID")
            operator_key = os.getenv("OPERATOR_KEY")

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
            activity.hedera_tx_id = tx_output

            db.session.commit()

            return {"success": True, "tx_id": tx_output}

        except Exception as e:
            return {"success": False, "error": str(e)}
