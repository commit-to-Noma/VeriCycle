from datetime import datetime, timezone, timedelta
from extensions import db
from models import AgentTask

PIPELINE_TASKS = [
    ("CollectorAgent", "collect"),
    ("VerifierAgent", "verify"),
    ("LogbookAgent", "log"),
    ("RewardAgent", "reward"),
    ("ComplianceAgent", "attest"),
]

def enqueue_pipeline(activity_id: int):
    now = datetime.now(timezone.utc)
    # Stagger tasks so Collector runs first, then Verifier, etc.
    # Offsets are in seconds and simple; adjust if you need finer control.
    offsets = [0, 1, 2, 3, 4]
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
