import time
from datetime import datetime, timezone, timedelta

from extensions import db
from models import AgentTask, Activity
from agents.collector_agent import CollectorAgent
from agents.verifier_agent import VerifierAgent
from agents.logbook_agent import LogbookAgent
from agents.reward_agent import RewardAgent
from agents.compliance_agent import ComplianceAgent

AGENT_MAP = {
    "CollectorAgent": CollectorAgent(),
    "VerifierAgent": VerifierAgent(),
    "LogbookAgent": LogbookAgent(),
    "RewardAgent": RewardAgent(),
    "ComplianceAgent": ComplianceAgent(),
}

# Backoff schedule per attempt index (1-based)
BACKOFF_SECONDS = [5, 30, 120]

def _schedule_backoff(task: AgentTask):
    idx = min(task.attempts, len(BACKOFF_SECONDS)) - 1
    delay = BACKOFF_SECONDS[idx] if idx >= 0 else 5
    task.next_run_at = datetime.now(timezone.utc) + timedelta(seconds=delay)

def run_worker_loop(poll_interval=1.0):
    print("[WORKER] AgentTask worker loop started", flush=True)

    # import app lazily to avoid circular imports during module import
    from app import app

    while True:
        try:
            now = datetime.now(timezone.utc)

            with app.app_context():
                # Find next due task (only pick queued tasks to avoid reprocessing failed ones)
                task = (AgentTask.query
                    .filter(AgentTask.status == "queued")
                    .filter(AgentTask.next_run_at <= now)
                    .order_by(AgentTask.next_run_at.asc(), AgentTask.id.asc())
                    .first())

                if not task:
                    # nothing to do this cycle
                    pass
                else:
                    # Lock task
                    task.status = "processing"
                    db.session.commit()

                    # Refresh activity and skip if activity is in a terminal state
                    activity = Activity.query.get(task.activity_id)
                    if not activity or activity.status in ("failed", "rejected") or activity.pipeline_stage in ("failed", "rejected"):
                        task.status = "done"
                        task.last_error = "Skipped: activity terminal state"
                        db.session.commit()
                        continue

                    agent = AGENT_MAP.get(task.agent_name)
                    if not agent:
                        task.status = "failed"
                        task.last_error = f"Unknown agent: {task.agent_name}"
                        task.attempts += 1
                        _schedule_backoff(task)
                        db.session.commit()
                    else:
                        print(f"[WORKER] Running task_id={task.id} agent={task.agent_name} activity_id={task.activity_id}", flush=True)

                        result = agent.process(task.activity_id)

                        # 1) Terminal stop (agent indicated a hard failure)
                        if result is False:
                            task.status = "done"
                            db.session.commit()
                            continue

                        # 2) Agent asked to skip (not its turn) -> requeue shortly
                        if result == "skip":
                            task.status = "queued"
                            task.next_run_at = datetime.now(timezone.utc) + timedelta(seconds=1)
                            db.session.commit()
                            continue

                        # 3) Completed work (success)
                        task.status = "done"
                        db.session.commit()

            # Sleep between polls
            time.sleep(poll_interval)

        except Exception as e:
            # Don't crash the worker loop; attempt rollback inside app context
            print(f"[WORKER ERROR] {type(e).__name__}: {e}", flush=True)
            try:
                with app.app_context():
                    db.session.rollback()
            except Exception:
                pass
            time.sleep(poll_interval)
