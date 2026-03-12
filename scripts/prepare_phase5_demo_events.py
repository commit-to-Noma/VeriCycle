#!/usr/bin/env python
from datetime import datetime, timezone
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from app import app, db, create_verification_signal, add_schedule_match_signal
from models import Activity, AgentTask, User, VerificationSignal
from agents.collector_agent import CollectorAgent
from agents.verifier_agent import VerifierAgent
from agents.logbook_agent import LogbookAgent
from agents.reward_agent import RewardAgent
from agents.compliance_agent import ComplianceAgent


LABEL_VERIFIED = "Judge Demo Verified Event"
LABEL_APPROVED = "Judge Demo Approved Review Event"
LABEL_REJECTED = "Judge Demo Rejected Review Event"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def find_or_create_collector() -> User:
    collector = User.query.filter_by(email="test@gmail.com").first()
    if collector:
        return collector

    collector = User.query.filter_by(role="collector").order_by(User.id.asc()).first()
    if collector:
        return collector

    collector = User()
    collector.email = f"phase5.collector.{int(datetime.now(timezone.utc).timestamp())}@demo.local"
    collector.password_hash = "placeholder"
    collector.full_name = "Phase 5 Collector"
    collector.role = "collector"
    db.session.add(collector)
    db.session.commit()
    return collector


def find_reviewer() -> User:
    reviewer = User.query.filter(User.role.in_(["admin", "center"]))\
        .order_by(User.id.asc()).first()
    if not reviewer:
        raise RuntimeError("No admin/center reviewer account exists")
    return reviewer


def clear_signals(activity_id: int):
    VerificationSignal.query.filter_by(activity_id=activity_id).delete()
    db.session.commit()


def clear_downstream_tasks(activity_id: int):
    AgentTask.query.filter(
        AgentTask.activity_id == activity_id,
        AgentTask.agent_name.in_(["LogbookAgent", "RewardAgent", "ComplianceAgent"]),
    ).delete(synchronize_session=False)
    db.session.commit()


def upsert_event(collector: User, label: str, amount: float = 147.5) -> Activity:
    activity = Activity.query.filter_by(desc=label, user_id=collector.id).order_by(Activity.id.desc()).first()
    if activity is None:
        activity = Activity()
        activity.user_id = collector.id
        activity.timestamp = now_iso()
        activity.desc = label
        activity.amount = amount
        activity.status = "pending"
        activity.verified_status = "pending"
        activity.pipeline_stage = "created"
        activity.logbook_status = "pending"
        activity.review_status = None
        activity.review_reason = None
        activity.confidence_score = None
        activity.trust_weight = None
        activity.verifier_reputation = None
        activity.reward_status = None
        activity.reward_tx_id = None
        activity.hts_tx_id = None
        activity.hedera_tx_id = None
        activity.hcs_tx_id = None
        activity.logbook_tx_id = None
        activity.compliance_tx_id = None
        db.session.add(activity)
        db.session.commit()
    else:
        activity.timestamp = now_iso()
        activity.amount = amount
        activity.status = "pending"
        activity.verified_status = "pending"
        activity.pipeline_stage = "created"
        activity.logbook_status = "pending"
        activity.review_status = None
        activity.review_reason = None
        activity.reviewed_by_user_id = None
        activity.reviewed_at = None
        activity.last_error = None
        activity.confidence_score = None
        activity.trust_weight = None
        activity.verifier_reputation = None
        activity.reward_status = None
        activity.reward_tx_id = None
        activity.hts_tx_id = None
        activity.reward_last_error = None
        activity.hedera_tx_id = None
        activity.hcs_tx_id = None
        activity.logbook_tx_id = None
        activity.logbook_last_error = None
        activity.logbook_finalized_at = None
        activity.compliance_tx_id = None
        db.session.commit()

    clear_signals(activity.id)
    clear_downstream_tasks(activity.id)
    return activity


def run_full_pipeline(activity_id: int):
    CollectorAgent().process(activity_id)
    VerifierAgent().process(activity_id)
    LogbookAgent().process(activity_id)
    RewardAgent().process(activity_id)
    ComplianceAgent().process(activity_id)


def signal_verified_story(activity: Activity, collector: User):
    create_verification_signal(
        activity_id=activity.id,
        signal_type="collector_submission",
        source_role="operator",
        source_user_id=collector.id,
        value="submitted",
        is_positive=True,
        metadata={"phase": "phase5", "story": "verified"},
    )
    add_schedule_match_signal(activity)
    db.session.commit()


def signal_low_story(activity: Activity, collector: User, story_name: str):
    create_verification_signal(
        activity_id=activity.id,
        signal_type="resident_confirmation",
        source_role="participant",
        source_user_id=collector.id,
        value="confirmed",
        is_positive=True,
        metadata={"phase": "phase5", "story": story_name},
    )
    db.session.commit()


def summarize(activity: Activity) -> dict:
    return {
        "id": activity.id,
        "desc": activity.desc,
        "status": activity.status,
        "verified_status": activity.verified_status,
        "stage": activity.pipeline_stage,
        "confidence": activity.confidence_score,
        "review_status": activity.review_status,
        "hcs_tx_id": activity.hcs_tx_id or activity.logbook_tx_id or activity.hedera_tx_id,
        "hts_tx_id": activity.hts_tx_id or activity.reward_tx_id,
        "compliance_tx_id": activity.compliance_tx_id,
    }


def reload_activity(activity_id: int) -> Activity | None:
    db.session.expire_all()
    return db.session.get(Activity, activity_id)


def main():
    with app.app_context():
        collector = find_or_create_collector()
        reviewer = find_reviewer()

        # A) Perfect verified flow
        verified = upsert_event(collector, LABEL_VERIFIED)
        verified_id = verified.id
        signal_verified_story(verified, collector)
        run_full_pipeline(verified_id)
        verified = reload_activity(verified_id)
        if verified is None:
            raise RuntimeError("Verified story activity disappeared unexpectedly")

        # B) Approved review flow (prepared as pending review for live approval in demo)
        approved = upsert_event(collector, LABEL_APPROVED)
        signal_low_story(approved, collector, "approved")
        CollectorAgent().process(approved.id)
        VerifierAgent().process(approved.id)
        approved = reload_activity(approved.id)
        if approved is None:
            raise RuntimeError("Approved story activity disappeared unexpectedly")

        if (approved.pipeline_stage or "").lower() != "needs_review":
            raise RuntimeError(
                "Approved story did not enter needs_review as expected "
                f"(stage={approved.pipeline_stage}, review_status={approved.review_status}, "
                f"status={approved.status}, confidence={approved.confidence_score})"
            )

        # C) Rejected review flow
        rejected = upsert_event(collector, LABEL_REJECTED)
        signal_low_story(rejected, collector, "rejected")
        CollectorAgent().process(rejected.id)
        VerifierAgent().process(rejected.id)
        rejected = reload_activity(rejected.id)
        if rejected is None:
            raise RuntimeError("Rejected story activity disappeared unexpectedly")

        if (rejected.pipeline_stage or "").lower() != "needs_review":
            raise RuntimeError(
                "Rejected story did not enter needs_review as expected "
                f"(stage={rejected.pipeline_stage}, review_status={rejected.review_status}, "
                f"status={rejected.status}, confidence={rejected.confidence_score})"
            )

        rejected.review_status = "rejected"
        rejected.review_reason = "manager_rejected_after_review"
        rejected.reviewed_by_user_id = reviewer.id
        rejected.reviewed_at = datetime.now(timezone.utc)
        rejected.status = "rejected"
        rejected.verified_status = "rejected"
        rejected.pipeline_stage = "rejected"
        rejected.last_error = rejected.review_reason
        rejected.hcs_tx_id = None
        rejected.hedera_tx_id = None
        rejected.logbook_tx_id = None
        rejected.reward_tx_id = None
        rejected.hts_tx_id = None
        rejected.reward_status = None
        rejected.compliance_tx_id = None
        db.session.commit()

        clear_downstream_tasks(rejected.id)

        verified_final = reload_activity(verified_id)
        approved_final = reload_activity(approved.id)
        rejected_final = reload_activity(rejected.id)
        if verified_final is None or approved_final is None or rejected_final is None:
            raise RuntimeError("One or more final demo events could not be loaded")

        result = {
            "collector": collector.email,
            "reviewer": reviewer.email,
            "events": {
                "verified": summarize(verified_final),
                "approved": summarize(approved_final),
                "rejected": summarize(rejected_final),
            },
            "expected": {
                "verified_confidence_min": 0.7,
                "review_confidence_exact": 0.2,
                "approved_story_pre_demo_state": "needs_review",
                "required_labels": [LABEL_VERIFIED, LABEL_APPROVED, LABEL_REJECTED],
            },
        }
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
