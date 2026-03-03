"""
RewardAgent: EcoCoin balance updates + reward finalization
Credits rewards to user and submits real HTS transfer when available.
"""

import os
import re
import subprocess
from extensions import db
from models import Activity, User, AgentTask

FINAL_LOGBOOK = {"anchored", "offchain_final", "demo_skipped"}
FINAL_REWARD = {"paid", "finalized_no_transfer"}


def _enqueue_compliance_once(activity_id: int) -> bool:
    exists = AgentTask.query.filter(
        AgentTask.activity_id == activity_id,
        AgentTask.agent_name == "ComplianceAgent",
        AgentTask.status.in_(["queued", "running"])
    ).first()
    if exists:
        return False

    db.session.add(AgentTask(
        activity_id=activity_id,
        agent_name="ComplianceAgent",
        task_type="attest",
        status="queued"
    ))
    return True


def _extract_tx_id(stdout: str) -> str | None:
    m = re.search(r"^TX_ID=(0\.0\.\d+@\d+\.\d+)\s*$", stdout or "", re.MULTILINE)
    return m.group(1) if m else None


def _run_reward_transfer(collector_account_id: str, reward_amount: float, timeout_sec: int = 45) -> str:
    rounded_amount = int(round(float(reward_amount or 0)))
    if rounded_amount <= 0:
        raise RuntimeError("Reward amount must be positive")

    cmd = ["node", "transfer-reward.js", collector_account_id, str(rounded_amount)]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout_sec,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        env=os.environ.copy(),
    )

    stdout = result.stdout or ""
    stderr = result.stderr or ""

    if result.returncode != 0:
        reason = ""
        lines = [ln.strip() for ln in stderr.replace("\r", "\n").split("\n") if ln.strip()]
        if lines:
            reason = lines[-1]
        raise RuntimeError(f"HTS reward transfer failed. rc={result.returncode} reason={reason or 'Unknown'}")

    tx_id = _extract_tx_id(stdout)
    if not tx_id:
        raise RuntimeError("HTS reward transfer did not return TX_ID=... line")
    return tx_id


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
            activity = db.session.get(Activity, activity_id)

            if not activity:
                print(f"[REWARD AGENT ERROR] Activity {activity_id} not found", flush=True)
                return "done"  # nothing to do

            if activity.pipeline_stage in ("rewarded", "attested") or (activity.reward_status in FINAL_REWARD):
                print(f"[REWARD AGENT] Already finalized (stage={activity.pipeline_stage}, reward_status={activity.reward_status})", flush=True)
                return "done"

            # Deferred Hedera mode: rewards run once activity is verified/logged
            if activity.pipeline_stage not in ("verified", "logged"):
                print(f"[REWARD AGENT] Skipping (stage={activity.pipeline_stage})", flush=True)
                return "skip"

            # Reward must only finalize after Logbook reached terminal success for mode.
            # DEMO_MODE=1  -> demo_skipped
            # DEMO_MODE=0  -> anchored
            if activity.logbook_status not in FINAL_LOGBOOK:
                activity.last_error = "Reward blocked: logbook not finalized yet"
                db.session.commit()
                print(
                    f"[REWARD AGENT] Skipping: {activity.last_error} "
                    f"(logbook_status={activity.logbook_status})",
                    flush=True
                )
                return "skip"

            print(f"[REWARD AGENT] Crediting rewards for activity {activity_id}", flush=True)

            def finalize_without_transfer(reason: str):
                normalized_reason = (reason or "Reward finalized without transfer")[:512]
                activity.status = "verified"
                activity.pipeline_stage = "rewarded"
                activity.last_error = None
                activity.reward_status = "finalized_no_transfer"
                activity.reward_tx_id = None
                activity.reward_last_error = normalized_reason
                db.session.commit()

                compliance_queued = _enqueue_compliance_once(activity.id)
                db.session.commit()

                try:
                    from app import log_agent_event
                    log_agent_event(activity.id, "RewardAgent", "info", activity.pipeline_stage, None, f"reward_finalized_no_transfer: {normalized_reason[:350]}")
                    db.session.commit()
                except Exception:
                    pass

                print(f"[REWARD AGENT WARN] Finalized without transfer: {normalized_reason}", flush=True)
                print(f"[REWARD AGENT] Activity marked rewarded; ComplianceAgent enqueued={compliance_queued}", flush=True)
                return "finalized_no_transfer"

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

            if activity.reward_status in FINAL_REWARD:
                print(f"[REWARD AGENT] Reward already finalized status={activity.reward_status}; skipping", flush=True)
                return "done"

            if not user.hedera_account_id:
                return finalize_without_transfer("Collector Hedera account is missing")

            if not os.getenv("ECOCOIN_TOKEN_ID"):
                return finalize_without_transfer("ECOCOIN_TOKEN_ID not configured")

            reward_tx_id = None
            print(f"[REWARD AGENT] Submitting HTS transfer to {user.hedera_account_id}", flush=True)
            try:
                reward_tx_id = _run_reward_transfer(user.hedera_account_id, activity.amount)
            except Exception as transfer_exc:
                return finalize_without_transfer(f"HTS transfer failed: {transfer_exc}")

            activity.status = "verified"
            activity.pipeline_stage = "rewarded"
            activity.last_error = None
            activity.reward_status = "paid"
            activity.reward_tx_id = reward_tx_id
            activity.reward_last_error = None

            try:
                from app import log_agent_event
                log_agent_event(activity.id, "RewardAgent", "info", activity.pipeline_stage, reward_tx_id, f"reward_transferred: tx_id={reward_tx_id}")
                db.session.commit()
            except Exception:
                pass
            
            print(f"[REWARD AGENT] ✓ Rewards processed", flush=True)
            print(
                f"RewardAgent: logbook finalized via {activity.logbook_status} -> reward complete",
                flush=True
            )
            print(f"RewardAgent: reward transferred tx_id={reward_tx_id}", flush=True)

            db.session.commit()
            compliance_queued = _enqueue_compliance_once(activity.id)
            db.session.commit()
            print(f"[REWARD AGENT] Activity marked rewarded; ComplianceAgent enqueued={compliance_queued}", flush=True)
            print(f"{'='*80}\n", flush=True)

            return "paid"

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
                    try:
                        from app import log_agent_event
                        log_agent_event(activity.id, "RewardAgent", "error", activity.pipeline_stage, None, f"reward_failed: {str(e)}")
                        db.session.commit()
                    except Exception:
                        pass
            except:
                pass
            print(f"{'='*80}\n", flush=True)
            return False
