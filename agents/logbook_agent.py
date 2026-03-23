"""
LogbookAgent: HCS submission + transaction tracking
Calls hedera-scripts/submit-record.js and stores the transaction ID.
Uses per-user Hedera credentials first, with operator fallback.
"""

import subprocess
import re
import os
from datetime import datetime, timezone
from extensions import db
from models import Activity, User, AgentTask


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


def _enqueue_reward_once(activity_id: int) -> bool:
    exists = AgentTask.query.filter(
        AgentTask.activity_id == activity_id,
        AgentTask.agent_name == "RewardAgent",
        AgentTask.status.in_(["queued", "running"])
    ).first()
    if exists:
        return False

    db.session.add(AgentTask(
        activity_id=activity_id,
        agent_name="RewardAgent",
        task_type="reward",
        status="queued"
    ))
    return True


def _queue_state_label(was_queued: bool) -> str:
    return "queued" if was_queued else "already_queued"

def _extract_tx_id(stdout: str) -> str | None:
    # strict: TX_ID=0.0.x@seconds.nanoseconds
    m = re.search(r"^TX_ID=(0\.0\.\d+@\d+\.\d+)\s*$", stdout, re.MULTILINE)
    return m.group(1) if m else None


def _summarize_error(err: str | Exception) -> str:
    text = str(err or "")
    if not text:
        return "unknown error"
    text = text.replace("\r", "\n")
    first_line = next((ln.strip() for ln in text.split("\n") if ln.strip()), "unknown error")
    if len(first_line) > 220:
        first_line = first_line[:220] + "..."
    return first_line


def _tail_lines(text: str, lines: int = 30) -> str:
    if not text:
        return ""
    cleaned = text.replace("\r", "\n")
    parts = [ln for ln in cleaned.split("\n") if ln != ""]
    return "\n".join(parts[-lines:])


def _stderr_reason(stderr_text: str) -> str:
    cleaned = (stderr_text or "").replace("\r", "\n")
    lines = [ln.strip() for ln in cleaned.split("\n") if ln.strip()]
    if not lines:
        return "Unknown"

    for ln in reversed(lines):
        if ln.startswith("ERROR="):
            return ln
    for ln in reversed(lines):
        if ln.startswith("WARN="):
            return ln
    return lines[-1]


def _run_submit_script(activity_id: int, env: dict, timeout_sec: int = 45) -> str:
    proof_hash = env.get("VERICYCLE_PROOF_HASH", "")
    cmd = ["node", "hedera-scripts/submit-record.js", str(activity_id)]
    if proof_hash:
        cmd.append(proof_hash)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=timeout_sec,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    stdout_tail = _tail_lines(stdout, 8)
    stderr_tail = _tail_lines(stderr, 30)
    reason = _stderr_reason(stderr_tail)

    if result.returncode != 0:
        raise RuntimeError(
            "HCS submit failed. "
            f"rc={result.returncode} reason={reason}"
        )

    tx_id = _extract_tx_id(stdout)
    if not tx_id:
        raise RuntimeError(
            "HCS submit did not return TX_ID=... line. "
            f"rc={result.returncode} reason={reason}"
        )

    return tx_id


def submit_to_hcs_for_activity(activity: Activity) -> str:
    """
    Submit activity proof to Hedera HCS.
    Primary attempt uses the activity owner's Hedera credentials.
    Fallback attempt uses shared OPERATOR_ID/OPERATOR_KEY from process env.
    
    Args:
        activity: Activity object to submit
        
    Returns:
        Transaction ID string
    """
    user = db.session.get(User, activity.user_id)
    base_env = os.environ.copy()
    primary_error = None
    from app import get_user_private_key
    user_private_key = get_user_private_key(user)

    has_user_creds = bool(user and user.hedera_account_id and user_private_key)
    if has_user_creds:
        print(f"[LOGBOOK AGENT] Primary signer: user account {user.hedera_account_id}", flush=True)
        user_env = base_env.copy()
        user_env["OPERATOR_ID"] = user.hedera_account_id
        user_env["OPERATOR_KEY"] = user_private_key
        user_env["VERICYCLE_PROOF_HASH"] = activity.proof_hash or ""
        try:
            return _run_submit_script(activity.id, user_env)
        except Exception as e:
            primary_error = _summarize_error(e)
            print(f"[LOGBOOK AGENT WARN] User-sign submission failed; trying operator fallback", flush=True)
            print(f"[LOGBOOK AGENT WARN] Primary error: {primary_error}", flush=True)
    else:
        print(f"[LOGBOOK AGENT WARN] User {activity.user_id} missing Hedera credentials; trying operator fallback", flush=True)
        primary_error = "Missing user Hedera credentials"

    # Fallback to shared operator credentials already loaded in process env
    fallback_op_id = base_env.get("OPERATOR_ID")
    fallback_op_key = base_env.get("OPERATOR_KEY")
    if fallback_op_id and fallback_op_key:
        print(f"[LOGBOOK AGENT] Fallback signer: operator account {fallback_op_id}", flush=True)
        try:
            base_env["VERICYCLE_PROOF_HASH"] = activity.proof_hash or ""
            return _run_submit_script(activity.id, base_env)
        except Exception as fallback_exc:
            fallback_error = _summarize_error(fallback_exc)
            raise RuntimeError(
                "HCS submit failed for both user and operator credentials. "
                f"primary_error={primary_error}; fallback_error={fallback_error}"
            )

    raise RuntimeError(
        "HCS submit failed and no operator fallback credentials available. "
        f"primary_error={primary_error}"
    )


def _persist_logbook_failed(activity: Activity | None, err_msg: str):
    if not activity:
        return
    now_utc = datetime.now(timezone.utc)
    activity.hedera_tx_id = None
    activity.logbook_tx_id = None
    activity.hcs_tx_id = None
    activity.logbook_status = "offchain_final"
    activity.logbook_last_error = (err_msg or "HCS submission failed")[:500]
    activity.reputation_delta = -0.05
    activity.verifier_reputation = max(0.0, (activity.verifier_reputation or 0.85) + activity.reputation_delta)
    activity.trust_weight = activity.verifier_reputation
    activity.logbook_finalized_at = now_utc
    activity.pipeline_stage = "logged"
    activity.last_error = None
    db.session.commit()


class LogbookAgent:
    name = "LogbookAgent"

    def process(self, activity_id: int) -> bool:
        """
        Submit verified activity to Hedera HCS and store transaction ID.
        Uses per-user Hedera credentials for isolation.
        Returns True if successful, False on failure.
        """
        from app import app

        print(f"\n{'='*80}", flush=True)
        print(f"[LOGBOOK AGENT] Processing activity_id={activity_id}", flush=True)
        print(f"{'='*80}\n", flush=True)

        with app.app_context():
            activity = None
            try:
                activity = db.session.get(Activity, activity_id)

                if not activity:
                    print(f"[LOGBOOK AGENT ERROR] Activity {activity_id} not found", flush=True)
                    return "done"  # nothing to do

                # Idempotency: if already logged to HCS, skip
                if activity.hedera_tx_id:
                    activity.logbook_status = activity.logbook_status or "anchored"
                    activity.logbook_tx_id = activity.logbook_tx_id or activity.hedera_tx_id
                    activity.hcs_tx_id = activity.hcs_tx_id or activity.logbook_tx_id or activity.hedera_tx_id
                    activity.logbook_finalized_at = activity.logbook_finalized_at or datetime.now(timezone.utc)
                    activity.logbook_last_error = None
                    if activity.logbook_status == "anchored":
                        activity.reputation_delta = 0.02
                        activity.verifier_reputation = min(1.0, (activity.verifier_reputation or 0.85) + 0.02)
                        activity.trust_weight = activity.verifier_reputation
                    db.session.commit()
                    reward_queued = _enqueue_reward_once(activity.id)
                    compliance_queued = _enqueue_compliance_once(activity.id)
                    db.session.commit()
                    print("[LOGBOOK AGENT] Already logged; skipping", flush=True)
                    print(
                        f"[LOGBOOK AGENT] Downstream queue state: RewardAgent={_queue_state_label(reward_queued)}, ComplianceAgent={_queue_state_label(compliance_queued)}",
                        flush=True,
                    )
                    return "done"

                if os.getenv("DEMO_MODE", "0") == "1":
                    print("[LOGBOOK AGENT] DEMO_MODE enabled: skipping Hedera submit (no hedera_tx_id will be set)", flush=True)

                    try:
                        activity.logbook_status = "demo_skipped"
                        activity.logbook_tx_id = None
                        activity.hcs_tx_id = None
                        activity.logbook_last_error = None
                        activity.logbook_finalized_at = datetime.now(timezone.utc)
                    except Exception:
                        pass

                    activity.pipeline_stage = "logged"
                    activity.last_error = None
                    db.session.commit()

                    reward_queued = _enqueue_reward_once(activity.id)
                    compliance_queued = _enqueue_compliance_once(activity.id)
                    db.session.commit()
                    print(
                        f"[LOGBOOK AGENT] Downstream queue state: RewardAgent={_queue_state_label(reward_queued)}, ComplianceAgent={_queue_state_label(compliance_queued)}",
                        flush=True,
                    )

                    try:
                        from app import log_agent_event
                        log_agent_event(activity.id, "LogbookAgent", "info", activity.pipeline_stage, None, "DEMO_MODE: Hedera submit skipped")
                        db.session.commit()
                    except Exception:
                        pass

                    return "demo_skipped"

                if not activity.proof_hash:
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
                    db.session.commit()

                if activity.pipeline_stage != "verified":
                    print(f"[LOGBOOK AGENT] Skipping (stage={activity.pipeline_stage})", flush=True)
                    return "skip"

                activity.logbook_status = "pending"
                activity.logbook_last_error = None
                activity.last_error = None
                db.session.commit()

                print(f"[LOGBOOK AGENT] Submitting to Hedera HCS...", flush=True)

                try:
                    tx_id = submit_to_hcs_for_activity(activity)
                except Exception as e:
                    reason = _summarize_error(e)
                    _persist_logbook_failed(activity, reason)
                    reward_queued = _enqueue_reward_once(activity.id)
                    compliance_queued = _enqueue_compliance_once(activity.id)
                    db.session.commit()
                    try:
                        from app import log_agent_event
                        log_agent_event(activity.id, "LogbookAgent", "info", activity.pipeline_stage, None, f"offchain_finalized: {reason}")
                        db.session.commit()
                    except Exception:
                        pass
                    print(
                        f"[LOGBOOK AGENT] Downstream queue state: RewardAgent={_queue_state_label(reward_queued)}, ComplianceAgent={_queue_state_label(compliance_queued)}",
                        flush=True
                    )
                    print(f"LogbookAgent: HCS submit failed -> offchain_final (anchor pending): {reason}", flush=True)
                    return "offchain_final"

                print(f"[LOGBOOK AGENT] HCS submission successful", flush=True)
                print(f"[LOGBOOK AGENT] Transaction ID: {tx_id}", flush=True)
                print(f"LogbookAgent: anchored tx_id={tx_id}", flush=True)
                print(f"[HCS] Anchored event {activity.id} tx_id={tx_id}", flush=True)

                activity.hedera_tx_id = tx_id
                activity.logbook_tx_id = tx_id
                activity.hcs_tx_id = tx_id
                activity.status = "verified"
                activity.last_error = None
                activity.logbook_status = "anchored"
                activity.logbook_last_error = None
                activity.logbook_finalized_at = datetime.now(timezone.utc)
                activity.reputation_delta = 0.02
                activity.verifier_reputation = min(1.0, (activity.verifier_reputation or 0.85) + 0.02)
                activity.trust_weight = activity.verifier_reputation
                db.session.commit()
                try:
                    from app import log_agent_event
                    log_agent_event(activity.id, "LogbookAgent", "info", activity.pipeline_stage, tx_id, f"anchored: tx_id={tx_id}")
                    db.session.commit()
                except Exception:
                    pass

                compliance_queued = _enqueue_compliance_once(activity.id)
                reward_queued = _enqueue_reward_once(activity.id)
                db.session.commit()

                print(f"[LOGBOOK AGENT] Activity logged with tx_id", flush=True)
                print(
                    f"[LOGBOOK AGENT] Downstream queue state: RewardAgent={_queue_state_label(reward_queued)}, ComplianceAgent={_queue_state_label(compliance_queued)}",
                    flush=True,
                )
                print(f"{'='*80}\n", flush=True)

                return True

            except subprocess.TimeoutExpired:
                print(f"[LOGBOOK AGENT ERROR] Hedera script timed out", flush=True)
                try:
                    _persist_logbook_failed(activity, "HCS submission timeout")
                    if activity:
                        reward_queued = _enqueue_reward_once(activity.id)
                        compliance_queued = _enqueue_compliance_once(activity.id)
                        db.session.commit()
                        try:
                            from app import log_agent_event
                            log_agent_event(activity.id, "LogbookAgent", "info", activity.pipeline_stage, None, "offchain_finalized: HCS submission timeout")
                            db.session.commit()
                        except Exception:
                            pass
                        print(
                            f"[LOGBOOK AGENT] Downstream queue state: RewardAgent={_queue_state_label(reward_queued)}, ComplianceAgent={_queue_state_label(compliance_queued)}",
                            flush=True
                        )
                        print("LogbookAgent: HCS submit failed -> offchain_final (anchor pending): HCS submission timeout", flush=True)
                except Exception:
                    pass
                print(f"{'='*80}\n", flush=True)
                return "offchain_final"

            except Exception as e:
                print(f"[LOGBOOK AGENT ERROR] {type(e).__name__}: {str(e)}", flush=True)
                try:
                    reason = _summarize_error(e)
                    _persist_logbook_failed(activity, reason)
                    if activity:
                        reward_queued = _enqueue_reward_once(activity.id)
                        compliance_queued = _enqueue_compliance_once(activity.id)
                        db.session.commit()
                        try:
                            from app import log_agent_event
                            log_agent_event(activity.id, "LogbookAgent", "info", activity.pipeline_stage, None, f"offchain_finalized: {reason}")
                            db.session.commit()
                        except Exception:
                            pass
                        print(
                            f"[LOGBOOK AGENT] Downstream queue state: RewardAgent={_queue_state_label(reward_queued)}, ComplianceAgent={_queue_state_label(compliance_queued)}",
                            flush=True
                        )
                        print(f"LogbookAgent: HCS submit failed -> offchain_final (anchor pending): {reason}", flush=True)
                except Exception:
                    pass
                print(f"{'='*80}\n", flush=True)
                return "offchain_final"
