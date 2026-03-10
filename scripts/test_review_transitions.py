#!/usr/bin/env python
from datetime import datetime, timezone
import sys
import os
from typing import NoReturn

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from app import app, db, enqueue_once
from models import User, Activity, AgentTask, VerificationSignal


def fail(msg: str) -> NoReturn:
    print(f"FAIL: {msg}")
    sys.exit(1)


def create_activity(user_id: int, desc: str, confidence: float, reason: str) -> Activity:
    activity = Activity()
    activity.user_id = user_id
    activity.timestamp = datetime.now(timezone.utc).isoformat()
    activity.desc = desc
    activity.amount = 10.0
    activity.status = "pending"
    activity.verified_status = "pending"
    activity.pipeline_stage = "needs_review"
    activity.confidence_score = confidence
    activity.trust_weight = confidence
    activity.verifier_reputation = confidence
    activity.review_status = "pending_review"
    activity.review_reason = reason
    db.session.add(activity)
    db.session.flush()

    signal = VerificationSignal()
    signal.activity_id = activity.id
    signal.signal_type = "resident_confirmation"
    signal.source_role = "participant"
    signal.source_user_id = user_id
    signal.value = "confirmed"
    signal.weight = 0.2
    signal.is_positive = True
    signal.metadata_json = '{"regression": "review_transition"}'
    db.session.add(signal)

    return activity


def has_downstream_tasks(activity_id: int) -> bool:
    downstream_agents = ["LogbookAgent", "RewardAgent", "ComplianceAgent"]
    row = AgentTask.query.filter(
        AgentTask.activity_id == activity_id,
        AgentTask.agent_name.in_(downstream_agents),
        AgentTask.status.in_(["queued", "running", "done"]),
    ).first()
    return row is not None


with app.app_context():
    print("=" * 80)
    print("Review transition regression check")
    print("=" * 80)

    reviewer = User.query.filter(User.role.in_(["admin", "center"]))\
        .order_by(User.id.asc()).first()
    if not reviewer:
        fail("No admin/center user exists for review simulation")

    collector = User.query.filter_by(role="collector").order_by(User.id.asc()).first()
    if not collector:
        collector = User()
        collector.email = f"collector.review.regression.{int(datetime.now(timezone.utc).timestamp())}@demo.local"
        collector.password_hash = "placeholder"
        collector.full_name = "Regression Collector"
        collector.role = "collector"
        db.session.add(collector)
        db.session.flush()

    approved = create_activity(
        collector.id,
        "Regression Approved Review Event",
        confidence=0.2,
        reason="conflicting_or_insufficient_signals",
    )

    rejected = create_activity(
        collector.id,
        "Regression Rejected Review Event",
        confidence=0.2,
        reason="conflicting_or_insufficient_signals",
    )

    db.session.commit()

    # Simulate approve handler state transition.
    approved.review_status = "approved"
    approved.review_reason = None
    approved.reviewed_by_user_id = reviewer.id
    approved.reviewed_at = datetime.now(timezone.utc)
    approved.status = "verified"
    approved.verified_status = "verified"
    approved.pipeline_stage = "verified"
    queued_logbook = enqueue_once(approved.id, "LogbookAgent")
    db.session.commit()

    if not queued_logbook:
        fail("Approve path did not queue LogbookAgent")

    approved_task = AgentTask.query.filter_by(activity_id=approved.id, agent_name="LogbookAgent")\
        .order_by(AgentTask.id.desc()).first()
    if not approved_task or approved_task.status != "queued":
        fail("Approve path missing queued LogbookAgent task")

    # Simulate reject handler state transition.
    rejected.review_status = "rejected"
    rejected.review_reason = "manager_rejected_after_review"
    rejected.reviewed_by_user_id = reviewer.id
    rejected.reviewed_at = datetime.now(timezone.utc)
    rejected.status = "rejected"
    rejected.verified_status = "rejected"
    rejected.pipeline_stage = "rejected"
    rejected.last_error = rejected.review_reason
    db.session.commit()

    if has_downstream_tasks(rejected.id):
        fail("Reject path incorrectly has downstream agent tasks")

    print(f"PASS: approved_event_id={approved.id} queued_logbook={queued_logbook}")
    print(f"PASS: rejected_event_id={rejected.id} has_no_downstream_tasks=True")
    print("=" * 80)
    print("All review transition regression checks passed")
    print("=" * 80)
