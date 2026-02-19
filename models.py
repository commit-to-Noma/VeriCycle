from extensions import db
from flask_login import UserMixin
from datetime import datetime, timezone


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(60), nullable=False)
    hedera_account_id = db.Column(db.String(100), nullable=True)
    hedera_private_key = db.Column(db.String(255), nullable=True)
    
    full_name = db.Column(db.String(100), nullable=True)
    phone_number = db.Column(db.String(20), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    id_number = db.Column(db.String(30), nullable=True)
    role = db.Column(db.String(20), nullable=False, default='collector')


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
    trust_weight = db.Column(db.Float, default=1.0)
    
    # PIPELINE FIELDS (for multi-agent coordinator)
    pipeline_stage = db.Column(db.String(50), default="created")  # created -> collected -> verified -> logged -> rewarded -> attested
    last_error = db.Column(db.String(512), nullable=True)
    attempt_count = db.Column(db.Integer, default=0)

    user = db.relationship('User', backref=db.backref('activities', lazy=True))


class AgentTask(db.Model):
    __tablename__ = "agent_task"

    id = db.Column(db.Integer, primary_key=True)

    activity_id = db.Column(db.Integer, db.ForeignKey('activity.id'), nullable=False)
    agent_name = db.Column(db.String(50), nullable=False)     # "CollectorAgent", etc
    task_type = db.Column(db.String(50), nullable=False)      # "collect"/"verify"/"log"/"reward"/"attest"

    status = db.Column(db.String(20), default="queued")       # queued|processing|done|failed
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
