"""
CollectorAgent: Basic validation + creates pipeline activity
Now a lightweight stage-setter for the multi-agent pipeline.
"""

from extensions import db
from models import Activity, AgentTask


def _enqueue_verifier_once(activity_id: int) -> bool:
    existing = AgentTask.query.filter(
        AgentTask.activity_id == activity_id,
        AgentTask.agent_name == "VerifierAgent",
        AgentTask.status.in_(["queued", "running", "done"])
    ).first()
    if existing:
        return False

    db.session.add(AgentTask(
        activity_id=activity_id,
        agent_name="VerifierAgent",
        task_type="verify",
        status="queued"
    ))
    return True


class CollectorAgent:
    name = "CollectorAgent"

    def process(self, activity_id: int):
        """
        Validate activity data and mark as 'collected' if valid.
        Returns True if successful, False if validation fails.
        """
        from app import app

        print(f"\n{'='*80}", flush=True)
        print(f"[AGENT] CollectorAgent.process() activity_id={activity_id}", flush=True)
        print(f"{'='*80}\n", flush=True)

        with app.app_context():
            try:
                activity = db.session.get(Activity, activity_id)

                if not activity:
                    print(f"[AGENT ERROR] Activity {activity_id} not found", flush=True)
                    return False

                # Monotonic stage guard: never move an activity "backwards"
                STAGE_RANK = {
                    "created": 0,
                    "collected": 1,
                    "verified": 2,
                    "log_failed": 3,
                    "logged": 4,
                    "rewarded": 5,
                    "attested": 6,
                    "rejected": 99,   # terminal
                }

                cur = activity.pipeline_stage or "created"
                cur_rank = STAGE_RANK.get(cur, 0)

                # If we've already reached collected or beyond, CollectorAgent must not rewrite stage.
                if cur_rank >= STAGE_RANK["collected"]:
                    print(f"[AGENT] CollectorAgent: already past collected (stage={cur}); skipping without changes", flush=True)
                    return "skip"

                # If not exactly "created", also skip (covers any unexpected pre-created states)
                if cur != "created":
                    print(f"[AGENT] Skipping (stage={cur})", flush=True)
                    return "skip"

                print(f"[AGENT] Activity loaded: desc='{activity.desc}', amount={activity.amount}", flush=True)

                # Validation: amount must be positive and <= 200
                print(f"[AGENT] Validating: amount={activity.amount} (must be > 0 and <= 200)", flush=True)
                if activity.amount <= 0 or activity.amount > 200:
                    activity.status = "rejected"
                    activity.verified_status = "rejected"
                    activity.pipeline_stage = "rejected"
                    activity.trust_weight = 0.0
                    activity.last_error = "Validation failed: invalid amount"
                    db.session.commit()
                    print(f"[AGENT] Activity REJECTED: invalid amount", flush=True)
                    return False

                print(f"[AGENT] Validation PASSED", flush=True)

                # Mark as collected and ready for verification
                activity.pipeline_stage = "collected"
                activity.attempt_count = (activity.attempt_count or 0) + 1
                db.session.commit()

                verifier_queued = _enqueue_verifier_once(activity.id)
                db.session.commit()

                print(f"[AGENT] Activity marked as 'collected', ready for verification", flush=True)
                print(f"[AGENT] Enqueued downstream: VerifierAgent={verifier_queued}", flush=True)
                print(f"{'='*80}\n", flush=True)

                return True

            except Exception as e:
                print(f"[AGENT ERROR] Unexpected exception: {type(e).__name__}: {str(e)}", flush=True)
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
