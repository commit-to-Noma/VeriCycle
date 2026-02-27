from datetime import datetime, timezone, timedelta
from extensions import db
from models import AgentTask

PIPELINE_TASKS = [
    ("CollectorAgent", "collect"),
]

def enqueue_pipeline(activity_id: int):
    now = datetime.now(timezone.utc)
    # Initial enqueue is Collector only. Downstream agents are enqueued by prior agents.
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
