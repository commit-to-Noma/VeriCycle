"""
VerifierAgent: Trust scoring + verification decision
Assigns trust_weight and decides verified/rejected status.
"""

from extensions import db
from models import Activity, AgentTask, User


def _enqueue_agent_once(activity_id: int, agent_name: str, task_type: str) -> bool:
    exists = AgentTask.query.filter(
        AgentTask.activity_id == activity_id,
        AgentTask.agent_name == agent_name,
        AgentTask.status.in_(["queued", "running"])
    ).first()
    if exists:
        return False

    db.session.add(AgentTask(
        activity_id=activity_id,
        agent_name=agent_name,
        task_type=task_type,
        status="queued"
    ))
    return True


class VerifierAgent:
    name = "VerifierAgent"

    def process(self, activity_id: int) -> bool:
        """
        Verify collected activities and assign trust weight.
        Returns True if successful, False if rejected.
        """
        from app import app

        print(f"\n{'='*80}", flush=True)
        print(f"[VERIFIER AGENT] Processing activity_id={activity_id}", flush=True)
        print(f"{'='*80}\n", flush=True)

        with app.app_context():
            try:
                activity = db.session.get(Activity, activity_id)

                if not activity:
                    print(f"[VERIFIER AGENT ERROR] Activity {activity_id} not found", flush=True)
                    return True  # Not my responsibility

                # Only process if exactly in 'collected' stage
                if activity.pipeline_stage != "collected":
                    print(f"[VERIFIER AGENT] Skipping (stage={activity.pipeline_stage})", flush=True)
                    return "skip"

                print(f"[VERIFIER AGENT] Verifying: desc='{activity.desc}', amount={activity.amount}", flush=True)

                # Basic verification rules
                if activity.amount <= 0 or activity.amount > 200:
                    activity.status = "rejected"
                    activity.verified_status = "rejected"
                    activity.pipeline_stage = "rejected"
                    activity.trust_weight = 0.0
                    activity.last_error = "Verification failed: invalid amount"
                    db.session.commit()
                    print(f"[VERIFIER AGENT] ❌ REJECTED: invalid amount", flush=True)
                    print(f"{'='*80}\n", flush=True)
                    return False

                # Simple trust scoring (can expand with user history, center reputation, etc.)
                # For now: base trust of 0.85 for valid activities
                activity.trust_weight = 0.85
                activity.verified_status = "verified"
                activity.pipeline_stage = "verified"
                activity.logbook_status = activity.logbook_status or "pending"

                user = db.session.get(User, activity.user_id)
                from app import stable_proof_input, compute_proof_sha256
                stable_bundle = {
                    "vericycle_version": "hackathon-2026",
                    "activity_id": activity.id,
                    "timestamp": activity.timestamp,
                    "user": (user.email if user else ""),
                    "description": activity.desc,
                    "amount": float(activity.amount) if activity.amount is not None else None,
                    "stage": "recorded",
                }
                activity.proof_hash = compute_proof_sha256(stable_proof_input(stable_bundle))
                
                print(f"[VERIFIER AGENT] ✓ VERIFIED: trust_weight={activity.trust_weight}", flush=True)
                
                db.session.commit()

                logbook_queued = _enqueue_agent_once(activity.id, "LogbookAgent", "log")
                reward_queued = _enqueue_agent_once(activity.id, "RewardAgent", "reward")
                db.session.commit()
                print(f"[VERIFIER AGENT] Database updated", flush=True)
                print(
                    f"[VERIFIER AGENT] Enqueued downstream: LogbookAgent={logbook_queued}, RewardAgent={reward_queued}",
                    flush=True
                )
                print(f"{'='*80}\n", flush=True)

                return True

            except Exception as e:
                print(f"[VERIFIER AGENT ERROR] {type(e).__name__}: {str(e)}", flush=True)
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
