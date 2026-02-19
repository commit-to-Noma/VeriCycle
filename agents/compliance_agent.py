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
            activity = Activity.query.get(activity_id)

            if not activity:
                print(f"[COMPLIANCE AGENT ERROR] Activity {activity_id} not found", flush=True)
                return "done"  # nothing to do

            # Only process if rewarded
            if activity.pipeline_stage != "rewarded":
                print(f"[COMPLIANCE AGENT] Skipping (stage={activity.pipeline_stage})", flush=True)
                return "skip"

            print(f"[COMPLIANCE AGENT] Recording attestation for activity {activity_id}", flush=True)

            # Hackathon: just mark as attested
            # Future: submit a second HCS message to an "attestations" topic
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
