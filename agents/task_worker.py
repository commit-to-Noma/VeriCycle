import time
from datetime import datetime, timezone
from sqlalchemy import case

from extensions import db
from models import AgentTask, AgentLog, Activity
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
def _log(activity_id: int, agent_name: str, message: str, level: str = "info"):
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    activity = db.session.get(Activity, activity_id)
    db.session.add(AgentLog(
        created_at=ts,
        activity_id=activity_id,
        agent_name=agent_name,
        level=level,
        message=message[:512],
        pipeline_stage=getattr(activity, "pipeline_stage", None) if activity else None,
        hedera_tx_id=getattr(activity, "hedera_tx_id", None) if activity else None,
        last_error=getattr(activity, "last_error", None) if activity else None,
    ))

def run_worker_loop(poll_interval=1.0):
    print("[WORKER] AgentTask worker loop started", flush=True)

    # import app lazily to avoid circular imports during module import
    from app import app

    while True:
        try:
            with app.app_context():
                # Only pick queued tasks; done/failed/running tasks are never re-executed
                priority_order = case(
                    (AgentTask.agent_name == "CollectorAgent", 1),
                    (AgentTask.agent_name == "VerifierAgent", 2),
                    (AgentTask.agent_name == "LogbookAgent", 3),
                    (AgentTask.agent_name == "RewardAgent", 4),
                    (AgentTask.agent_name == "ComplianceAgent", 5),
                    else_=99,
                )
                task = (AgentTask.query
                    .filter(AgentTask.status == "queued")
                    .order_by(priority_order.asc(), AgentTask.id.asc())
                    .first())

                if not task:
                    time.sleep(0.5)
                    continue
                else:
                    # lock task so it cannot be picked again
                    task.status = "running"
                    db.session.commit()

                    # Refresh activity and skip if activity is in a terminal state
                    activity = db.session.get(Activity, task.activity_id)
                    if not activity or activity.status in ("failed", "rejected") or activity.pipeline_stage in ("failed", "rejected"):
                        task.status = "done"
                        task.last_error = "Skipped: activity terminal state"
                        _log(task.activity_id, task.agent_name, task.last_error)
                        db.session.commit()
                        continue

                    agent = AGENT_MAP.get(task.agent_name)
                    if not agent:
                        task.status = "failed"
                        task.last_error = f"Unknown agent: {task.agent_name}"
                        _log(task.activity_id, task.agent_name, task.last_error, level="error")
                        db.session.commit()
                    else:
                        print(f"[WORKER] Running task_id={task.id} agent={task.agent_name} activity_id={task.activity_id}", flush=True)
                        _log(task.activity_id, task.agent_name, f"START task_id={task.id}")
                        db.session.commit()

                        run_result = None
                        try:
                            run_result = agent.process(task.activity_id)
                        except Exception as e:
                            task.last_error = f"{type(e).__name__}: {str(e)}"[:512]
                            task.status = "failed"
                            _log(task.activity_id, task.agent_name, f"ERROR {type(e).__name__}: {str(e)}", level="error")
                            db.session.commit()
                            print(f"[WORKER TASK ERROR] task_id={task.id} {type(e).__name__}: {e}", flush=True)
                        finally:
                            if task.status == "running":
                                task.status = "done"
                                task.last_error = None
                                _log(task.activity_id, task.agent_name, f"DONE result={run_result}")
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
