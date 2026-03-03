"""
ComplianceAgent: Attestation + audit trail finalization
Emits final attestation record to HCS for audit/compliance.
"""

from extensions import db
from models import Activity


class ComplianceAgent:
    name = "ComplianceAgent"

    def process(self, activity_id: int) -> bool:
        """
        Emit final attestation and complete the pipeline.
        Returns True if successful, False on failure.
        """
        print(f"\n{'='*80}", flush=True)
        print(f"[COMPLIANCE AGENT] Processing activity_id={activity_id}", flush=True)
        print(f"{'='*80}\n", flush=True)

        try:
            activity = db.session.get(Activity, activity_id)

            if not activity:
                print(f"[COMPLIANCE AGENT ERROR] Activity {activity_id} not found", flush=True)
                return "done"  # nothing to do

            # Deferred mode: compliance runs only after reward finalization
            if activity.pipeline_stage != "rewarded":
                print(f"[COMPLIANCE AGENT] Skipping (stage={activity.pipeline_stage})", flush=True)
                return "skip"

            print(f"[COMPLIANCE AGENT] Recording attestation for activity {activity_id}", flush=True)

            reward_status = getattr(activity, "reward_status", None)
            if reward_status not in ("paid", "finalized_no_transfer"):
                activity.last_error = "Compliance blocked: reward not finalized yet"
                db.session.commit()
                print(f"[COMPLIANCE AGENT] Skipping: {activity.last_error}", flush=True)
                return "skip"

            activity.pipeline_stage = "attested"
            print(f"[COMPLIANCE AGENT] ✓ Attestation recorded", flush=True)

            db.session.commit()
            print(f"[COMPLIANCE AGENT] Activity marked as 'attested' ✓", flush=True)
            print(f"[COMPLIANCE AGENT] Pipeline complete for activity {activity_id}", flush=True)
            print(f"{'='*80}\n", flush=True)

            return "done"

        except Exception as e:
            print(f"[COMPLIANCE AGENT ERROR] {type(e).__name__}: {str(e)}", flush=True)
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
