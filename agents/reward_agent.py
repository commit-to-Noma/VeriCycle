"""
RewardAgent: EcoCoin balance updates + reward finalization
Credits rewards to user. HTS transfer would go here in future.
"""

from extensions import db
from models import Activity, User


class RewardAgent:
    name = "RewardAgent"

    def process(self, activity_id: int) -> bool:
        """
        Credit rewards for verified activities.
        Returns True if successful, False on failure.
        """
        print(f"\n{'='*80}", flush=True)
        print(f"[REWARD AGENT] Processing activity_id={activity_id}", flush=True)
        print(f"{'='*80}\n", flush=True)

        try:
            activity = Activity.query.get(activity_id)

            if not activity:
                print(f"[REWARD AGENT ERROR] Activity {activity_id} not found", flush=True)
                return "done"  # nothing to do

            # Only process if logged
            if activity.pipeline_stage != "logged":
                print(f"[REWARD AGENT] Skipping (stage={activity.pipeline_stage})", flush=True)
                return "skip"

            print(f"[REWARD AGENT] Crediting rewards for activity {activity_id}", flush=True)

            # Get the user
            user = User.query.get(activity.user_id)
            if not user:
                error_msg = "Reward failed: user not found"
                print(f"[REWARD AGENT ERROR] {error_msg}", flush=True)
                activity.status = "failed"
                activity.pipeline_stage = "failed"
                activity.last_error = error_msg
                db.session.commit()
                return False

            print(f"[REWARD AGENT] User: {user.email}, amount={activity.amount}", flush=True)

            # Hackathon: just mark as verified (future: update balance, HTS transfer, etc.)
            activity.status = "verified"
            activity.pipeline_stage = "rewarded"
            
            print(f"[REWARD AGENT] ✓ Rewards processed", flush=True)

            db.session.commit()
            print(f"[REWARD AGENT] Activity marked as 'rewarded'", flush=True)
            print(f"{'='*80}\n", flush=True)

            return "done"

        except Exception as e:
            print(f"[REWARD AGENT ERROR] {type(e).__name__}: {str(e)}", flush=True)
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
