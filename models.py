from extensions import db
from flask_login import UserMixin
from datetime import datetime, timezone


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(60), nullable=False)
    hedera_account_id = db.Column(db.String(100), nullable=True)
    hedera_private_key = db.Column(db.String(255), nullable=True)
    hedera_private_key_encrypted = db.Column(db.Text, nullable=True)
    hedera_key_version = db.Column(db.String(20), nullable=True)
    
    full_name = db.Column(db.String(100), nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    id_number = db.Column(db.String(30), nullable=True)
    role = db.Column(db.String(20), nullable=False, default='collector')  # Phase 2: recycler may still persist as collector for compatibility.


class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.String(64), nullable=False)
    desc = db.Column(db.String(512), nullable=False)
    amount = db.Column(db.Float, nullable=False)

    # NEW FIELDS FOR AGENTS
    verified_status = db.Column(db.String(20), default="pending")
    status = db.Column(db.String(50), default="pending")
    agent_processed = db.Column(db.Boolean, default=False)
    hedera_tx_id = db.Column(db.String(150), nullable=True)
    proof_hash = db.Column(db.String(64), nullable=True)
    logbook_status = db.Column(db.String(20), default="pending")  # pending|anchored|offchain_final|demo_skipped|failed
    logbook_tx_id = db.Column(db.String(150), nullable=True)
    logbook_last_error = db.Column(db.Text, nullable=True)
    logbook_finalized_at = db.Column(db.DateTime(timezone=True), nullable=True)
    reward_status = db.Column(db.String(40), nullable=True)  # paid|finalized_no_transfer
    reward_tx_id = db.Column(db.String(150), nullable=True)
    reward_last_error = db.Column(db.Text, nullable=True)
    trust_weight = db.Column(db.Float, default=1.0)
    verifier_reputation = db.Column(db.Float, default=0.85)
    reputation_delta = db.Column(db.Float, default=0.0)
    confidence_score = db.Column(db.Float, default=0.0)

    # Explicit tx fields for judge clarity
    hcs_tx_id = db.Column(db.String(150), nullable=True)
    hts_tx_id = db.Column(db.String(150), nullable=True)
    compliance_tx_id = db.Column(db.String(150), nullable=True)
    
    # PIPELINE FIELDS (for multi-agent coordinator)
    pipeline_stage = db.Column(db.String(50), default="created")  # created -> signals_collected -> verified|needs_review -> logged -> rewarded -> attested
    last_error = db.Column(db.String(512), nullable=True)
    attempt_count = db.Column(db.Integer, default=0)
    review_status = db.Column(db.String(30), nullable=True)  # pending_review|approved|rejected
    review_reason = db.Column(db.String(255), nullable=True)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=True)

    user = db.relationship(
        'User',
        foreign_keys=[user_id],
        backref=db.backref('activities', lazy=True, foreign_keys='Activity.user_id')
    )
    reviewed_by = db.relationship(
        'User',
        foreign_keys=[reviewed_by_user_id],
        backref=db.backref('reviewed_activities', lazy=True, foreign_keys='Activity.reviewed_by_user_id')
    )


class AgentTask(db.Model):
    __tablename__ = "agent_task"

    id = db.Column(db.Integer, primary_key=True)

    activity_id = db.Column(db.Integer, db.ForeignKey('activity.id'), nullable=False)
    agent_name = db.Column(db.String(50), nullable=False)     # "CollectorAgent", etc
    task_type = db.Column(db.String(50), nullable=False)      # "collect"/"verify"/"log"/"reward"/"attest"

    status = db.Column(db.String(20), default="queued")       # queued|running|done|failed
    attempts = db.Column(db.Integer, default=0)

    next_run_at = db.Column(db.DateTime(timezone=True), nullable=False,
                            default=lambda: datetime.now(timezone.utc))
    last_error = db.Column(db.String(512), nullable=True)

    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    activity = db.relationship('Activity', backref=db.backref('tasks', lazy=True))


class DeadLetterTask(db.Model):
    __tablename__ = "dead_letter_task"

    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey('agent_task.id'), nullable=False)
    activity_id = db.Column(db.Integer, db.ForeignKey('activity.id'), nullable=False)
    agent_name = db.Column(db.String(50), nullable=False)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    reason = db.Column(db.String(512), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="open")  # open|requeued
    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc))
    resolved_at = db.Column(db.DateTime(timezone=True), nullable=True)

    task = db.relationship('AgentTask', backref=db.backref('dead_letter_entries', lazy=True))
    activity = db.relationship('Activity', backref=db.backref('dead_letter_entries', lazy=True))


class AdminAuditLog(db.Model):
    __tablename__ = "admin_audit_log"

    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc))
    admin_email = db.Column(db.String(120), nullable=False)
    action = db.Column(db.String(80), nullable=False)
    target_type = db.Column(db.String(40), nullable=True)
    target_id = db.Column(db.String(80), nullable=True)
    details = db.Column(db.String(512), nullable=True)

class Location(db.Model):
    __tablename__ = "location"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)          # e.g. "Ruimsig"
    city = db.Column(db.String(120), nullable=True)           # e.g. "Johannesburg"
    ward = db.Column(db.String(50), nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    reliability_score = db.Column(db.Float, default=1.0)


class HouseholdProfile(db.Model):
    __tablename__ = "household_profile"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, unique=True)
    location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)

    # Day 19 will update this
    reliability_score = db.Column(db.Float, default=1.0)

    user = db.relationship("User", backref=db.backref("household_profile", uselist=False))
    location = db.relationship("Location", backref=db.backref("households", lazy=True))


class WasteSchedule(db.Model):
    __tablename__ = "waste_schedule"
    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)

    # e.g. "Recycling", "General Waste", "Garden"
    stream = db.Column(db.String(50), nullable=False)

    # 0=Mon ... 6=Sun (store as int for simplicity)
    pickup_day = db.Column(db.Integer, nullable=False)

    # "08:00-12:00"
    pickup_window = db.Column(db.String(50), nullable=True)

    location = db.relationship("Location", backref=db.backref("schedules", lazy=True))


class PickupEvent(db.Model):
    __tablename__ = "pickup_event"

    id = db.Column(db.Integer, primary_key=True)
    location_id = db.Column(db.Integer, db.ForeignKey("location.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    stream = db.Column(db.String(50), nullable=False)
    scheduled_date = db.Column(db.String(10), nullable=False)
    outcome = db.Column(db.String(20), nullable=False)

    created_at = db.Column(db.String(64), nullable=False)

    location = db.relationship("Location", backref=db.backref("pickup_events", lazy=True))
    user = db.relationship("User", backref=db.backref("pickup_events", lazy=True))


class AgentLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.String(64), nullable=False)  # ISO UTC string
    activity_id = db.Column(db.Integer, nullable=False)
    agent_name = db.Column(db.String(64), nullable=False)
    level = db.Column(db.String(16), nullable=False, default="info")  # info|error
    message = db.Column(db.String(512), nullable=False)

    # snapshot fields (useful for judge view)
    pipeline_stage = db.Column(db.String(50), nullable=True)
    hedera_tx_id = db.Column(db.String(150), nullable=True)
    last_error = db.Column(db.String(512), nullable=True)


class VerificationSignal(db.Model):
    __tablename__ = "verification_signal"

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("activity.id"), nullable=False)
    signal_type = db.Column(db.String(50), nullable=False)  # resident_confirmation, collector_submission, qr_scan, photo_proof, schedule_match
    source_role = db.Column(db.String(30), nullable=False)  # participant, operator, system
    source_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    value = db.Column(db.String(120), nullable=True)  # confirmed, missed, matched, uploaded, etc.
    weight = db.Column(db.Float, nullable=False, default=0.0)
    is_positive = db.Column(db.Boolean, nullable=False, default=True)

    metadata_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc))

    activity = db.relationship("Activity", backref=db.backref("signals", lazy=True, cascade="all, delete-orphan"))
    source_user = db.relationship("User", backref=db.backref("verification_signals", lazy=True))


class AgentCommerceEvent(db.Model):
    __tablename__ = "agent_commerce_event"

    id = db.Column(db.Integer, primary_key=True)
    activity_id = db.Column(db.Integer, db.ForeignKey("activity.id"), nullable=False)
    payer_agent = db.Column(db.String(64), nullable=False)
    payee_agent = db.Column(db.String(64), nullable=False)
    reason = db.Column(db.String(128), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    token_id = db.Column(db.String(100), nullable=True)
    tx_id = db.Column(db.String(150), nullable=True)
    status = db.Column(db.String(40), nullable=False, default="finalized_no_transfer")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False,
                           default=lambda: datetime.now(timezone.utc))

    activity = db.relationship("Activity", backref=db.backref("commerce_events", lazy=True))


class PickupOpportunity(db.Model):
    __tablename__ = "pickup_opportunity"

    id = db.Column(db.Integer, primary_key=True)

    source_role = db.Column(db.String(20), nullable=False)  # business | resident
    source_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    material_type = db.Column(db.String(80), nullable=False)
    estimated_kg = db.Column(db.Float, nullable=False)
    location = db.Column(db.String(200), nullable=False)
    requested_window = db.Column(db.String(100), nullable=True)

    status = db.Column(db.String(30), nullable=False, default="open")
    # open | accepted | completed | cancelled

    notes = db.Column(db.String(500), nullable=True)

    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    source_user = db.relationship(
        "User",
        backref=db.backref("pickup_opportunities", lazy=True),
        foreign_keys=[source_user_id]
    )


class OpportunityAssignment(db.Model):
    __tablename__ = "opportunity_assignment"

    id = db.Column(db.Integer, primary_key=True)

    opportunity_id = db.Column(db.Integer, db.ForeignKey("pickup_opportunity.id"), nullable=False)
    recycler_user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    status = db.Column(db.String(30), nullable=False, default="accepted")
    # accepted | submitted | completed | cancelled

    accepted_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc)
    )

    linked_activity_id = db.Column(db.Integer, db.ForeignKey("activity.id"), nullable=True)

    opportunity = db.relationship(
        "PickupOpportunity",
        backref=db.backref("assignments", lazy=True, cascade="all, delete-orphan")
    )

    recycler_user = db.relationship(
        "User",
        backref=db.backref("opportunity_assignments", lazy=True),
        foreign_keys=[recycler_user_id]
    )

    linked_activity = db.relationship(
        "Activity",
        backref=db.backref("opportunity_assignment", uselist=False)
    )
