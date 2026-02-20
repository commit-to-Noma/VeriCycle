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
