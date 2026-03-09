from datetime import datetime, timezone, timedelta
from extensions import db
from models import AgentTask

PIPELINE_TASKS = [
    ("CollectorAgent", "collect"),
]

def enqueue_pipeline(activity_id: int):
    now = datetime.now(timezone.utc)
    # Phase 1 signal flow: initial enqueue remains Collector only.
    # Verifier/Logbook/Reward are conditionally enqueued downstream based on verification outcome.
    offsets = [0]
    for (agent_name, task_type), off in zip(PIPELINE_TASKS, offsets):
        db.session.add(AgentTask(
            activity_id=activity_id,
            agent_name=agent_name,
            task_type=task_type,
            status="queued",
            attempts=0,
            next_run_at=now + timedelta(seconds=off),
        ))
    db.session.commit()
