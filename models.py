from extensions import db
from flask_login import UserMixin


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
    agent_processed = db.Column(db.Boolean, default=False)
    hedera_tx_id = db.Column(db.String(150), nullable=True)
    trust_weight = db.Column(db.Float, default=1.0)

    user = db.relationship('User', backref=db.backref('activities', lazy=True))
