from datetime import datetime, timezone

from app import app, db, create_verification_signal
from models import User, Activity
from agents.task_enqueue import enqueue_pipeline


with app.app_context():
    u = User.query.filter_by(role="collector").first()
    if not u:
        raise RuntimeError("No collector user found")

    a = Activity(
        user_id=u.id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        desc="Low signal test",
        amount=10.0,
        status="pending",
        verified_status="pending",
        pipeline_stage="created",
    )
    db.session.add(a)
    db.session.flush()

    create_verification_signal(
        activity_id=a.id,
        signal_type="resident_confirmation",
        source_role="participant",
        source_user_id=u.id,
        value="confirmed",
        is_positive=True,
        metadata={"test": "low_signal"},
    )

    db.session.commit()
    enqueue_pipeline(a.id)

    print("activity_id:", a.id)
