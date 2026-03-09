"""
VerifierAgent: Trust scoring + verification decision
Assigns trust_weight and decides verified/rejected status.
"""

from extensions import db
from models import Activity, AgentTask, User, VerificationSignal
from agents.trust_engine import compute_signal_score, should_verify


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
                    activity.verifier_reputation = max(0.0, (activity.verifier_reputation or 0.85) - 0.05)
                    activity.reputation_delta = -0.05
                    activity.last_error = "Verification failed: invalid amount"
                    db.session.commit()
                    print(f"[VERIFIER AGENT] REJECTED: invalid amount", flush=True)
                    print(f"{'='*80}\n", flush=True)
                    return False

                signals = VerificationSignal.query.filter_by(activity_id=activity.id).all()
                score, has_conflict = compute_signal_score(signals)

                activity.confidence_score = score
                activity.trust_weight = score
                activity.verifier_reputation = score
                activity.reputation_delta = 0.0

                if should_verify(score, has_conflict):
                    activity.verified_status = "verified"
                    activity.status = "verified"
                    activity.pipeline_stage = "verified"
                    activity.review_status = None
                    activity.review_reason = None
                    activity.logbook_status = activity.logbook_status or "pending"
                else:
                    activity.verified_status = "pending"
                    activity.status = "needs_review"
                    activity.pipeline_stage = "needs_review"
                    activity.review_status = "pending_review"
                    activity.review_reason = "conflicting_or_insufficient_signals"

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
                print(
                    f"[VERIFIER AGENT] score={score} has_conflict={has_conflict} stage={activity.pipeline_stage}",
                    flush=True,
                )
                
                db.session.commit()

                if activity.pipeline_stage == "verified":
                    logbook_queued = _enqueue_agent_once(activity.id, "LogbookAgent", "log")
                    db.session.commit()
                    print(f"[VERIFIER AGENT] Database updated", flush=True)
                    print(
                        f"[VERIFIER AGENT] Enqueued downstream: LogbookAgent={logbook_queued}",
                        flush=True
                    )
                else:
                    print("[VERIFIER AGENT] Activity needs review; downstream agents not enqueued", flush=True)
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
