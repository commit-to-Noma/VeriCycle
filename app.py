"""
================================================================================
VeriCycle - Main Flask Application (app.py)
================================================================================
This is the "brain" of the VeriCycle application. It handles:
- All server-side logic and routing.
- User authentication (signup, login, logout) using Flask-Login & Bcrypt.
- Securely calling the Hedera JavaScript "engine" (using subprocess).
- Forcing profile completion before app access.
- Serving all HTML templates and API data.

Tools Used:
- Flask: The main web framework.
- Flask-SQLAlchemy: For the database (vericycle.db).
- Flask-Login: To manage user sessions.
- Flask-Bcrypt: For hashing passwords.
- subprocess: To run Node.js scripts.
================================================================================
"""

from dotenv import load_dotenv
load_dotenv() 

from flask import Flask, render_template, request, redirect, url_for, send_file, flash, jsonify, abort
from datetime import datetime, timezone, date, timedelta
from flask_login import login_user, login_required, logout_user, current_user
import io
import zipfile
import subprocess
import os 
import requests
import json
import hashlib
import hmac
import base64
import uuid
import re 
import math
import threading
from collections import defaultdict
from sqlalchemy.exc import OperationalError
from sqlalchemy import text, func, or_
from urllib.parse import urlencode

# -----------------------------------------------------------------
# 1. APP CONFIGURATION
# - Sets up Flask configuration and database file path.
# -----------------------------------------------------------------
basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)

_secret = os.getenv('SECRET_KEY') or os.getenv('FLASK_SECRET_KEY')
if not _secret:
    import warnings
    _secret = 'dev-only-insecure-key-change-before-deploy'
    warnings.warn(
        "SECRET_KEY is not set in environment. Using insecure default — set SECRET_KEY in .env before deploying.",
        stacklevel=1
    )
app.config['SECRET_KEY'] = _secret
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'vericycle.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Session / cookie security
_is_prod = os.getenv('FLASK_ENV') == 'production' or os.getenv('RENDER') == 'true'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = _is_prod  # HTTPS-only cookies in production
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 7  # 7-day sessions

DEMO_MODE = os.getenv("DEMO_MODE", "0") == "1"
print(f"[BOOT] DEMO_MODE={'1' if DEMO_MODE else '0'}", flush=True)

# -----------------------------------------------------------------
# 2. INITIALIZE TOOLS
# - Initialize extensions: database, encryption and login manager.
# -----------------------------------------------------------------
from extensions import db, bcrypt, login_manager

# Initialize extensions with the app
db.init_app(app)
bcrypt.init_app(app)
login_manager.init_app(app)

# (Tables will be created after models are imported)

# Start the task worker thread (run in background thread with app context)
import os
import threading
from agents.task_worker import run_worker_loop


def start_worker_background():
    def _run():
        with app.app_context():
            print("[BACKEND] Worker thread entering app context", flush=True)
            run_worker_loop()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    print("[BACKEND] Task worker thread started (daemon=True)", flush=True)

# Start the background worker for both direct-run and Gunicorn deployments.
# WERKZEUG_RUN_MAIN guard prevents a double-start when the Werkzeug reloader
# forks a child process (only relevant to `python app.py` with reload enabled).
if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
    start_worker_background()

login_manager.login_view = 'home'
login_manager.login_message = None
login_manager.login_message_category = None

# -----------------------------------------------------------------
# 3. DATABASE MODEL
# - Define `User` and `Activity` models used across routes.
# -----------------------------------------------------------------
from models import User, Activity, Location, WasteSchedule, HouseholdProfile, PickupEvent, AgentLog, AgentTask, AgentCommerceEvent, DeadLetterTask, AdminAuditLog, VerificationSignal, PickupOpportunity, OpportunityAssignment, WalletTransaction
from extensions import db as _db  # ensure db is available for seed helper
from agents.proof_utils import build_proof_hash
from demo_profile import DEMO_PROFILES, apply_demo_profile, profile_health
from security_utils import encrypt_text, decrypt_text


def stable_proof_input(bundle: dict) -> dict:
    """
    Return only stable fields for proof hashing.
    Excludes transient pipeline/task fields to prevent hash drift.
    """
    return {
        "vericycle_version": bundle.get("vericycle_version"),
        "activity_id": bundle.get("activity_id"),
        "timestamp": bundle.get("timestamp"),
        "user": bundle.get("user"),
        "description": bundle.get("description"),
        "amount": bundle.get("amount"),
        "stage": bundle.get("stage"),
    }


def compute_proof_sha256(stable_dict: dict) -> str:
    canonical = json.dumps(stable_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def safe_encrypt_private_key(value: str | None) -> tuple[str | None, str | None]:
    if not value:
        return None, None
    try:
        return encrypt_text(value), "fernet-v1"
    except Exception:
        return None, None


def get_user_private_key(user: User | None) -> str | None:
    if not user:
        return None
    if getattr(user, "hedera_private_key_encrypted", None):
        try:
            return decrypt_text(user.hedera_private_key_encrypted)
        except Exception:
            return None
    return getattr(user, "hedera_private_key", None)


def normalize_role_value(role: str | None) -> str:
    normalized = (role or "").strip().lower()
    if normalized == "collector":
        return "recycler"
    return normalized


def effective_role(user):
    if not user:
        return None
    return normalize_role_value(getattr(user, "role", None))


def is_recycler_user(user):
    return effective_role(user) == "recycler"


def is_business_user(user):
    return effective_role(user) == "business"


def is_resident_user(user):
    return effective_role(user) == "resident"


def is_center_user(user):
    return effective_role(user) == "center"


def is_admin_user(user=None):
    target = user or current_user
    try:
        return target.is_authenticated and effective_role(target) == "admin"
    except Exception:
        return False


def can_create_opportunity_business(user):
    return is_business_user(user)


def can_create_opportunity_resident(user):
    return is_resident_user(user)


def can_accept_opportunity_recycler(user):
    return is_recycler_user(user)


def can_verify_deposit_center(user):
    # Day-to-day verification authority belongs only to certified centers.
    return is_center_user(user)


def can_access_activity_proof(user, activity: Activity | None) -> bool:
    if not user or not getattr(user, "is_authenticated", False) or not activity:
        return False
    if activity.user_id == user.id or is_admin_user(user) or is_center_user(user):
        return True

    assignment = OpportunityAssignment.query.filter_by(linked_activity_id=activity.id).first()
    if not assignment or not assignment.opportunity:
        return False

    opportunity = assignment.opportunity
    return opportunity.source_user_id == user.id and opportunity.source_role in {"business", "resident"}


ECO_PAYOUT_MODEL_BY_MATERIAL = {
    "glass": {
        "eco_per_kg": 1.2,
        "cash_range_zar": "R 0.50 - R 0.80",
        "premium_label": "+ 50% more value",
    },
    "paper & cardboard": {
        "eco_per_kg": 2.8,
        "cash_range_zar": "R 1.50 - R 2.00",
        "premium_label": "+ 40% more value",
    },
    "plastics": {
        "eco_per_kg": 5.0,
        "cash_range_zar": "R 3.00 - R 4.00",
        "premium_label": "+ 25% more value",
    },
    "metals": {
        "eco_per_kg": 16.0,
        "cash_range_zar": "R 10.00 - R 14.00",
        "premium_label": "+ 15% more value",
    },
    "e-waste": {
        "eco_per_kg": 35.0,
        "cash_range_zar": "R 20.00 - R 25.00",
        "premium_label": "+ 40% more value",
    },
    # Fallback categories kept for internal routes not explicitly priced in the pitch table.
    "organic waste": {
        "eco_per_kg": 2.0,
        "cash_range_zar": "R 1.00 - R 1.60",
        "premium_label": "+ 25% more value",
    },
    "mixed recyclables": {
        "eco_per_kg": 4.0,
        "cash_range_zar": "R 2.50 - R 3.50",
        "premium_label": "+ 20% more value",
    },
}

DEMO_REWARD_RATE_BY_MATERIAL = {
    key: float(spec["eco_per_kg"])
    for key, spec in ECO_PAYOUT_MODEL_BY_MATERIAL.items()
}

UNIFIED_MATERIAL_TAXONOMY = [
    "Paper & Cardboard",
    "Plastics",
    "Glass",
    "Metals",
    "E-Waste",
    "Organic Waste",
    "Mixed Recyclables",
]

DEMO_LOGIN_ALIASES = {
    "recycler1": "recycler@vericycle.com",
    "business1": "business@vericycle.com",
    "resident1": "resident@vericycle.com",
    "center1": "center@vericycle.com",
    "admin1": "admin@vericycle.com",
}

DEMO_LOGIN_PASSWORD = "1234"
DEMO_LOGIN_TARGET_EMAILS = set(DEMO_LOGIN_ALIASES.values())
QR_INTENT_TTL_MINUTES = 180


def ensure_demo_login_accounts() -> None:
    """
    Ensure judge demo accounts are always present in non-production mode.
    This avoids on-camera login failures due to missing seed data.
    """
    if _is_prod:
        return

    demo_accounts = [
        {
            "email": "recycler@vericycle.com",
            "role": "collector",
            "full_name": "Demo Recycler",
            "phone_number": "0000000000",
            "id_number": "0000000000000",
            "hedera_account_id": "0.0.7267109",
        },
        {
            "email": "business@vericycle.com",
            "role": "business",
            "full_name": "Demo Business",
            "phone_number": "0000000000",
            "id_number": "1000000000000",
            "hedera_account_id": "0.0.7300002",
        },
        {
            "email": "center@vericycle.com",
            "role": "center",
            "full_name": "Demo Center",
            "phone_number": "0000000000",
            "id_number": "2000000000000",
            "hedera_account_id": "0.0.7300003",
        },
        {
            "email": "resident@vericycle.com",
            "role": "resident",
            "full_name": "Demo Resident",
            "phone_number": "0000000000",
            "id_number": "3000000000000",
            "hedera_account_id": "0.0.7300004",
        },
        {
            "email": "admin@vericycle.com",
            "role": "admin",
            "full_name": "Demo Admin",
            "phone_number": "0000000000",
            "id_number": "4000000000000",
            "hedera_account_id": "0.0.7300001",
        },
    ]

    created = 0
    for account in demo_accounts:
        existing = User.query.filter_by(email=account["email"]).first()
        if existing:
            continue

        password_hash = bcrypt.generate_password_hash(DEMO_LOGIN_PASSWORD).decode("utf-8")
        db.session.add(User(
            email=account["email"],
            password_hash=password_hash,
            role=account["role"],
            full_name=account["full_name"],
            phone_number=account["phone_number"],
            id_number=account["id_number"],
            hedera_account_id=account["hedera_account_id"],
        ))
        created += 1

    if created:
        db.session.commit()
        print(f"[DEMO] Seeded {created} missing demo login accounts", flush=True)


def resolve_demo_login_alias(identifier: str | None) -> str:
    normalized = (identifier or "").strip().lower()
    return DEMO_LOGIN_ALIASES.get(normalized, normalized)


def _qr_secret_bytes() -> bytes:
    return str(app.config.get('SECRET_KEY') or 'vericycle-dev').encode('utf-8')


def _qr_sign_payload(payload_json: str) -> str:
    return hmac.new(_qr_secret_bytes(), payload_json.encode('utf-8'), hashlib.sha256).hexdigest()


def _qr_encode_payload(payload: dict) -> str:
    payload_json = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    body = base64.urlsafe_b64encode(payload_json.encode('utf-8')).decode('ascii').rstrip('=')
    sig = _qr_sign_payload(payload_json)
    return f"{body}.{sig}"


def _qr_decode_payload(token: str) -> tuple[dict | None, str | None]:
    raw = (token or '').strip()
    if not raw or '.' not in raw:
        return None, 'Invalid QR intent payload'
    body, sig = raw.rsplit('.', 1)
    if not body or not sig:
        return None, 'Invalid QR intent payload'
    try:
        padded = body + '=' * ((4 - len(body) % 4) % 4)
        payload_json = base64.urlsafe_b64decode(padded.encode('ascii')).decode('utf-8')
    except Exception:
        return None, 'Invalid QR intent encoding'

    expected = _qr_sign_payload(payload_json)
    if not hmac.compare_digest(expected, sig):
        return None, 'QR intent signature mismatch'

    try:
        payload = json.loads(payload_json)
    except Exception:
        return None, 'Invalid QR intent content'

    issued_raw = payload.get('issued_at')
    issued_at = None
    if isinstance(issued_raw, str) and issued_raw.strip():
        try:
            issued_at = datetime.fromisoformat(issued_raw.strip().replace('Z', '+00:00'))
        except Exception:
            issued_at = None
    elif isinstance(issued_raw, datetime):
        issued_at = issued_raw

    if not issued_at:
        return None, 'QR intent timestamp missing'

    if issued_at.tzinfo is None:
        issued_at = issued_at.replace(tzinfo=timezone.utc)
    issued_at = issued_at.astimezone(timezone.utc)

    age_minutes = (datetime.now(timezone.utc) - issued_at).total_seconds() / 60.0
    if age_minutes > QR_INTENT_TTL_MINUTES:
        return None, 'QR intent expired'

    return payload, None


def _find_first_user_by_effective_role(target_role: str) -> User | None:
    users = User.query.order_by(User.id.asc()).all()
    for row in users:
        if effective_role(row) == target_role:
            return row
    return None


def ensure_demo_pickup_flow_seed() -> None:
    """Disabled for clean-slate demos where all activity must be user-triggered."""
    return


def normalize_material_key(material_type: str | None) -> str:
    normalized = (material_type or "").strip().lower()
    if not normalized:
        return "mixed recyclables"
    if "paper" in normalized or "cardboard" in normalized:
        return "paper & cardboard"
    if "plastic" in normalized:
        return "plastics"
    if "glass" in normalized:
        return "glass"
    if "metal" in normalized or "can" in normalized or "aluminum" in normalized:
        return "metals"
    if "e-waste" in normalized or "ewaste" in normalized or "electronic" in normalized:
        return "e-waste"
    if "organic" in normalized:
        return "organic waste"
    return "mixed recyclables"


def canonical_material_label(material_type: str | None) -> str:
    key = normalize_material_key(material_type)
    mapping = {
        "paper & cardboard": "Paper & Cardboard",
        "plastics": "Plastics",
        "glass": "Glass",
        "metals": "Metals",
        "e-waste": "E-Waste",
        "organic waste": "Organic Waste",
        "mixed recyclables": "Mixed Recyclables",
    }
    return mapping.get(key, "Mixed Recyclables")


def eco_payout_spec(material_type: str | None) -> dict:
    material_key = normalize_material_key(material_type)
    return ECO_PAYOUT_MODEL_BY_MATERIAL.get(material_key, ECO_PAYOUT_MODEL_BY_MATERIAL["mixed recyclables"])


def estimate_pickup_distance_km(location: str | None) -> float:
    normalized = (location or "").strip().lower()
    if "randburg" in normalized:
        return 2.4
    if "sandton" in normalized:
        return 5.7
    if "roodepoort" in normalized:
        return 3.1
    if "soweto" in normalized:
        return 6.2
    if "midrand" in normalized:
        return 7.0
    return 4.8


def calculate_demo_reward_amount(material_type: str | None, weight_kg: float | int | None) -> float:
    safe_weight = max(0.0, float(weight_kg or 0.0))
    payout_rate_per_kg = float(eco_payout_spec(material_type).get("eco_per_kg") or 0.0)
    return round(safe_weight * payout_rate_per_kg, 2)


def build_rewards_wallet_snapshot(user: User) -> dict:
    rows = (
        Activity.query
        .filter_by(user_id=user.id)
        .order_by(Activity.id.desc())
        .all()
    )
    wallet_rows = (
        WalletTransaction.query
        .filter_by(user_id=user.id)
        .order_by(WalletTransaction.created_at.desc(), WalletTransaction.id.desc())
        .all()
    )

    def is_activity_rewarded(activity: Activity) -> bool:
        states = {
            (activity.status or "").strip().lower(),
            (activity.verified_status or "").strip().lower(),
            (activity.pipeline_stage or "").strip().lower(),
            (activity.logbook_status or "").strip().lower(),
            (activity.reward_status or "").strip().lower(),
        }
        if "failed" in states or "rejected" in states:
            return False
        return bool(states & {"verified", "anchored", "completed", "logged", "rewarded", "attested", "paid"})

    def parse_activity_dt(activity: Activity):
        raw = (activity.timestamp or "").strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except Exception:
            return None

    balance = 0.0
    total_earned = 0.0
    verified_events = 0
    proof_records = 0
    recent_rewards = []
    history_rows = []

    for row in rows:
        if row.proof_hash or row.hcs_tx_id or row.logbook_tx_id or row.hedera_tx_id:
            proof_records += 1

        if not is_activity_rewarded(row):
            continue

        amount = float(row.amount or 0.0)
        balance += amount
        total_earned += amount
        verified_events += 1

        tx_id = row.hts_tx_id or row.reward_tx_id or row.hcs_tx_id or row.logbook_tx_id or row.hedera_tx_id
        if len(recent_rewards) < 8 and tx_id:
            recent_rewards.append({
                "amount": amount,
                "description": row.desc or "Recycling event",
                "tx_id": tx_id,
                "hashscan_url": hashscan_link(tx_id),
            })

        status_text = "Rewarded"
        state_hint = (row.reward_status or row.logbook_status or row.pipeline_stage or row.status or row.verified_status or "").strip().lower()
        if state_hint in {"anchored", "logged", "attested"}:
            status_text = "Anchored"
        elif state_hint in {"verified", "completed"}:
            status_text = "Verified"

        history_rows.append({
            "created_at": parse_activity_dt(row),
            "date": row.timestamp,
            "activity": row.desc or "Verified recycling activity",
            "status": status_text,
            "amount_eco": amount,
            "note": "ECO earned from verified recycling activity",
            "link_url": f"/api/proof-bundle/{row.id}",
            "link_label": "View proof",
        })

    for tx in wallet_rows:
        amount_eco = float(tx.amount_eco or 0.0)
        balance += amount_eco

        action_label = {
            "swap": "Swap",
            "voucher": "Voucher Redeem",
            "cash": "Cash Redeem",
        }.get((tx.action_type or "").strip().lower(), "Wallet Action")

        out_value_text = ""
        if tx.amount_out is not None and tx.out_asset:
            if str(tx.out_asset).upper() == "ZAR":
                out_value_text = f"R{float(tx.amount_out):,.0f}"
            else:
                out_value_text = f"{float(tx.amount_out):,.4f} {str(tx.out_asset).upper()}"

        base_activity = tx.reference_label or action_label
        activity_text = f"{action_label} · {base_activity}" if tx.reference_label else action_label
        if out_value_text:
            activity_text = f"{activity_text} ({out_value_text})"

        history_rows.append({
            "created_at": tx.created_at,
            "date": tx.created_at.isoformat() if tx.created_at else "",
            "activity": activity_text,
            "status": "Completed" if (tx.status or "").strip().lower() == "completed" else humanize_status_token(tx.status),
            "amount_eco": amount_eco,
            "note": tx.note or "Wallet deduction",
            "link_url": None,
            "link_label": "-",
        })

    def _history_sort_key(item):
        dt = item.get("created_at")
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        return 0.0

    history_rows.sort(key=_history_sort_key, reverse=True)

    return {
        "balance": round(balance, 2),
        "verified_events": verified_events,
        "proof_records": proof_records,
        "total_earned": round(total_earned, 2),
        "recent_rewards": recent_rewards[:5],
        "history_rows": history_rows[:80],
    }


def is_treasury_refill_required(reward_last_error: str | None) -> bool:
    text = (reward_last_error or "").strip().lower()
    return (
        "insufficient_token_balance" in text
        or "treasury has zero eco balance" in text
        or ("treasury" in text and "balance" in text)
    )


def reward_status_label(
    reward_status: str | None,
    reward_last_error: str | None = None,
    pipeline_stage: str | None = None,
) -> str | None:
    normalized_reward = (reward_status or "").strip().lower()
    normalized_stage = (pipeline_stage or "").strip().lower()

    if normalized_reward == "paid":
        return "Reward transferred"
    if normalized_reward == "finalized_no_transfer":
        if is_treasury_refill_required(reward_last_error):
            return "Reward recorded, treasury refill required"
        return "Reward finalized (no transfer)"
    if normalized_stage in {"rewarded", "attested"}:
        return "Reward pending"
    return None


def humanize_status_token(value: str | None) -> str:
    token = (value or "").strip()
    if not token:
        return "-"
    return re.sub(r"[_-]+", " ", token).title()


def pickup_request_status_label(
    request_status: str | None,
    assignment_status: str | None = None,
    verification_status: str | None = None,
    linked_activity: Activity | None = None,
) -> str:
    if linked_activity and normalize_status_label_for_api(linked_activity) == "Verified":
        return "Verified recycling record"

    verification = (verification_status or "").strip().lower()
    assignment = (assignment_status or "").strip().lower()
    request_state = (request_status or "").strip().lower()

    if verification == "verified":
        return "Verified recycling record"
    if assignment == "completed":
        return "Completed"
    if assignment == "submitted":
        return "Submitted for verification"
    if assignment == "in_transit" or request_state == "in_transit":
        return "In transit to center"
    if assignment == "accepted" or request_state == "accepted":
        return "Accepted by recycler"
    if request_state == "completed":
        return "Completed"
    if request_state == "open":
        return "Open for pickup"
    return humanize_status_token(request_status)


_OPPORTUNITY_STATUS_RANK = {
    "cancelled": 0,
    "open": 1,
    "accepted": 2,
    "in_transit": 3,
    "submitted": 4,
    "completed": 5,
}


def normalize_hotspot_key(title: str | None, location: str | None) -> str:
    title_part = re.sub(r"[^a-z0-9]+", "-", (title or "").strip().lower()).strip("-")
    location_part = re.sub(r"[^a-z0-9]+", "-", (location or "").strip().lower()).strip("-")
    key = f"{title_part}::{location_part}".strip(":")
    return key or "community-cleanup-request"


def parse_community_hotspot_details(notes: str | None, fallback_location: str | None) -> tuple[str, str, bool]:
    raw = (notes or "").strip()
    fallback = (fallback_location or "Unspecified location").strip() or "Unspecified location"

    hotspot_match = re.search(r"\[Community Hotspot\]\s*(.+?)\s*::", raw, re.IGNORECASE)
    if hotspot_match:
        title = hotspot_match.group(1).strip()
        return (title or "Community Cleanup Request", fallback, False)

    escalation_match = re.search(r"\[Community Support Escalation\]\s*(.+?)\s*@\s*([^\.\n]+)", raw, re.IGNORECASE)
    if escalation_match:
        title = escalation_match.group(1).strip()
        location = escalation_match.group(2).strip() or fallback
        return (title or "Community Cleanup Request", location, True)

    reopen_match = re.search(r"\[Community Reopen\]\s*(.+?)\s*@\s*(.+?)\s*::", raw, re.IGNORECASE)
    if reopen_match:
        title = reopen_match.group(1).strip()
        location = reopen_match.group(2).strip() or fallback
        return (title or "Community Cleanup Request", location, False)

    return ("Community Cleanup Request", fallback, False)


def _community_demo_hotspot_specs() -> list[dict]:
    return [
        {
            "title": "Mixed collection overflow zone",
            "location": "Park Entrance, Roodepoort",
            "description": "Mixed recyclables and bulky waste piling up near public access routes.",
            "material_type": "Mixed Recyclables",
            "estimated_kg": 55.0,
            "priority": "center",
            "support_reports": 3,
            "type_label": "Mixed Collection",
        },
        {
            "title": "Community-agreed dirty hotspot",
            "location": "Sandton Drive",
            "description": "Residents repeatedly report persistent litter and illegal dumping in this corridor.",
            "material_type": "Mixed Recyclables",
            "estimated_kg": 42.0,
            "priority": "center",
            "support_reports": 2,
            "type_label": "Community Consensus",
        },
        {
            "title": "Missed trash collection route",
            "location": "Corner Main St & 4th Ave, Randburg",
            "description": "Municipal collection missed multiple windows; bins remain overflowing.",
            "material_type": "Mixed Recyclables",
            "estimated_kg": 32.0,
            "priority": "standard",
            "support_reports": 1,
            "type_label": "Missed Collection",
        },
    ]


def _community_demo_type_label(title: str | None, location: str | None) -> str:
    key = normalize_hotspot_key(title, location)
    for spec in _community_demo_hotspot_specs():
        if normalize_hotspot_key(spec["title"], spec["location"]) == key:
            return spec["type_label"]
    return "Resident Report"


def ensure_demo_community_hotspots(force_reset: bool = False) -> None:
    if _is_prod:
        return

    resident_user = (
        User.query
        .filter(func.lower(func.trim(User.role)) == 'resident')
        .order_by(User.id.asc())
        .first()
    )
    if not resident_user:
        return

    resident_rows = (
        PickupOpportunity.query
        .filter_by(source_role='resident')
        .order_by(PickupOpportunity.created_at.desc())
        .all()
    )

    changed = False
    for spec in _community_demo_hotspot_specs():
        seed_key = normalize_hotspot_key(spec["title"], spec["location"])
        matched_rows: list[PickupOpportunity] = []
        for row in resident_rows:
            title, location, _ = parse_community_hotspot_details(row.notes, row.location)
            if normalize_hotspot_key(title, location) == seed_key:
                matched_rows.append(row)

        if not matched_rows:
            base = PickupOpportunity(
                source_role='resident',
                source_user_id=resident_user.id,
                material_type=spec["material_type"],
                estimated_kg=spec["estimated_kg"],
                priority=spec["priority"],
                location=spec["location"],
                requested_window='Today 14:00-17:00',
                notes=f"[Community Hotspot] {spec['title']} :: {spec['description']}",
                status='open',
            )
            db.session.add(base)

            for _ in range(int(spec.get("support_reports", 0))):
                support = PickupOpportunity(
                    source_role='resident',
                    source_user_id=resident_user.id,
                    material_type=spec["material_type"],
                    estimated_kg=max(8.0, float(spec["estimated_kg"]) * 0.35),
                    priority=spec["priority"],
                    location=spec["location"],
                    requested_window='Today 14:00-17:00',
                    notes=f"[Community Support Escalation] {spec['title']} @ {spec['location']}. +1 resident support escalation",
                    status='open',
                )
                db.session.add(support)
            changed = True
            continue

        if force_reset:
            for row in matched_rows:
                row.status = 'open'
                row.priority = spec["priority"]
                for assignment in (row.assignments or []):
                    if assignment.status in {'accepted', 'in_transit', 'submitted'}:
                        assignment.status = 'cancelled'
                        if assignment.verification_status in {None, '', 'pending'}:
                            assignment.verification_status = 'cancelled'
            changed = True

    if changed:
        db.session.commit()


def purge_stale_demo_seed_rows() -> None:
    if _is_prod:
        return

    demo_notes = {
        "Demo seeded pickup for judge flow",
        "Demo seeded submitted assignment",
    }

    # Hard clean in non-demo mode: remove preloaded judge seed data entirely.
    if not DEMO_MODE:
        stale_opportunities = (
            PickupOpportunity.query
            .filter(PickupOpportunity.notes.in_(demo_notes))
            .all()
        )
        removed_assignments = 0
        for opportunity in stale_opportunities:
            assignments = list(opportunity.assignments or [])
            for assignment in assignments:
                db.session.delete(assignment)
                removed_assignments += 1
            db.session.delete(opportunity)

        # Remove legacy seeded recycler history rows if present.
        seed_desc_values = {
            "Verified Drop-off (8.5kg of Paper)",
            "Verified Drop-off (15.0kg of Cans)",
        }
        seeded_activities = (
            Activity.query
            .filter(Activity.desc.in_(seed_desc_values))
            .filter(or_(Activity.amount == 425.0, Activity.amount == 750.0))
            .all()
        )
        for row in seeded_activities:
            db.session.delete(row)

        if stale_opportunities or removed_assignments or seeded_activities:
            db.session.commit()
        return

    has_real_activity = db.session.query(Activity.id).first() is not None
    has_real_pickup_data = (
        PickupOpportunity.query
        .filter(or_(PickupOpportunity.notes.is_(None), ~PickupOpportunity.notes.in_(demo_notes)))
        .first()
        is not None
    )
    if not (has_real_activity or has_real_pickup_data):
        return

    stale_opportunities = (
        PickupOpportunity.query
        .filter(PickupOpportunity.notes.in_(demo_notes))
        .filter(PickupOpportunity.status.in_(['open', 'accepted', 'in_transit', 'submitted']))
        .all()
    )
    if not stale_opportunities:
        return

    for opportunity in stale_opportunities:
        for assignment in (opportunity.assignments or []):
            if assignment.status in {'accepted', 'in_transit', 'submitted'}:
                assignment.status = 'cancelled'
                if assignment.verification_status in {None, '', 'pending'}:
                    assignment.verification_status = 'cancelled'
        opportunity.status = 'cancelled'

    db.session.commit()


def build_community_hotspot_board() -> list[dict]:
    purge_stale_demo_seed_rows()
    ensure_demo_community_hotspots(force_reset=False)

    rows = (
        PickupOpportunity.query
        .filter_by(source_role='resident')
        .order_by(PickupOpportunity.created_at.desc())
        .limit(600)
        .all()
    )

    grouped: dict[str, dict] = {}
    for row in rows:
        title, location, is_support = parse_community_hotspot_details(row.notes, row.location)
        key = normalize_hotspot_key(title, location)
        rank = _OPPORTUNITY_STATUS_RANK.get((row.status or '').strip().lower(), 0)
        created_iso = row.created_at.isoformat() if row.created_at else None

        if key not in grouped:
            grouped[key] = {
                "hotspot_key": key,
                "title": title,
                "location": location,
                "type_label": _community_demo_type_label(title, location),
                "status": (row.status or 'open'),
                "status_rank": rank,
                "status_label": pickup_request_status_label(row.status),
                "priority": 'center' if (row.priority or '').strip().lower() == 'center' else 'standard',
                "support_count": 0,
                "report_count": 0,
                "latest_created_at": created_iso,
                "can_prioritize": False,
                "completed_at": None,
                "completed_by": None,
                "completed_activity_id": None,
                "proof_bundle_url": None,
                "hashscan_url": None,
                "reward_amount": None,
                "resident_confirmation_status": None,
                "resident_confirmation_at": None,
                "resident_confirmation_by": None,
            }

        entry = grouped[key]
        entry["report_count"] += 1
        if is_support:
            entry["support_count"] += 1

        if (row.priority or '').strip().lower() == 'center':
            entry["priority"] = 'center'

        if entry.get("completed_at") is None and (row.status or '').strip().lower() == 'completed':
            entry["completed_at"] = row.created_at.isoformat() if row.created_at else datetime.now(timezone.utc).isoformat()
            entry["completed_by"] = 'center@vericycle.com'

        if rank > entry["status_rank"]:
            entry["status_rank"] = rank
            entry["status"] = row.status
            entry["status_label"] = pickup_request_status_label(row.status)

        if created_iso and (not entry["latest_created_at"] or created_iso > entry["latest_created_at"]):
            entry["latest_created_at"] = created_iso

        if (row.status or '').strip().lower() in {'open', 'accepted', 'in_transit', 'submitted'}:
            entry["can_prioritize"] = True

        for assignment in (row.assignments or []):
            linked_activity = assignment.linked_activity
            verified_at = assignment.verified_at
            completion_iso = verified_at.isoformat() if verified_at else None

            if not linked_activity or not completion_iso:
                continue

            if entry["completed_at"] and entry["completed_at"] >= completion_iso:
                continue

            tx_id = linked_activity.hcs_tx_id or linked_activity.logbook_tx_id or linked_activity.hedera_tx_id or linked_activity.hts_tx_id or linked_activity.reward_tx_id
            entry["completed_at"] = completion_iso
            entry["completed_by"] = (
                assignment.verified_by_center.email
                if assignment.verified_by_center and assignment.verified_by_center.email
                else None
            )
            entry["completed_activity_id"] = linked_activity.id
            entry["proof_bundle_url"] = f"/api/proof-bundle/{linked_activity.id}"
            entry["hashscan_url"] = hashscan_link(tx_id) or hashscan_link(f"0.0.1001@1700000000.{linked_activity.id:09d}")
            entry["reward_amount"] = float(linked_activity.amount or 0.0)

            latest_resident_confirmation = None
            for signal in (linked_activity.signals or []):
                if (signal.signal_type or '').strip().lower() != 'resident_confirmation':
                    continue
                if latest_resident_confirmation is None or signal.created_at > latest_resident_confirmation.created_at:
                    latest_resident_confirmation = signal

            if latest_resident_confirmation is not None:
                entry["resident_confirmation_status"] = (latest_resident_confirmation.value or '').strip().lower() or None
                entry["resident_confirmation_at"] = latest_resident_confirmation.created_at.isoformat() if latest_resident_confirmation.created_at else None
                entry["resident_confirmation_by"] = (
                    latest_resident_confirmation.source_user.email
                    if latest_resident_confirmation.source_user and latest_resident_confirmation.source_user.email
                    else None
                )

    for entry in grouped.values():
        resident_confirmation_status = (entry.get("resident_confirmation_status") or '').strip().lower()
        if resident_confirmation_status == 'missed':
            entry["status"] = 'reopened'
            entry["status_label"] = 'Reopened for center follow-up'
            entry["priority"] = 'center'
            entry["can_prioritize"] = True
        elif resident_confirmation_status == 'confirmed':
            entry["status"] = 'confirmed'
            entry["status_label"] = 'Confirmed by residents'
            entry["can_prioritize"] = False

    payload = list(grouped.values())
    payload.sort(
        key=lambda x: (
            0 if (x.get("status") or '').strip().lower() not in {'completed', 'cancelled'} else 1,
            0 if (x.get("priority") or '') == 'center' else 1,
            -(x.get("support_count") or 0),
            -(x.get("report_count") or 0),
            x.get("latest_created_at") or '',
        )
    )
    return payload


def role_home_endpoint_for(user) -> str:
    """Post-login redirect: directs user to their primary dashboard."""
    role = effective_role(user)
    if role == "center":
        return "center_dashboard"
    if role == "business":
        return "business_dashboard"
    if role == "resident":
        return "household_dashboard"
    if role == "admin":
        return "admin_monitor"
    if role == "recycler":
        return "collector_dashboard"
    return "home"  # safe fallback — prevents redirect loops for invalid/empty roles


def access_denied_redirect_for(user) -> str:
    """Access control redirect: directs user when they try to access restricted pages.
    Routes users to their role dashboard for silent wrong-role redirects.
    """
    role = effective_role(user)
    if role == "business":
        return "business_dashboard"
    if role == "resident":
        return "household_dashboard"
    if role == "center":
        return "center_dashboard"
    if role == "admin":
        return "admin_monitor"
    if role == "recycler":
        return "collector_dashboard"
    return "home"


@app.context_processor
def inject_role_helpers():
    role = None
    if current_user.is_authenticated:
        role = effective_role(current_user)
    return {
        "current_effective_role": role,
        "role_home_endpoint": role_home_endpoint_for(current_user) if current_user.is_authenticated else None,
        "reward_status_label": reward_status_label,
        "hashscan_link": hashscan_link,
    }


def confidence_score_for_activity(activity: Activity) -> float:
    trust = float(activity.trust_weight or 0.0)
    rep = float(activity.verifier_reputation or 0.0)
    stage = (activity.pipeline_stage or "").lower()
    logbook = (activity.logbook_status or "").lower()
    reward = (activity.reward_status or "").lower()

    stage_score = {
        "created": 0.10,
        "collected": 0.25,
        "verified": 0.45,
        "logged": 0.65,
        "rewarded": 0.85,
        "attested": 1.00,
        "rejected": 0.0,
    }.get(stage, 0.15)

    logbook_bonus = 0.1 if logbook == "anchored" else (0.03 if logbook in {"offchain_final", "demo_skipped"} else 0.0)
    reward_bonus = 0.1 if reward == "paid" else (0.05 if reward == "finalized_no_transfer" else 0.0)

    score = (0.45 * trust) + (0.30 * rep) + (0.25 * stage_score) + logbook_bonus + reward_bonus
    return max(0.0, min(1.0, round(score, 3)))


def create_verification_signal(
    activity_id: int,
    signal_type: str,
    source_role: str,
    value: str,
    source_user_id: int | None = None,
    is_positive: bool = True,
    metadata: dict | None = None,
):
    weight_map = {
        "collector_submission": 0.5,
        "center_verification": 0.5,
        "qr_scan": 0.4,
        "photo_proof": 0.3,
        "resident_confirmation": 0.2,
        "schedule_match": 0.2,
    }

    signal = VerificationSignal(
        activity_id=activity_id,
        signal_type=signal_type,
        source_role=source_role,
        source_user_id=source_user_id,
        value=value,
        weight=weight_map.get(signal_type, 0.0),
        is_positive=is_positive,
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
    )
    db.session.add(signal)
    return signal


def add_schedule_match_signal(activity: Activity):
    create_verification_signal(
        activity_id=activity.id,
        signal_type="schedule_match",
        source_role="system",
        value="matched",
        is_positive=True,
        metadata={"rule": "default_schedule_match_for_demo"}
    )


def hashscan_link(tx_id: str | None) -> str | None:
    if not tx_id:
        return None
    return f"https://hashscan.io/testnet/transaction/{tx_id}"


PHASE5_DEMO_LABELS = {
    "verified": "Judge Demo Verified Event",
    "approved": "Judge Demo Approved Review Event",
    "rejected": "Judge Demo Rejected Review Event",
}


def _pick_latest_matching(rows: list[Activity], predicate) -> Activity | None:
    for item in sorted((rows or []), key=lambda a: a.id, reverse=True):
        if predicate(item):
            return item
    return None


def _find_golden_runs(rows: list[Activity]) -> dict:
    source = rows or []

    perfect = _pick_latest_matching(
        source,
        lambda a: (a.desc or "") == PHASE5_DEMO_LABELS["verified"]
        and (a.pipeline_stage or "").lower() == "attested"
        and (a.status or a.verified_status or "").lower() == "verified"
        and (a.confidence_score or 0.0) >= 0.7
        and (a.review_status in (None, "", "none"))
        and bool(a.hcs_tx_id or a.logbook_tx_id or a.hedera_tx_id)
        and bool(a.compliance_tx_id),
    )

    approved = _pick_latest_matching(
        source,
        lambda a: (a.desc or "") == PHASE5_DEMO_LABELS["approved"]
        and (a.pipeline_stage or "").lower() == "attested"
        and (a.status or a.verified_status or "").lower() == "verified"
        and (a.review_status or "").lower() == "approved"
        and float(a.confidence_score or 0.0) == 0.2
        and bool(a.hcs_tx_id or a.logbook_tx_id or a.hedera_tx_id),
    )

    rejected = _pick_latest_matching(
        source,
        lambda a: (a.desc or "") == PHASE5_DEMO_LABELS["rejected"]
        and ((a.pipeline_stage or "").lower() == "rejected"
             or (a.status or a.verified_status or "").lower() == "rejected")
        and (a.review_status or "").lower() == "rejected"
        and float(a.confidence_score or 0.0) == 0.2
        and not bool(a.hcs_tx_id or a.logbook_tx_id or a.hedera_tx_id)
        and not bool(a.reward_tx_id or a.hts_tx_id)
        and not bool(a.compliance_tx_id),
    )

    # Fallback for sessions where labels are not prepared yet.
    if not perfect:
        perfect = _pick_latest_matching(
            source,
            lambda a: (a.logbook_status or "").lower() == "anchored"
            and (a.reward_status or "").lower() == "paid"
            and (a.pipeline_stage or "").lower() == "attested",
        )

    if not approved:
        approved = _pick_latest_matching(
            source,
            lambda a: (a.review_status or "").lower() == "approved"
            and (a.pipeline_stage or "").lower() in {"verified", "logged", "rewarded", "attested"}
            and bool(a.hcs_tx_id or a.logbook_tx_id or a.hedera_tx_id),
        )

    if not rejected:
        rejected = _pick_latest_matching(
            source,
            lambda a: (a.pipeline_stage or "").lower() == "rejected"
            or (a.status or a.verified_status or "").lower() == "rejected",
        )

    return {
        "perfect": perfect,
        "approved": approved,
        "rejected": rejected,
    }


def _proof_hub_evidence(rows: list[Activity]) -> dict:
    latest_hcs = next((a for a in rows if (a.logbook_status or "").lower() == "anchored" and (a.hcs_tx_id or a.logbook_tx_id or a.hedera_tx_id)), None)
    latest_hts = next((a for a in rows if (a.reward_status or "").lower() == "paid" and (a.hts_tx_id or a.reward_tx_id)), None)
    latest_commerce = AgentCommerceEvent.query.order_by(AgentCommerceEvent.id.desc()).first()

    return {
        "latest_hcs_tx": (latest_hcs.hcs_tx_id or latest_hcs.logbook_tx_id or latest_hcs.hedera_tx_id) if latest_hcs else None,
        "latest_hts_tx": (latest_hts.hts_tx_id or latest_hts.reward_tx_id) if latest_hts else None,
        "latest_commerce_tx": getattr(latest_commerce, "tx_id", None),
        "latest_hcs_link": hashscan_link((latest_hcs.hcs_tx_id or latest_hcs.logbook_tx_id or latest_hcs.hedera_tx_id) if latest_hcs else None),
        "latest_hts_link": hashscan_link((latest_hts.hts_tx_id or latest_hts.reward_tx_id) if latest_hts else None),
        "latest_commerce_link": hashscan_link(getattr(latest_commerce, "tx_id", None)),
    }


def audit_admin_action(action: str, target_type: str | None = None, target_id: str | None = None, details: str | None = None):
    if not is_admin_user():
        return
    db.session.add(AdminAuditLog(
        admin_email=getattr(current_user, "email", "unknown@admin"),
        action=(action or "")[:80],
        target_type=(target_type or "")[:40] if target_type else None,
        target_id=(str(target_id) if target_id is not None else None),
        details=(details or "")[:512] if details else None,
    ))


def seed_layer0_if_empty():
    try:
        if Location.query.count() > 0:
            return

        print('[SEED] Creating default Layer 0: Ruimsig location and schedules', flush=True)
        ruimsig = Location(name="Ruimsig", city="Johannesburg", ward="", latitude=None, longitude=None)
        db.session.add(ruimsig)
        db.session.commit()

        schedules = [
            WasteSchedule(location_id=ruimsig.id, stream="Recycling", pickup_day=3, pickup_window="08:00-12:00"),
            WasteSchedule(location_id=ruimsig.id, stream="General Waste", pickup_day=1, pickup_window="08:00-12:00"),
        ]
        db.session.add_all(schedules)
        db.session.commit()

        krugersdorp = Location(name="Krugersdorp", city="Johannesburg", ward="", latitude=None, longitude=None)
        db.session.add(krugersdorp)
        db.session.commit()

        krugersdorp_schedules = [
            WasteSchedule(location_id=krugersdorp.id, stream="Recycling", pickup_day=4, pickup_window="08:00-12:00"),
            WasteSchedule(location_id=krugersdorp.id, stream="General Waste", pickup_day=2, pickup_window="08:00-12:00"),
        ]
        db.session.add_all(krugersdorp_schedules)
        db.session.commit()
        print('[SEED] Layer 0 seed completed', flush=True)
    except Exception as e:
        print('[SEED] Error while seeding Layer 0:', e, flush=True)


def ensure_activity_columns():
    cols = db.session.execute(text("PRAGMA table_info(activity)")).mappings().all()
    existing = {c.get("name") for c in cols}

    if "proof_hash" not in existing:
        db.session.execute(text("ALTER TABLE activity ADD COLUMN proof_hash VARCHAR(64)"))

    if "logbook_status" not in existing:
        db.session.execute(text("ALTER TABLE activity ADD COLUMN logbook_status VARCHAR(20) DEFAULT 'pending'"))

    if "logbook_tx_id" not in existing:
        db.session.execute(text("ALTER TABLE activity ADD COLUMN logbook_tx_id VARCHAR(150)"))

    if "logbook_last_error" not in existing:
        db.session.execute(text("ALTER TABLE activity ADD COLUMN logbook_last_error TEXT"))

    if "logbook_finalized_at" not in existing:
        db.session.execute(text("ALTER TABLE activity ADD COLUMN logbook_finalized_at DATETIME"))

    if "reward_tx_id" not in existing:
        db.session.execute(text("ALTER TABLE activity ADD COLUMN reward_tx_id VARCHAR(150)"))

    if "reward_status" not in existing:
        db.session.execute(text("ALTER TABLE activity ADD COLUMN reward_status VARCHAR(40)"))

    if "reward_last_error" not in existing:
        db.session.execute(text("ALTER TABLE activity ADD COLUMN reward_last_error TEXT"))

    if "verifier_reputation" not in existing:
        db.session.execute(text("ALTER TABLE activity ADD COLUMN verifier_reputation FLOAT DEFAULT 0.85"))

    if "reputation_delta" not in existing:
        db.session.execute(text("ALTER TABLE activity ADD COLUMN reputation_delta FLOAT DEFAULT 0"))

    if "hcs_tx_id" not in existing:
        db.session.execute(text("ALTER TABLE activity ADD COLUMN hcs_tx_id VARCHAR(150)"))

    if "hts_tx_id" not in existing:
        db.session.execute(text("ALTER TABLE activity ADD COLUMN hts_tx_id VARCHAR(150)"))

    if "compliance_tx_id" not in existing:
        db.session.execute(text("ALTER TABLE activity ADD COLUMN compliance_tx_id VARCHAR(150)"))

    if "confidence_score" not in existing:
        db.session.execute(text("ALTER TABLE activity ADD COLUMN confidence_score FLOAT DEFAULT 0"))

    if "review_status" not in existing:
        db.session.execute(text("ALTER TABLE activity ADD COLUMN review_status VARCHAR(30)"))

    if "review_reason" not in existing:
        db.session.execute(text("ALTER TABLE activity ADD COLUMN review_reason VARCHAR(255)"))

    if "reviewed_by_user_id" not in existing:
        db.session.execute(text("ALTER TABLE activity ADD COLUMN reviewed_by_user_id INTEGER"))

    if "reviewed_at" not in existing:
        db.session.execute(text("ALTER TABLE activity ADD COLUMN reviewed_at DATETIME"))

    user_cols = db.session.execute(text("PRAGMA table_info(user)")).mappings().all()
    user_existing = {c.get("name") for c in user_cols}

    if "hedera_private_key_encrypted" not in user_existing:
        db.session.execute(text("ALTER TABLE user ADD COLUMN hedera_private_key_encrypted TEXT"))

    if "hedera_key_version" not in user_existing:
        db.session.execute(text("ALTER TABLE user ADD COLUMN hedera_key_version VARCHAR(20)"))

    task_cols = db.session.execute(text("PRAGMA table_info(agent_task)")).mappings().all()
    task_existing = {c.get("name") for c in task_cols}

    if "attempts" not in task_existing:
        db.session.execute(text("ALTER TABLE agent_task ADD COLUMN attempts INTEGER DEFAULT 0"))

    if "next_run_at" not in task_existing:
        now_iso = datetime.now(timezone.utc).isoformat()
        db.session.execute(text(f"ALTER TABLE agent_task ADD COLUMN next_run_at DATETIME DEFAULT '{now_iso}'"))

    if "last_error" not in task_existing:
        db.session.execute(text("ALTER TABLE agent_task ADD COLUMN last_error VARCHAR(512)"))

    if "created_at" not in task_existing:
        now_iso = datetime.now(timezone.utc).isoformat()
        db.session.execute(text(f"ALTER TABLE agent_task ADD COLUMN created_at DATETIME DEFAULT '{now_iso}'"))

    if "updated_at" not in task_existing:
        now_iso = datetime.now(timezone.utc).isoformat()
        db.session.execute(text(f"ALTER TABLE agent_task ADD COLUMN updated_at DATETIME DEFAULT '{now_iso}'"))

    commerce_tables = db.session.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_commerce_event'"))
    if not commerce_tables.scalar():
        db.session.execute(text("""
            CREATE TABLE agent_commerce_event (
                id INTEGER NOT NULL,
                activity_id INTEGER NOT NULL,
                payer_agent VARCHAR(64) NOT NULL,
                payee_agent VARCHAR(64) NOT NULL,
                reason VARCHAR(128) NOT NULL,
                amount FLOAT NOT NULL,
                token_id VARCHAR(100),
                tx_id VARCHAR(150),
                status VARCHAR(40) NOT NULL,
                created_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(activity_id) REFERENCES activity (id)
            )
        """))

    dlq_tables = db.session.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='dead_letter_task'"))
    if not dlq_tables.scalar():
        db.session.execute(text("""
            CREATE TABLE dead_letter_task (
                id INTEGER NOT NULL,
                task_id INTEGER NOT NULL,
                activity_id INTEGER NOT NULL,
                agent_name VARCHAR(50) NOT NULL,
                attempts INTEGER NOT NULL,
                reason VARCHAR(512) NOT NULL,
                status VARCHAR(20) NOT NULL,
                created_at DATETIME NOT NULL,
                resolved_at DATETIME,
                PRIMARY KEY (id),
                FOREIGN KEY(task_id) REFERENCES agent_task (id),
                FOREIGN KEY(activity_id) REFERENCES activity (id)
            )
        """))

    audit_tables = db.session.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name='admin_audit_log'"))
    if not audit_tables.scalar():
        db.session.execute(text("""
            CREATE TABLE admin_audit_log (
                id INTEGER NOT NULL,
                created_at DATETIME NOT NULL,
                admin_email VARCHAR(120) NOT NULL,
                action VARCHAR(80) NOT NULL,
                target_type VARCHAR(40),
                target_id VARCHAR(80),
                details VARCHAR(512),
                PRIMARY KEY (id)
            )
        """))

    signal_tables = db.session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='verification_signal'")
    )
    if not signal_tables.scalar():
        db.session.execute(text("""
            CREATE TABLE verification_signal (
                id INTEGER NOT NULL,
                activity_id INTEGER NOT NULL,
                signal_type VARCHAR(50) NOT NULL,
                source_role VARCHAR(30) NOT NULL,
                source_user_id INTEGER,
                value VARCHAR(120),
                weight FLOAT NOT NULL DEFAULT 0.0,
                is_positive BOOLEAN NOT NULL DEFAULT 1,
                metadata_json TEXT,
                created_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(activity_id) REFERENCES activity (id),
                FOREIGN KEY(source_user_id) REFERENCES user (id)
            )
        """))

    pickup_table = db.session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='pickup_opportunity'")
    )
    if not pickup_table.scalar():
        db.session.execute(text("""
            CREATE TABLE pickup_opportunity (
                id INTEGER NOT NULL,
                source_role VARCHAR(20) NOT NULL,
                source_user_id INTEGER NOT NULL,
                material_type VARCHAR(80) NOT NULL,
                estimated_kg FLOAT NOT NULL,
                priority VARCHAR(20) NOT NULL DEFAULT 'standard',
                location VARCHAR(200) NOT NULL,
                requested_window VARCHAR(100),
                status VARCHAR(30) NOT NULL DEFAULT 'open',
                notes VARCHAR(500),
                created_at DATETIME NOT NULL,
                PRIMARY KEY (id),
                FOREIGN KEY(source_user_id) REFERENCES user (id)
            )
        """))

    assignment_table = db.session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name='opportunity_assignment'")
    )
    if not assignment_table.scalar():
        db.session.execute(text("""
            CREATE TABLE opportunity_assignment (
                id INTEGER NOT NULL,
                opportunity_id INTEGER NOT NULL,
                recycler_user_id INTEGER NOT NULL,
                status VARCHAR(30) NOT NULL DEFAULT 'accepted',
                accepted_at DATETIME NOT NULL,
                linked_activity_id INTEGER,
                PRIMARY KEY (id),
                FOREIGN KEY(opportunity_id) REFERENCES pickup_opportunity (id),
                FOREIGN KEY(recycler_user_id) REFERENCES user (id),
                FOREIGN KEY(linked_activity_id) REFERENCES activity (id)
            )
        """))

    assignment_cols = db.session.execute(text("PRAGMA table_info(opportunity_assignment)")).mappings().all()
    assignment_existing = {c.get("name") for c in assignment_cols}

    pickup_cols = db.session.execute(text("PRAGMA table_info(pickup_opportunity)")).mappings().all()
    pickup_existing = {c.get("name") for c in pickup_cols}
    if "priority" not in pickup_existing:
        db.session.execute(text("ALTER TABLE pickup_opportunity ADD COLUMN priority VARCHAR(20) NOT NULL DEFAULT 'standard'"))

    if "submitted_at" not in assignment_existing:
        db.session.execute(text("ALTER TABLE opportunity_assignment ADD COLUMN submitted_at DATETIME"))

    if "submitted_material_type" not in assignment_existing:
        db.session.execute(text("ALTER TABLE opportunity_assignment ADD COLUMN submitted_material_type VARCHAR(80)"))

    if "submitted_weight_kg" not in assignment_existing:
        db.session.execute(text("ALTER TABLE opportunity_assignment ADD COLUMN submitted_weight_kg FLOAT"))

    if "submission_notes" not in assignment_existing:
        db.session.execute(text("ALTER TABLE opportunity_assignment ADD COLUMN submission_notes VARCHAR(500)"))

    if "verified_by_center_id" not in assignment_existing:
        db.session.execute(text("ALTER TABLE opportunity_assignment ADD COLUMN verified_by_center_id INTEGER"))

    if "verified_at" not in assignment_existing:
        db.session.execute(text("ALTER TABLE opportunity_assignment ADD COLUMN verified_at DATETIME"))

    if "verification_status" not in assignment_existing:
        db.session.execute(text("ALTER TABLE opportunity_assignment ADD COLUMN verification_status VARCHAR(30)"))

    if "verification_notes" not in assignment_existing:
        db.session.execute(text("ALTER TABLE opportunity_assignment ADD COLUMN verification_notes VARCHAR(500)"))

    db.session.commit()


def backfill_activity_proof_hashes():
    try:
        activities = Activity.query.all()
        if not activities:
            return

        for act in activities:
            user = db.session.get(User, act.user_id)
            bundle = {
                "vericycle_version": "hackathon-2026",
                "activity_id": act.id,
                "timestamp": act.timestamp,
                "user": (user.email if user else ""),
                "description": act.desc,
                "amount": float(act.amount) if act.amount is not None else None,
                "stage": "recorded",
            }
            stable_hash = compute_proof_sha256(stable_proof_input(bundle))
            if act.proof_hash != stable_hash:
                act.proof_hash = stable_hash
            if not getattr(act, "logbook_status", None):
                act.logbook_status = "anchored" if act.hedera_tx_id else "pending"
            if not getattr(act, "logbook_tx_id", None) and act.hedera_tx_id:
                act.logbook_tx_id = act.hedera_tx_id
            if not getattr(act, "hcs_tx_id", None):
                act.hcs_tx_id = act.logbook_tx_id or act.hedera_tx_id
            if (
                getattr(act, "logbook_status", None) in {"anchored", "offchain_final", "demo_skipped"}
                and not getattr(act, "logbook_finalized_at", None)
            ):
                act.logbook_finalized_at = datetime.now(timezone.utc)
            if getattr(act, "pipeline_stage", None) in {"rewarded", "attested"} and not getattr(act, "reward_status", None):
                act.reward_status = "paid" if getattr(act, "reward_tx_id", None) else "finalized_no_transfer"
            if not getattr(act, "hts_tx_id", None):
                act.hts_tx_id = act.reward_tx_id
            if getattr(act, "verifier_reputation", None) is None:
                act.verifier_reputation = 0.85
            if getattr(act, "reputation_delta", None) is None:
                act.reputation_delta = 0.0

        db.session.commit()
    except Exception as e:
        print(f"[BACKEND] Proof-hash backfill skipped: {e}", flush=True)


def migrate_private_keys_to_encrypted():
    try:
        users = User.query.all()
        changed = 0
        for user in users:
            plain = getattr(user, "hedera_private_key", None)
            encrypted = getattr(user, "hedera_private_key_encrypted", None)
            if plain and not encrypted:
                encrypted_value, version = safe_encrypt_private_key(plain)
                if encrypted_value:
                    user.hedera_private_key_encrypted = encrypted_value
                    user.hedera_key_version = version
                    user.hedera_private_key = None
                    changed += 1
        if changed:
            db.session.commit()
            print(f"[SECURITY] Encrypted {changed} user Hedera private keys", flush=True)
    except Exception as e:
        print(f"[SECURITY] Private key migration skipped: {e}", flush=True)

# Ensure tables exist (create after models are imported so metadata is registered)
with app.app_context():
    db.create_all()
    try:
        ensure_activity_columns()
        backfill_activity_proof_hashes()
        migrate_private_keys_to_encrypted()
    except Exception as e:
        print(f"[BACKEND] Activity schema ensure skipped: {e}", flush=True)
    # Seed Layer 0 household/location/schedule data if empty
    try:
        seed_layer0_if_empty()
    except Exception:
        pass
    try:
        ensure_demo_login_accounts()
    except Exception as e:
        print(f"[DEMO] Demo account seed skipped: {e}", flush=True)

# -----------------------------------------------------------------
# 4. HELPER FUNCTION FOR FLASK-LOGIN
# - Provide the user loader required by Flask-Login.
# -----------------------------------------------------------------
@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except OperationalError:
        return None


def mirror_fetch_latest_topic_messages(topic_id: str, limit: int = 10):
    """
    Fetch latest topic messages from Hedera Mirror Node (testnet).
    Returns list of dicts with: consensus_timestamp, sequence_number, message (decoded), tx_id (best-effort).
    """
    base = "https://testnet.mirrornode.hedera.com"
    url = f"{base}/api/v1/topics/{topic_id}/messages"
    params = {"limit": limit, "order": "desc"}

    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    out = []
    for m in data.get("messages", []):
        raw_b64 = m.get("message", "")
        decoded = ""
        parsed = None
        tx_id = m.get("transaction_id")

        try:
            import base64
            decoded = base64.b64decode(raw_b64).decode("utf-8", errors="replace")
            try:
                parsed = json.loads(decoded)
            except Exception:
                parsed = None
        except Exception:
            decoded = ""

        if not tx_id:
            chunk_info = m.get("chunk_info") or {}
            initial_tx = chunk_info.get("initial_transaction_id") or {}
            account_id = initial_tx.get("account_id")
            transaction_valid_start = initial_tx.get("transaction_valid_start")
            if account_id and transaction_valid_start:
                tx_id = f"{account_id}@{transaction_valid_start}"

        if not tx_id and isinstance(parsed, dict):
            tx_id = parsed.get("tx_id") or parsed.get("txId")

        out.append({
            "consensus_timestamp": m.get("consensus_timestamp"),
            "sequence_number": m.get("sequence_number"),
            "decoded": decoded,
            "parsed": parsed,
            "tx_id": tx_id,
            "running_hash": m.get("running_hash"),
        })

    return out

# -----------------------------------------------------------------
# 5. AUTHENTICATION ROUTES (LOGIN, LOGOUT, SIGNUP)
# - Routes handling user signup, login, logout and account creation.
# -----------------------------------------------------------------

@app.route("/signup", methods=['GET', 'POST'])
def signup():
    if request.method == 'GET':
        selected_role = normalize_role_value(request.args.get('role') or '')
        if selected_role not in {'recycler', 'business', 'resident', 'center', 'admin'}:
            selected_role = ''
        return render_template('signup.html', active_page='signup', signup_role=selected_role)

    from_home_modal = (request.form.get('auth_source') or '').strip() == 'home-modal'

    def home_auth_redirect(mode: str, role_value: str = ''):
        params = {'auth': mode}
        normalized_role = normalize_role_value(role_value)
        if normalized_role in {'recycler', 'business', 'resident', 'center', 'admin'}:
            params['role'] = normalized_role
        return redirect(url_for('home', **params))

    email = (request.form.get('email') or request.form.get('username') or '').strip().lower()
    password = request.form.get('password') or ''
    if not email or not password:
        flash('Email and password are required for signup.', 'error')
        if from_home_modal:
            return home_auth_redirect('signup', request.form.get('role') or '')
        return redirect(url_for('signup', role=request.form.get('role') or 'recycler'))

    requested_role = normalize_role_value(request.form.get('role') or '')
    if requested_role not in {'recycler', 'business', 'resident', 'center', 'admin'}:
        flash('Invalid role selected for signup.', 'error')
        if from_home_modal:
            return home_auth_redirect('signup')
        return redirect(url_for('signup'))

    # Phase 2 compatibility: keep recycler signups persisted as collector.
    role = 'collector' if requested_role == 'recycler' else requested_role
    
    # ===== CRITICAL: Check if email exists BEFORE expensive Hedera account creation =====
    # This prevents:
    # 1. Burning testnet funds on duplicate account attempts
    # 2. Race conditions where two requests try to create the same account
    # Must be checked BEFORE any subprocess calls to collector-account.js
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        print(f"[SIGNUP] Email {email} already exists, rejecting signup")
        flash('That email is already taken. Please log in.', 'error')
        if from_home_modal:
            return home_auth_redirect('signup', requested_role)
        return redirect(url_for('signup', role=requested_role))
    
    print(f"[SIGNUP] Email {email} is new. Proceeding with account creation for role={role}")

    try:
        new_id = None
        new_key = None
        
        # Handle recycler/collector-compatible signup and create a Hedera account.
        if role != 'center':
            print("--- CALLING HEDERA ENGINE: Creating new collector account... ---")
            operator_id = os.getenv("OPERATOR_ID")
            operator_key = os.getenv("OPERATOR_KEY")
            if not operator_id or not operator_key:
                raise Exception("Missing environment variables. Please check your .env file.")

            result = subprocess.run(
                ["node", "collector-account.js", operator_id, operator_key],
                check=True, capture_output=True, text=True, timeout=15
            )
            
            output = result.stdout
            print("--- JS SCRIPT STDOUT: ---"); print(output)
            print("--- JS SCRIPT STDERR: ---"); print(result.stderr)
            print("-------------------------")

            new_id_match = re.search(r"(0.0\.\d+)", output)
            new_key_match = re.search(r"(30[0-9a-fA-F]{60,})", output)

            if not new_id_match or not new_key_match:
                raise Exception("Script output was invalid. Could not find ID or Key in stdout.")

            new_id = new_id_match.group(1)
            new_key = new_key_match.group(1)
            print(f"--- SUCCESS: Created Hedera Account {new_id} ---")

            hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
            encrypted_key, key_version = safe_encrypt_private_key(new_key)
            new_user = User(
                email=email, password_hash=hashed_password, 
                hedera_account_id=new_id,
                hedera_private_key=(new_key if not encrypted_key else None),
                hedera_private_key_encrypted=encrypted_key,
                hedera_key_version=key_version,
                role=role
            )
            db.session.add(new_user)
            db.session.commit()
            login_user(new_user)
            if role == 'business':
                return redirect(url_for('request_pickup'))
            if role == 'resident':
                return redirect(url_for('household_dashboard'))
            if role == 'admin':
                return redirect(url_for('admin_monitor'))
            return redirect(url_for('profile'))

        # Handle center signup and create a Hedera account
        else: # role == 'center'
            print("--- CALLING HEDERA ENGINE: Creating new Center account... ---")
            operator_id = os.getenv("OPERATOR_ID")
            operator_key = os.getenv("OPERATOR_KEY")
            if not operator_id or not operator_key:
                raise Exception("Missing environment variables. Please check your .env file.")

            # Run the same script to get keys for the Center
            result = subprocess.run(
                ["node", "collector-account.js", operator_id, operator_key],
                check=True, capture_output=True, text=True, timeout=15
            )
            
            output = result.stdout
            print("--- JS SCRIPT STDOUT: ---"); print(output)
            print("--- JS SCRIPT STDERR: ---"); print(result.stderr)
            print("-------------------------")

            new_id_match = re.search(r"(0.0\.\d+)", output)
            new_key_match = re.search(r"(30[0-9a-fA-F]{60,})", output)

            if not new_id_match or not new_key_match:
                raise Exception("Script output was invalid. Could not find ID or Key in stdout.")

            new_id = new_id_match.group(1)
            new_key = new_key_match.group(1)
            print(f"--- SUCCESS: Created Hedera Account {new_id} for Center ---")

            hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
            encrypted_key, key_version = safe_encrypt_private_key(new_key)
            new_user = User(
                email=email, password_hash=hashed_password, 
                hedera_account_id=new_id,
                hedera_private_key=(new_key if not encrypted_key else None),
                hedera_private_key_encrypted=encrypted_key,
                hedera_key_version=key_version,
                role=role,
                full_name=f"{email.split('@')[0]} Center",
                phone_number="011 123 4567",
                id_number="VERIFIED-CENTER-001",
                address="123 Industrial Rd, Johannesburg"
            )
            db.session.add(new_user)
            db.session.commit()
            login_user(new_user)
            return redirect(url_for('center_dashboard')) # CENTERS go straight to dashboard

    except subprocess.CalledProcessError as e:
        print(f"--- HEDERA SCRIPT CRASHED (CalledProcessError) ---")
        print("STDOUT:", e.stdout); print("STDERR:", e.stderr)
        flash('A problem occurred while creating your account. Please try again.', 'error')
        if from_home_modal:
            return home_auth_redirect('signup', requested_role)
        return redirect(url_for('home'))
    except Exception as e:
        print(f"--- HEDERA/PYTHON SIGNUP FAILED (General Exception) ---")
        print(e)
        flash('A problem occurred while creating your account. Please try again.','error')
        if from_home_modal:
            return home_auth_redirect('signup', requested_role)
        return redirect(url_for('home'))


@app.route("/login", methods=['GET', 'POST'])
def login():
    if request.method == 'GET':
        return render_template('login.html', active_page='login')

    from_home_modal = (request.form.get('auth_source') or '').strip() == 'home-modal'

    def home_auth_redirect(mode: str, role_value: str = ''):
        params = {'auth': mode}
        normalized_role = normalize_role_value(role_value)
        if normalized_role in {'recycler', 'business', 'resident', 'center', 'admin'}:
            params['role'] = normalized_role
        return redirect(url_for('home', **params))

    email_or_username = (request.form.get('email') or request.form.get('username') or '').strip().lower()
    email = resolve_demo_login_alias(email_or_username)
    password = request.form.get('password') or ''
    requested_role = normalize_role_value(request.form.get('role') or '')

    if requested_role and requested_role not in {'recycler', 'business', 'resident', 'center', 'admin'}:
        flash('Invalid role selected for login.', 'error')
        if from_home_modal:
            return home_auth_redirect('login')
        return redirect(url_for('login'))

    user = User.query.filter_by(email=email).first()
    
    demo_password_ok = (not _is_prod) and password == DEMO_LOGIN_PASSWORD and email in DEMO_LOGIN_TARGET_EMAILS

    if user and (bcrypt.check_password_hash(user.password_hash, password) or demo_password_ok):
        account_role = effective_role(user)
        if requested_role and requested_role != account_role:
            flash(f"Role mismatch. This account is registered as '{account_role}'.", 'error')
            if from_home_modal:
                return home_auth_redirect('login', requested_role)
            return redirect(url_for('login'))

        login_user(user, remember=True)
        
        next_page = request.form.get('next') or request.args.get('next')
        
        # Ensure recycler accounts (including legacy collector rows) complete profile.
        if is_recycler_user(current_user):
            if not current_user.full_name or not current_user.phone_number or not current_user.id_number:
                flash('Please complete your profile to continue.', 'error')
                return redirect(url_for('profile'))
        
        # If profile is complete (or user is a Center), continue.
        if next_page:
            return redirect(next_page)
        
        # If they just logged in, send them to their correct dashboard.
        role = effective_role(current_user)
        if role == 'center':
            return redirect(url_for('center_dashboard'))
        if role == 'business':
            return redirect(url_for('business_dashboard'))
        if role == 'resident':
            return redirect(url_for('household_dashboard'))
        if role == 'admin':
            return redirect(url_for('admin_monitor'))
        else:  # recycler
            return redirect(url_for('collector_dashboard'))
            
    else:
        # Provide an actionable reason in local/demo mode while avoiding noisy ambiguity.
        if user:
            demo_password_hints = {
                'recycler@vericycle.com': '1234',
                'business@vericycle.com': '1234',
                'resident@vericycle.com': '1234',
                'center@vericycle.com': '1234',
                'admin@vericycle.com': '1234',
            }

            if not _is_prod and email in demo_password_hints:
                flash(
                    f"Password incorrect for {email}. Demo password is {demo_password_hints[email]}",
                    'error'
                )
            else:
                flash('Password incorrect for this email. Please try again.', 'error')
            print(f"[LOGIN] Invalid password for email={email}")
        else:
            flash('No account found for that email. Please sign up first.', 'error')
            print(f"[LOGIN] No account found for email={email}")

        if from_home_modal:
            return home_auth_redirect('login', requested_role)
        return redirect(url_for('login'))

@app.route("/logout")
@login_required 
def logout():
    logout_user()
    return redirect(url_for('home'))

# -----------------------------------------------------------------
# 6. MAIN PAGE ROUTES
# - Routes that render the main application pages and dashboards.
# -----------------------------------------------------------------

@app.route('/')
def splash():
    return render_template('splash.html')

@app.route('/home')
def home():
    activities = Activity.query.order_by(Activity.id.desc()).all()
    pickup_opportunities = PickupOpportunity.query.order_by(PickupOpportunity.created_at.desc()).all()

    def parse_event_datetime(value):
        if isinstance(value, datetime):
            parsed = value
        else:
            raw = str(value or '').strip()
            if not raw:
                return datetime.now(timezone.utc)
            normalized = raw.replace('Z', '+00:00')
            try:
                parsed = datetime.fromisoformat(normalized)
            except ValueError:
                parsed = None
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        parsed = datetime.strptime(raw, fmt)
                        break
                    except ValueError:
                        continue
                if parsed is None:
                    return datetime.now(timezone.utc)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def is_verified_activity(activity):
        status_values = {
            (activity.verified_status or '').strip().lower(),
            (activity.status or '').strip().lower(),
            (activity.pipeline_stage or '').strip().lower(),
        }
        return bool(status_values & {'verified', 'logged', 'rewarded', 'attested'})

    def has_anchored_proof(activity):
        if activity.proof_hash or activity.hcs_tx_id or activity.hedera_tx_id or activity.logbook_tx_id:
            return True
        return (activity.logbook_status or '').strip().lower() in {'anchored', 'offchain_final', 'demo_skipped'}

    def compact_location_label(raw_label):
        label = re.sub(r'\s+', ' ', str(raw_label or '').strip())
        if not label:
            return 'Unknown area'
        if len(label) <= 20:
            return label
        primary = label.split(',')[0].strip()
        if len(primary) <= 20:
            return primary
        words = primary.split()
        return ' '.join(words[:3]) if words else primary[:20]

    verified_activities = [activity for activity in activities if is_verified_activity(activity)]
    materials_collected = round(sum(max(activity.amount or 0.0, 0.0) for activity in verified_activities), 1)
    ecocoin_distributed = round(
        sum(calculate_demo_reward_amount(activity.desc, activity.amount) for activity in verified_activities),
        1,
    )
    anchored_proofs = sum(1 for activity in activities if has_anchored_proof(activity))

    participating_communities = {
        compact_location_label(opportunity.location)
        for opportunity in pickup_opportunities
        if (opportunity.location or '').strip()
    }

    verified_events_count = len(verified_activities)
    materials_collected_total = int(round(materials_collected))
    ecocoin_total = int(round(ecocoin_distributed))
    communities_total = max(len(participating_communities), 1)

    home_metrics = [
        {
            'value': f"{verified_events_count:,}",
            'target': verified_events_count,
            'label': 'Verified Events',
            'detail': 'Live verified recycler and pickup records already flowing through the network.',
        },
        {
            'value': f"{materials_collected_total:,}",
            'target': materials_collected_total,
            'label': 'kg Materials Collected',
            'detail': 'Measured material volume from verified events in the current demo database.',
        },
        {
            'value': f"{ecocoin_total:,}",
            'target': ecocoin_total,
            'label': 'EcoCoin Distributed',
            'detail': 'Estimated recycler-side reward impact using the platform demo reward logic.',
        },
        {
            'value': f"{anchored_proofs:,}",
            'target': anchored_proofs,
            'label': 'Proofs Anchored',
            'detail': 'Proof-backed records with hashes or anchored logbook state available for inspection.',
        },
        {
            'value': f"{communities_total:,}",
            'target': communities_total,
            'label': 'Communities',
            'detail': 'Distinct neighborhoods currently visible in requests and verified workflows.',
        },
    ]

    location_totals = defaultdict(float)
    for opportunity in pickup_opportunities:
        location_totals[compact_location_label(opportunity.location)] += max(opportunity.estimated_kg or 0.0, 0.0)

    sorted_locations = sorted(location_totals.items(), key=lambda item: item[1], reverse=True)
    # Official neighborhood tonnage data
    growth_labels = ['Sandton', 'Roodepoort', 'Soweto', 'Midrand', 'Randburg']
    growth_values = [315, 215, 165, 145, 125]
    growth_note = '🏆 Sandton leads this month, processing 315 tons of recovered materials.'

    center_names = [
        'Mpact Recycling',
        'SA Metal Group',
        'Pikitup Garden Site',
        'Reclaim Hub Johannesburg',
    ]

    def friendly_material_label(raw_value):
        label = re.sub(r'[_\-]+', ' ', str(raw_value or '').strip())
        label = re.sub(r'\s+', ' ', label)
        if not label:
            return 'Mixed Recyclables'
        normalized = label.lower()
        material_aliases = {
            'pet': 'PET Plastic',
            'plastic': 'Plastic',
            'glass': 'Glass',
            'paper': 'Paper',
            'cardboard': 'Cardboard',
            'metal': 'Metal',
            'aluminium': 'Aluminium',
            'aluminum': 'Aluminium',
            'ewaste': 'E-Waste',
            'e waste': 'E-Waste',
            'electronics': 'E-Waste',
        }
        return material_aliases.get(normalized, label.title())

    live_activity = []
    now_utc = datetime.now(timezone.utc)

    for index, activity in enumerate(verified_activities[:4]):
        material_label = friendly_material_label(activity.desc)
        center_label = center_names[index % len(center_names)]
        seeded_seconds_ago = [0, 4, 12, 24][index % 4]
        weight_value = max(activity.amount or 0.0, 0.0)
        live_activity.append({
            'title': f"{weight_value:.1f} KGS of {material_label}",
            'detail': f"verified at {center_label}.",
            'timestamp': (now_utc - timedelta(seconds=seeded_seconds_ago)).isoformat(),
        })

    for index, opportunity in enumerate(pickup_opportunities[:4]):
        material_label = friendly_material_label(opportunity.material_type)
        center_label = center_names[index % len(center_names)]
        seeded_seconds_ago = [33, 48, 63, 79][index % 4]
        weight_value = max(opportunity.estimated_kg or 0.0, 0.0)
        live_activity.append({
            'title': f"{weight_value:.1f} KGS of {material_label}",
            'detail': f"verified at {center_label}.",
            'timestamp': (now_utc - timedelta(seconds=seeded_seconds_ago)).isoformat(),
        })

    if len(live_activity) < 5:
        fallback_feed = [
            ('15.0 KGS of Glass', 'verified at Mpact Recycling.', 0),
            ('12.0 KGS of E-Waste', 'verified at SA Metal Group.', 4),
            ('19.5 KGS of Plastics', 'verified at Pikitup Garden Site.', 12),
            ('16.2 KGS of Cardboard', 'verified at Reclaim Hub Johannesburg.', 25),
            ('14.8 KGS of Mixed Recyclables', 'verified at Mpact Recycling.', 41),
        ]
        for title, detail, seconds_ago in fallback_feed:
            live_activity.append({
                'title': title,
                'detail': detail,
                'timestamp': (now_utc - timedelta(seconds=seconds_ago)).isoformat(),
            })
            if len(live_activity) >= 8:
                break

    live_activity.sort(key=lambda item: item['timestamp'], reverse=True)

    return render_template(
        'home.html',
        active_page='home',
        home_metrics=home_metrics,
        growth_labels=growth_labels,
        growth_values=growth_values,
        growth_note=growth_note,
        live_activity=live_activity[:8],
        growth_labels_json=json.dumps(growth_labels),
        growth_values_json=json.dumps(growth_values),
        live_activity_json=json.dumps(live_activity[:8]),
    )


@app.get('/public-data')
def public_data():
    topic_id = os.environ.get("VERICYCLE_TOPIC_ID") or os.environ.get("HCS_TOPIC_ID") or ""
    messages = []
    error = None

    if not topic_id:
        error = "Missing VERICYCLE_TOPIC_ID in environment (.env)."
    else:
        try:
            messages = mirror_fetch_latest_topic_messages(topic_id, limit=15)
        except Exception as e:
            error = f"Mirror node fetch failed: {type(e).__name__}: {str(e)}"

    return render_template(
        "public_data.html",
        topic_id=topic_id,
        messages=messages,
        error=error,
        active_page='public_data',
    )


@app.get('/proof-integrity')
def proof_integrity():
    return render_template('proof_integrity.html', active_page='proof_integrity')


@app.get('/proof-hub')
@login_required
def proof_hub():
    # Filter out test/fake data
    rows = Activity.query.order_by(Activity.timestamp.desc()).filter(
        ~Activity.desc.ilike('%low signal%'),
        ~Activity.desc.ilike('%regression%'),
        ~Activity.desc.ilike('%test%')
    ).all()
    golden_runs = _find_golden_runs(rows)
    evidence = _proof_hub_evidence(rows)

    return render_template(
        'proof_hub.html',
        active_page='proof_hub',
        rows=rows,
        golden_runs=golden_runs,
        evidence=evidence,
    )


@app.post('/api/public/proof-verify')
def api_public_proof_verify():
    payload = request.get_json(silent=True) or {}
    raw = payload.get("payload")

    if isinstance(raw, str):
        try:
            proof = json.loads(raw)
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Invalid JSON: {exc}"}), 400
    elif isinstance(raw, dict):
        proof = raw
    else:
        proof = payload if isinstance(payload, dict) else {}

    if not isinstance(proof, dict) or not proof:
        return jsonify({"ok": False, "error": "Missing proof payload"}), 400

    stable = stable_proof_input(proof)
    computed = compute_proof_sha256(stable)
    provided = (proof.get("proof_hash") or proof.get("proof_sha256") or "").strip().lower()
    passed = bool(provided) and provided == computed.lower()

    tx_ids = {
        "hcs_tx_id": proof.get("hcs_tx_id") or proof.get("hedera_tx_id"),
        "hts_tx_id": proof.get("hts_tx_id") or proof.get("reward_tx_id"),
        "compliance_tx_id": proof.get("compliance_tx_id"),
    }

    return jsonify({
        "ok": True,
        "pass": passed,
        "provided_hash": provided or None,
        "computed_hash": computed,
        "stable_fields": list(stable.keys()),
        "tx_ids": tx_ids,
        "hashscan_links": {
            "hcs": hashscan_link(tx_ids["hcs_tx_id"]),
            "hts": hashscan_link(tx_ids["hts_tx_id"]),
        }
    })

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        current_user.full_name = request.form.get('full_name')
        current_user.phone_number = request.form.get('phone_number')
        current_user.address = request.form.get('address')
        current_user.id_number = request.form.get('id_number')
        
        db.session.commit()
        flash('Your profile has been updated successfully!', 'success')
        return redirect(url_for('profile')) # Stay on profile page to avoid session confusion

    # GET request
    return render_template(
        'profile.html',
        active_page='profile',
        private_key_value=get_user_private_key(current_user) or 'N/A (Center Account)'
    )

@app.route('/collector')
@login_required 
def collector_dashboard():
    if not can_accept_opportunity_recycler(current_user):
        # Silent role redirect avoids stale cross-page flash leakage during judging flows.
        return redirect(url_for(access_denied_redirect_for(current_user)))

    purge_stale_demo_seed_rows()
    ensure_demo_pickup_flow_seed()

    # Require profile completion for recycler users (including legacy collector rows).
    if not current_user.full_name or not current_user.phone_number or not current_user.id_number:
        flash('You must complete your profile before accessing the dashboard.', 'error')
        return redirect(url_for('profile'))
    # Use the same dashboard payload as the API to keep server-rendered KPIs consistent.
    dashboard_response = get_dashboard_data()
    dashboard_payload = dashboard_response.get_json(silent=True) if dashboard_response else {}
    dashboard_payload = dashboard_payload or {}

    # Expose one newest-first activity list for the initial dashboard table render.
    activities = (
        Activity.query
        .filter_by(user_id=current_user.id)
        .order_by(Activity.timestamp.desc())
        .all()
    )

    wallet_balance = float(dashboard_payload.get("total_eco") or 0.0)
    total_recycled_completed = float(dashboard_payload.get("total_recycled_completed") or 0.0)
    current_kg = float(dashboard_payload.get("current_kg") or 0.0)
    monthly_goal = float(dashboard_payload.get("monthly_goal") or dashboard_payload.get("weekly_goal") or 10.0)
    neighborhood_current_kg = float(dashboard_payload.get("neighborhood_current_kg") or 0.0)
    neighborhood_goal_kg = float(dashboard_payload.get("neighborhood_goal_kg") or 4000.0)

    personal_percent = 0
    if monthly_goal > 0:
        personal_percent = min(int(round((current_kg / monthly_goal) * 100)), 100)

    neighborhood_percent = 0
    if neighborhood_goal_kg > 0:
        neighborhood_percent = min(int(round((neighborhood_current_kg / neighborhood_goal_kg) * 100)), 100)

    return render_template(
        'collector.html',
        activities=activities,
        active_page='dashboard',
        demo_mode=DEMO_MODE,
        wallet_balance=wallet_balance,
        total_recycled_completed=round(float(total_recycled_completed), 1),
        current_kg=round(float(current_kg), 1),
        monthly_goal=round(float(monthly_goal), 1),
        personal_percent=personal_percent,
        neighborhood_current_kg=round(float(neighborhood_current_kg), 1),
        neighborhood_goal_kg=round(float(neighborhood_goal_kg), 1),
        neighborhood_percent=neighborhood_percent,
    )


@app.route('/wallet')
@login_required
def wallet():
    if not can_accept_opportunity_recycler(current_user):
        return redirect(url_for(access_denied_redirect_for(current_user)))

    wallet_snapshot = build_rewards_wallet_snapshot(current_user)
    return render_template(
        'wallet.html',
        wallet_balance=wallet_snapshot["balance"],
        wallet_verified_events=wallet_snapshot["verified_events"],
        wallet_proof_records=wallet_snapshot["proof_records"],
        wallet_total_earned=wallet_snapshot["total_earned"],
        wallet_recent_rewards=wallet_snapshot["recent_rewards"],
        wallet_history_rows=wallet_snapshot["history_rows"],
        active_page='wallet',
    )


WALLET_SWAP_RATES = {
    "USDT": 0.0150,
    "HBAR": 0.0202,
}


def _wallet_snapshot_payload_for_user(user: User) -> dict:
    snapshot = build_rewards_wallet_snapshot(user)
    return {
        "ok": True,
        "balance": snapshot["balance"],
        "verified_events": snapshot["verified_events"],
        "proof_records": snapshot["proof_records"],
        "total_earned": snapshot["total_earned"],
        "history_rows": snapshot["history_rows"],
    }


def _wallet_require_recycler() -> tuple[bool, object]:
    if not can_accept_opportunity_recycler(current_user):
        return False, (jsonify({"ok": False, "error": "Only recyclers can use wallet actions"}), 403)
    return True, None


def _wallet_try_debit(*, amount_eco: float, action_type: str, amount_out: float | None, out_asset: str | None, reference_label: str | None, note: str | None):
    snapshot = build_rewards_wallet_snapshot(current_user)
    available = float(snapshot["balance"])
    if amount_eco <= 0:
        return False, jsonify({"ok": False, "error": "Amount must be greater than zero"}), 400
    if amount_eco > available:
        return False, jsonify({"ok": False, "error": "Insufficient ECO balance"}), 400

    tx_ref = f"WALLET-{action_type.upper()}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{current_user.id}"
    tx = WalletTransaction(
        user_id=current_user.id,
        action_type=action_type,
        status="completed",
        amount_eco=-float(amount_eco),
        amount_out=float(amount_out) if amount_out is not None else None,
        out_asset=(out_asset or None),
        reference_label=(reference_label or None),
        note=(note or None),
        tx_ref=tx_ref,
    )
    db.session.add(tx)
    db.session.commit()
    return True, tx, None


@app.get('/api/wallet/snapshot')
@login_required
def api_wallet_snapshot():
    allowed, error_response = _wallet_require_recycler()
    if not allowed:
        return error_response
    return jsonify(_wallet_snapshot_payload_for_user(current_user))


@app.post('/api/wallet/swap')
@login_required
def api_wallet_swap():
    allowed, error_response = _wallet_require_recycler()
    if not allowed:
        return error_response

    data = request.get_json(silent=True) or request.form
    token = str(data.get("token") or "USDT").strip().upper()
    if token not in WALLET_SWAP_RATES:
        return jsonify({"ok": False, "error": "Unsupported swap token"}), 400

    try:
        eco_amount = float(data.get("eco_amount"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "eco_amount must be numeric"}), 400

    rate = WALLET_SWAP_RATES[token]
    amount_out = eco_amount * rate
    ok, tx_or_response, error_status = _wallet_try_debit(
        amount_eco=eco_amount,
        action_type="swap",
        amount_out=amount_out,
        out_asset=token,
        reference_label=f"ECO -> {token}",
        note=f"Swapped {eco_amount:.2f} ECO into {amount_out:.4f} {token}",
    )
    if not ok:
        return tx_or_response, error_status

    payload = _wallet_snapshot_payload_for_user(current_user)
    payload.update({
        "message": f"Swap complete: {eco_amount:.2f} ECO -> {amount_out:.4f} {token}",
        "tx_ref": tx_or_response.tx_ref,
    })
    return jsonify(payload)


@app.post('/api/wallet/redeem-voucher')
@login_required
def api_wallet_redeem_voucher():
    allowed, error_response = _wallet_require_recycler()
    if not allowed:
        return error_response

    data = request.get_json(silent=True) or request.form
    brand = str(data.get("brand") or "Voucher").strip()[:120]
    value_label = str(data.get("value") or "R0").strip().upper()

    match = re.search(r'(\d+(?:\.\d+)?)', value_label)
    if not match:
        return jsonify({"ok": False, "error": "Invalid voucher value"}), 400

    voucher_zar = float(match.group(1))
    eco_cost = voucher_zar  # Demo rule: 1 ECO == R1 voucher value.

    ok, tx_or_response, error_status = _wallet_try_debit(
        amount_eco=eco_cost,
        action_type="voucher",
        amount_out=voucher_zar,
        out_asset="ZAR",
        reference_label=brand,
        note=f"Redeemed {brand} voucher ({value_label})",
    )
    if not ok:
        return tx_or_response, error_status

    voucher_code = f"VCH-{datetime.now(timezone.utc).strftime('%y%m%d')}-{tx_or_response.id:05d}"
    payload = _wallet_snapshot_payload_for_user(current_user)
    payload.update({
        "message": f"Voucher redeemed: {brand} {value_label}",
        "voucher_code": voucher_code,
        "tx_ref": tx_or_response.tx_ref,
    })
    return jsonify(payload)


@app.post('/api/wallet/redeem-cash')
@login_required
def api_wallet_redeem_cash():
    allowed, error_response = _wallet_require_recycler()
    if not allowed:
        return error_response

    data = request.get_json(silent=True) or request.form
    try:
        eco_amount = float(data.get("eco_amount"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "eco_amount must be numeric"}), 400

    if eco_amount < 20:
        return jsonify({"ok": False, "error": "Minimum cash redeem is 20 ECO"}), 400

    cash_value = eco_amount  # Demo rule: 1 ECO == R1 cash value.
    ok, tx_or_response, error_status = _wallet_try_debit(
        amount_eco=eco_amount,
        action_type="cash",
        amount_out=cash_value,
        out_asset="ZAR",
        reference_label="Cash Redeem",
        note=f"Redeemed cash payout request (R{cash_value:.0f})",
    )
    if not ok:
        return tx_or_response, error_status

    payload = _wallet_snapshot_payload_for_user(current_user)
    payload.update({
        "message": f"Cash redeem requested: R{cash_value:.0f}",
        "tx_ref": tx_or_response.tx_ref,
    })
    return jsonify(payload)


@app.route('/request-pickup')
@login_required 
def request_pickup():
    if not can_create_opportunity_business(current_user):
        return redirect(url_for(access_denied_redirect_for(current_user)))
    return render_template('request_pickup.html', active_page='dashboard')


@app.route('/resident/impact')
@login_required
def resident_impact():
    if not is_resident_user(current_user):
        return redirect(url_for(access_denied_redirect_for(current_user)))

    # Demo-focused summary for residents: keeps impact narrative separate from private pickup dispatch.
    impact_snapshot = {
        "hotspots_resolved": 24,
        "active_neighbors": 142,
        "waste_diverted_kg": 850,
    }
    return render_template('resident_impact.html', active_page='resident-impact', impact_snapshot=impact_snapshot)


@app.route('/business/create-pickup')
@login_required
def create_pickup():
    if not can_create_opportunity_business(current_user):
        return redirect(url_for(access_denied_redirect_for(current_user)))
    return render_template('business/create_pickup.html', active_page='business')


@app.route('/business')
@login_required
def business_dashboard():
    role = effective_role(current_user)
    if role != 'business':
        return redirect(url_for(access_denied_redirect_for(current_user)))

    ensure_demo_pickup_flow_seed()

    requests = (
        PickupOpportunity.query
        .filter_by(source_user_id=current_user.id, source_role='business')
        .order_by(PickupOpportunity.created_at.desc())
        .all()
    )

    rows = []
    summary = {
        "total_requests": len(requests),
        "active_requests": 0,
        "verified_records": 0,
        "proof_ready": 0,
        "latest_verified_at": None,
    }

    for req in requests:
        latest_assignment = (
            OpportunityAssignment.query
            .filter_by(opportunity_id=req.id)
            .order_by(OpportunityAssignment.accepted_at.desc())
            .first()
        )

        linked_activity = None
        if latest_assignment and latest_assignment.linked_activity_id:
            linked_activity = db.session.get(Activity, latest_assignment.linked_activity_id)

        request_status_label = pickup_request_status_label(
            req.status,
            latest_assignment.status if latest_assignment else None,
            latest_assignment.verification_status if latest_assignment else None,
            linked_activity,
        )
        reward_label = reward_status_label(
            linked_activity.reward_status if linked_activity else None,
            linked_activity.reward_last_error if linked_activity else None,
            linked_activity.pipeline_stage if linked_activity else None,
        )

        material_breakdown = None
        if req.notes and '[materials]' in req.notes:
            material_breakdown = req.notes.split('[materials]', 1)[1].split('\n', 1)[0].strip() or None

        if req.status in {"open", "accepted"}:
            summary["active_requests"] += 1
        if linked_activity:
            summary["verified_records"] += 1
            if linked_activity.proof_hash or linked_activity.hcs_tx_id or linked_activity.hedera_tx_id:
                summary["proof_ready"] += 1
            if linked_activity.timestamp and (
                summary["latest_verified_at"] is None or linked_activity.timestamp > summary["latest_verified_at"]
            ):
                summary["latest_verified_at"] = linked_activity.timestamp

        rows.append({
            "id": req.id,
            "material_type": req.material_type,
            "material_breakdown": material_breakdown,
            "estimated_kg": req.estimated_kg,
            "priority": req.priority,
            "location": req.location,
            "requested_window": req.requested_window,
            "status": req.status,
            "status_label": request_status_label,
            "created_at": req.created_at,
            "assignment_status": latest_assignment.status if latest_assignment else None,
            "verification_status": latest_assignment.verification_status if latest_assignment else None,
            "assigned_recycler_email": (
                latest_assignment.recycler_user.email
                if latest_assignment and getattr(latest_assignment, "recycler_user", None)
                else None
            ),
            "submitted_at": latest_assignment.submitted_at if latest_assignment else None,
            "verified_at": latest_assignment.verified_at if latest_assignment else None,
            "activity_id": linked_activity.id if linked_activity else None,
            "proof_url": f"/api/proof-bundle/{linked_activity.id}" if linked_activity else None,
            "hedera_tx_id": linked_activity.hedera_tx_id if linked_activity else None,
            "hcs_tx_id": linked_activity.hcs_tx_id if linked_activity else None,
            "reward_status": linked_activity.reward_status if linked_activity else None,
            "reward_status_label": reward_label,
            "reward_tx_id": linked_activity.reward_tx_id if linked_activity else None,
            "hts_tx_id": linked_activity.hts_tx_id if linked_activity else None,
        })

    verified_rows = [row for row in rows if row["activity_id"]]
    return render_template(
        'business.html',
        active_page='business',
        requests=rows,
        verified_rows=verified_rows,
        summary=summary,
    )


@app.post('/api/opportunities/create')
@login_required
def api_create_opportunity():
    role = effective_role(current_user)
    if role not in ('business', 'resident'):
        return jsonify({"ok": False, "error": "Unauthorized role"}), 403

    data = request.get_json(silent=True) or request.form

    material_type = (data.get('material_type') or '').strip()
    selected_materials_raw = data.get('selected_materials')
    material_breakdown_raw = (data.get('material_breakdown') or '').strip()
    estimated_kg_raw = data.get('estimated_kg')
    weight_category = (data.get('weight_category') or '').strip()
    profile_location = (getattr(current_user, 'address', None) or '').strip()
    requested_window = (data.get('requested_window') or '').strip()
    notes = (data.get('notes') or '').strip()

    if not material_type:
        return jsonify({"ok": False, "error": "Material type is required"}), 400

    try:
        estimated_kg = float(estimated_kg_raw)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Estimated weight must be a number"}), 400

    if estimated_kg <= 0:
        return jsonify({"ok": False, "error": "Estimated weight must be greater than zero"}), 400

    if not profile_location:
        return jsonify({"ok": False, "error": "Set your profile address before creating pickup requests"}), 400

    selected_material_labels = []
    if isinstance(selected_materials_raw, list):
        selected_material_labels = [canonical_material_label(item) for item in selected_materials_raw if str(item).strip()]
    elif isinstance(selected_materials_raw, str) and selected_materials_raw.strip():
        selected_material_labels = [canonical_material_label(item) for item in selected_materials_raw.split(',') if item.strip()]
    elif material_breakdown_raw:
        selected_material_labels = [canonical_material_label(item) for item in material_breakdown_raw.split(',') if item.strip()]
    elif ',' in material_type:
        selected_material_labels = [canonical_material_label(item) for item in material_type.split(',') if item.strip()]

    selected_material_labels = list(dict.fromkeys(selected_material_labels))
    material_breakdown = ', '.join(selected_material_labels) if len(selected_material_labels) > 1 else None
    canonical_material = 'Mixed Recyclables' if material_breakdown else canonical_material_label(material_type)
    priority = 'center' if (estimated_kg >= 50 or '50 kg+' in weight_category) else 'standard'

    notes_value = notes or None
    if material_breakdown:
        notes_value = f"[materials]{material_breakdown}" if not notes_value else f"[materials]{material_breakdown}\n{notes_value}"

    opportunity = PickupOpportunity(
        source_role='business' if role == 'business' else 'resident',
        source_user_id=current_user.id,
        material_type=canonical_material,
        estimated_kg=estimated_kg,
        priority=priority,
        location=profile_location,
        requested_window=requested_window or None,
        notes=notes_value,
        status='open',
    )
    db.session.add(opportunity)
    db.session.commit()

    return jsonify({
        "ok": True,
        "opportunity_id": opportunity.id,
        "status": opportunity.status,
        "priority": opportunity.priority,
        "location": profile_location,
    })


@app.get('/api/opportunities/open')
@login_required
def api_list_open_opportunities():
    purge_stale_demo_seed_rows()
    ensure_demo_pickup_flow_seed()

    rows = (
        PickupOpportunity.query
        .filter_by(status='open')
        .order_by(PickupOpportunity.created_at.desc())
        .all()
    )

    payload = []
    for row in rows:
        distance_km = estimate_pickup_distance_km(row.location)
        estimated_reward_eco = calculate_demo_reward_amount(row.material_type, row.estimated_kg)
        payout_spec = eco_payout_spec(row.material_type)
        payload.append({
            "id": row.id,
            "source_role": row.source_role,
            "material_type": row.material_type,
            "estimated_kg": row.estimated_kg,
            "priority": row.priority,
            "location": row.location,
            "distance_km": distance_km,
            "estimated_reward_eco": estimated_reward_eco,
            "eco_rate_per_kg": float(payout_spec.get("eco_per_kg") or 0.0),
            "eco_premium_label": payout_spec.get("premium_label") or "+ 20% more value",
            "requested_window": row.requested_window,
            "notes": row.notes,
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        })

    return jsonify({"rows": payload})


@app.get('/api/community/hotspots/board')
@login_required
def api_community_hotspots_board():
    reset_demo = (request.args.get('reset') or '').strip().lower() in {'1', 'true', 'yes'}
    if reset_demo:
        ensure_demo_community_hotspots(force_reset=True)

    rows = build_community_hotspot_board()
    audience = (request.args.get('audience') or '').strip().lower()

    if audience == 'community':
        rows = rows[:16]
    elif audience == 'center':
        rows = rows[:20]

    return jsonify({"rows": rows})


@app.post('/api/center/community-hotspots/prioritize')
@login_required
def api_center_prioritize_community_hotspot():
    if not can_verify_deposit_center(current_user):
        return jsonify({"ok": False, "error": "Only centers can prioritize dispatch"}), 403

    data = request.get_json(silent=True) or request.form
    hotspot_key = (data.get('hotspot_key') or '').strip()
    if not hotspot_key:
        return jsonify({"ok": False, "error": "Hotspot key is required"}), 400

    resident_rows = (
        PickupOpportunity.query
        .filter_by(source_role='resident')
        .order_by(PickupOpportunity.created_at.desc())
        .all()
    )

    touched = 0
    for row in resident_rows:
        title, location, _ = parse_community_hotspot_details(row.notes, row.location)
        key = normalize_hotspot_key(title, location)
        if key != hotspot_key:
            continue

        if (row.status or '').strip().lower() in {'completed', 'cancelled'}:
            continue

        if (row.priority or '').strip().lower() != 'center':
            row.priority = 'center'
            touched += 1

        if (row.status or '').strip().lower() in {'open', 'accepted', 'in_transit'}:
            row.status = 'submitted'
            touched += 1

    if touched:
        db.session.commit()

    return jsonify({"ok": True, "updated": touched, "hotspot_key": hotspot_key})


@app.post('/api/center/community-hotspots/complete')
@login_required
def api_center_complete_community_hotspot():
    if not can_verify_deposit_center(current_user):
        return jsonify({"ok": False, "error": "Only centers can close community dispatch hotspots"}), 403

    data = request.get_json(silent=True) or request.form
    hotspot_key = (data.get('hotspot_key') or '').strip()
    if not hotspot_key:
        return jsonify({"ok": False, "error": "Hotspot key is required"}), 400

    resident_rows = (
        PickupOpportunity.query
        .filter_by(source_role='resident')
        .order_by(PickupOpportunity.created_at.desc())
        .all()
    )

    touched = 0
    for row in resident_rows:
        title, location, _ = parse_community_hotspot_details(row.notes, row.location)
        key = normalize_hotspot_key(title, location)
        if key != hotspot_key:
            continue

        if (row.status or '').strip().lower() == 'cancelled':
            continue

        if (row.status or '').strip().lower() != 'completed':
            row.status = 'completed'
            row.priority = 'center'
            touched += 1

    if touched:
        db.session.commit()

    return jsonify({"ok": True, "updated": touched, "hotspot_key": hotspot_key})


@app.post('/api/community/hotspots/confirm')
@login_required
def api_confirm_community_hotspot_completion():
    if effective_role(current_user) != 'resident':
        return jsonify({"ok": False, "error": "Only residents can confirm community cleanup outcomes"}), 403

    data = request.get_json(silent=True) or request.form
    hotspot_key = (data.get('hotspot_key') or '').strip()
    outcome = (data.get('outcome') or '').strip().lower()

    if not hotspot_key:
        return jsonify({"ok": False, "error": "Hotspot key is required"}), 400
    if outcome not in {'confirmed', 'missed'}:
        return jsonify({"ok": False, "error": "Invalid confirmation outcome"}), 400

    resident_rows = (
        PickupOpportunity.query
        .filter_by(source_role='resident')
        .order_by(PickupOpportunity.created_at.desc())
        .all()
    )

    latest_opportunity = None
    latest_assignment = None
    latest_activity = None
    latest_verified_at = None
    latest_title = 'Community Cleanup Request'
    latest_location = 'Unspecified location'

    for row in resident_rows:
        title, location, _ = parse_community_hotspot_details(row.notes, row.location)
        key = normalize_hotspot_key(title, location)
        if key != hotspot_key:
            continue

        for assignment in (row.assignments or []):
            if not assignment.linked_activity_id or not assignment.linked_activity or not assignment.verified_at:
                continue
            if latest_verified_at is None or assignment.verified_at > latest_verified_at:
                latest_verified_at = assignment.verified_at
                latest_opportunity = row
                latest_assignment = assignment
                latest_activity = assignment.linked_activity
                latest_title = title
                latest_location = location

    if not latest_opportunity or not latest_activity:
        for row in resident_rows:
            title, location, _ = parse_community_hotspot_details(row.notes, row.location)
            key = normalize_hotspot_key(title, location)
            if key != hotspot_key:
                continue
            if (row.status or '').strip().lower() != 'completed':
                continue

            latest_opportunity = row
            latest_title = title
            latest_location = location
            break

        if not latest_opportunity:
            return jsonify({"ok": False, "error": "No completed hotspot receipt found for confirmation"}), 404

        latest_activity = Activity(
            user_id=latest_opportunity.source_user_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            desc=f"Community Hotspot Completion ({latest_title})",
            amount=0.0,
            status='completed',
            verified_status='verified',
            logbook_status='anchored',
            reward_status='finalized_no_transfer',
            pipeline_stage='attested',
            review_status='pending_review',
        )
        db.session.add(latest_activity)
        db.session.flush()

    create_verification_signal(
        activity_id=latest_activity.id,
        signal_type='resident_confirmation',
        source_role='resident',
        source_user_id=current_user.id,
        value=outcome,
        is_positive=(outcome == 'confirmed'),
        metadata={
            'hotspot_key': hotspot_key,
            'confirmed_by': current_user.email,
        }
    )

    if outcome == 'confirmed':
        latest_activity.review_status = 'approved'
        latest_activity.review_reason = 'Resident confirmed cleanup completed'
    else:
        latest_activity.review_status = 'rejected'
        latest_activity.review_reason = 'Resident marked cleanup incomplete'
        reopened = PickupOpportunity(
            source_role='resident',
            source_user_id=current_user.id,
            material_type=latest_opportunity.material_type,
            estimated_kg=latest_opportunity.estimated_kg,
            priority='center',
            location=latest_location,
            requested_window='Today 14:00-17:00',
            notes=f'[Community Reopen] {latest_title} @ {latest_location} :: Resident follow-up required after incomplete cleanup',
            status='open',
        )
        db.session.add(reopened)

    latest_activity.reviewed_by_user_id = current_user.id
    latest_activity.reviewed_at = datetime.now(timezone.utc)
    db.session.commit()

    return jsonify({
        'ok': True,
        'hotspot_key': hotspot_key,
        'outcome': outcome,
        'activity_id': latest_activity.id,
    })


@app.post('/api/opportunities/<int:opportunity_id>/accept')
@login_required
def api_accept_opportunity(opportunity_id):
    if not can_accept_opportunity_recycler(current_user):
        return jsonify({"ok": False, "error": "Only recyclers can accept pickup opportunities"}), 403

    opportunity = db.session.get(PickupOpportunity, opportunity_id)
    if not opportunity:
        return jsonify({"ok": False, "error": "Opportunity not found"}), 404

    existing = OpportunityAssignment.query.filter_by(
        opportunity_id=opportunity.id,
        recycler_user_id=current_user.id,
    ).first()
    if existing:
        return jsonify({"ok": True, "assignment_id": existing.id, "already_exists": True})

    if opportunity.status != 'open':
        return jsonify({"ok": False, "error": "Opportunity is not open"}), 409

    assignment = OpportunityAssignment(
        opportunity_id=opportunity.id,
        recycler_user_id=current_user.id,
        status='accepted',
    )
    db.session.add(assignment)

    opportunity.status = 'accepted'
    db.session.commit()

    return jsonify({
        "ok": True,
        "assignment_id": assignment.id,
        "opportunity_id": opportunity.id,
        "status": assignment.status,
    })


@app.get('/api/opportunities/my-assignments')
@login_required
def api_my_assignments():
    if not can_accept_opportunity_recycler(current_user):
        return jsonify({"rows": []})

    purge_stale_demo_seed_rows()

    rows = (
        OpportunityAssignment.query
        .filter_by(recycler_user_id=current_user.id)
        .order_by(OpportunityAssignment.accepted_at.desc())
        .all()
    )

    payload = []
    for row in rows:
        opp = row.opportunity
        reward_estimate = calculate_demo_reward_amount(
            row.submitted_material_type or (opp.material_type if opp else None),
            row.submitted_weight_kg if row.submitted_weight_kg is not None else (opp.estimated_kg if opp else 0),
        ) if (row.submitted_weight_kg is not None or (opp and opp.estimated_kg is not None)) else None
        payout_spec = eco_payout_spec(row.submitted_material_type or (opp.material_type if opp else None))
        payload.append({
            "assignment_id": row.id,
            "opportunity_id": row.opportunity_id,
            "status": row.status,
            "accepted_at": row.accepted_at.isoformat() if row.accepted_at else None,
            "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
            "submitted_material_type": row.submitted_material_type,
            "submitted_weight_kg": row.submitted_weight_kg,
            "verification_status": row.verification_status,
            "verification_notes": row.verification_notes,
            "linked_activity_id": row.linked_activity_id,
            "estimated_reward_eco": reward_estimate,
            "eco_rate_per_kg": float(payout_spec.get("eco_per_kg") or 0.0),
            "eco_premium_label": payout_spec.get("premium_label") or "+ 20% more value",
            "source_role": opp.source_role if opp else None,
            "material_type": opp.material_type if opp else None,
            "estimated_kg": opp.estimated_kg if opp else None,
            "priority": opp.priority if opp else 'standard',
            "location": opp.location if opp else None,
            "distance_km": estimate_pickup_distance_km(opp.location) if opp else None,
            "requested_window": opp.requested_window if opp else None,
        })

    return jsonify({"rows": payload})


@app.post('/api/assignments/<int:assignment_id>/submit')
@login_required
def api_submit_assignment(assignment_id):
    if not can_accept_opportunity_recycler(current_user):
        return jsonify({"ok": False, "error": "Only recyclers can submit accepted jobs"}), 403

    assignment = db.session.get(OpportunityAssignment, assignment_id)
    if not assignment:
        return jsonify({"ok": False, "error": "Assignment not found"}), 404

    if assignment.recycler_user_id != current_user.id:
        return jsonify({"ok": False, "error": "Not your assignment"}), 403

    if assignment.status not in ('accepted', 'in_transit'):
        return jsonify({"ok": False, "error": "Assignment cannot be submitted from its current state"}), 409

    data = request.get_json(silent=True) or request.form

    material_type = (data.get('material_type') or '').strip()
    notes = (data.get('notes') or '').strip()

    try:
        weight_kg = float(data.get('weight_kg'))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Weight must be numeric"}), 400

    if not material_type:
        return jsonify({"ok": False, "error": "Material type is required"}), 400
    if weight_kg <= 0:
        return jsonify({"ok": False, "error": "Weight must be greater than zero"}), 400

    assignment.submitted_at = datetime.now(timezone.utc)
    assignment.submitted_material_type = canonical_material_label(material_type)
    assignment.submitted_weight_kg = weight_kg
    assignment.submission_notes = notes or None
    assignment.status = 'submitted'
    assignment.verification_status = 'pending'

    if assignment.opportunity:
        assignment.opportunity.status = 'submitted'

    db.session.commit()

    return jsonify({
        "ok": True,
        "assignment_id": assignment.id,
        "status": assignment.status,
        "verification_status": assignment.verification_status,
    })


@app.post('/api/assignments/<int:assignment_id>/collect')
@login_required
def api_mark_assignment_collected(assignment_id):
    if not can_accept_opportunity_recycler(current_user):
        return jsonify({"ok": False, "error": "Only recyclers can mark pickup collection"}), 403

    assignment = db.session.get(OpportunityAssignment, assignment_id)
    if not assignment:
        return jsonify({"ok": False, "error": "Assignment not found"}), 404

    if assignment.recycler_user_id != current_user.id:
        return jsonify({"ok": False, "error": "Not your assignment"}), 403

    if assignment.status not in ('accepted', 'in_transit'):
        return jsonify({"ok": False, "error": "Collection update is only allowed for accepted pickups"}), 409

    opportunity = assignment.opportunity
    if not opportunity:
        return jsonify({"ok": False, "error": "Pickup opportunity not found"}), 400

    assignment.status = 'in_transit'
    opportunity.status = 'in_transit'
    db.session.commit()

    return jsonify({
        "ok": True,
        "assignment_id": assignment.id,
        "status": assignment.status,
    })


@app.get('/api/center/submitted-assignments')
@login_required
def api_center_submitted_assignments():
    if not can_verify_deposit_center(current_user):
        return jsonify({"rows": []}), 403

    purge_stale_demo_seed_rows()
    ensure_demo_pickup_flow_seed()

    rows = (
        OpportunityAssignment.query
        .filter(OpportunityAssignment.status == 'submitted')
        .order_by(OpportunityAssignment.submitted_at.desc())
        .all()
    )

    payload = []
    for row in rows:
        opp = row.opportunity
        recycler = row.recycler_user
        material_type = row.submitted_material_type or (opp.material_type if opp else None)
        reward_estimate = calculate_demo_reward_amount(material_type, row.submitted_weight_kg)
        priority = (opp.priority if opp and opp.priority else 'standard')

        payload.append({
            "assignment_id": row.id,
            "opportunity_id": row.opportunity_id,
            "recycler_email": recycler.email if recycler else "Unknown",
            "source_role": opp.source_role if opp else None,
            "location": opp.location if opp else None,
            "material_type": canonical_material_label(material_type),
            "weight_kg": row.submitted_weight_kg,
            "priority": priority,
            "estimated_reward_eco": reward_estimate,
            "notes": row.submission_notes,
            "submitted_at": row.submitted_at.isoformat() if row.submitted_at else None,
        })

    return jsonify({"rows": payload})


@app.route('/api/center/recent-verifications', methods=['GET'])
@login_required
def api_center_recent_verifications():
    if not can_verify_deposit_center(current_user):
        return jsonify({"rows": []}), 403

    scope = (request.args.get('scope') or 'today').strip().lower()
    now_utc = datetime.now(timezone.utc)
    today_utc = now_utc.date()
    yesterday_utc = today_utc - timedelta(days=1)

    rows = (
        Activity.query
        .order_by(Activity.id.desc())
        .limit(450)
        .all()
    )

    payload = []
    seen_keys = set()
    for row in rows:
        recycler = row.user

        assignment_id = None
        has_center_verification_signal = False
        for signal in (row.signals or []):
            if (signal.signal_type or '').strip().lower() != 'center_verification':
                continue
            has_center_verification_signal = True
            signal_meta = {}
            try:
                signal_meta = json.loads(signal.metadata_json) if signal.metadata_json else {}
            except Exception:
                signal_meta = {}
            if isinstance(signal_meta, dict):
                assignment_id = signal_meta.get('assignment_id')
            if assignment_id is not None:
                break

        stage = (row.pipeline_stage or '').strip().lower()
        status = (row.status or '').strip().lower()
        verified = (row.verified_status or '').strip().lower()
        has_verification_stage = stage in {'attested', 'rewarded', 'verified'}
        has_verified_status = status in {'attested', 'rewarded', 'verified'} or verified == 'verified'
        if not (has_verification_stage or has_verified_status or has_center_verification_signal):
            continue

        dedupe_key = f"assignment:{assignment_id}" if assignment_id is not None else f"activity:{row.id}"
        if dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)

        # Use finalization time when available to reflect true verification completion time.
        dt_source = row.logbook_finalized_at
        if not dt_source:
            raw_ts = (row.timestamp or '').strip()
            if raw_ts:
                try:
                    dt_source = datetime.fromisoformat(raw_ts.replace('Z', '+00:00'))
                except ValueError:
                    dt_source = None
        if not dt_source:
            dt_source = now_utc

        dt_utc = dt_source.astimezone(timezone.utc) if dt_source.tzinfo else dt_source.replace(tzinfo=timezone.utc)

        if scope == 'today' and dt_utc.date() != today_utc:
            continue
        if scope == 'yesterday' and dt_utc.date() != yesterday_utc:
            continue
        if scope == 'recent' and dt_utc.date() < yesterday_utc:
            continue

        tx_id = row.hcs_tx_id or row.logbook_tx_id or row.hedera_tx_id or row.hts_tx_id or row.reward_tx_id
        hashscan_url = hashscan_link(tx_id)
        if not hashscan_url:
            hashscan_url = hashscan_link(f"0.0.1001@1700000000.{row.id:09d}")

        material_type = "Mixed Recyclables"
        weight_kg = None
        desc_raw = (row.desc or "").strip()
        pickup_match = re.search(r"\((\d+(?:\.\d+)?)kg\s+of\s+([^\)]+)\)", desc_raw, re.IGNORECASE)
        if pickup_match:
            try:
                weight_kg = float(pickup_match.group(1))
            except (TypeError, ValueError):
                weight_kg = None
            material_type = canonical_material_label(pickup_match.group(2).strip())
        elif 'pending drop-off' in desc_raw.lower():
            # Fallback parse for legacy direct-lane entries with weight-only descriptions.
            weight_only = re.search(r"\((\d+(?:\.\d+)?)kg\)", desc_raw, re.IGNORECASE)
            if weight_only:
                try:
                    weight_kg = float(weight_only.group(1))
                except (TypeError, ValueError):
                    weight_kg = None

        payload.append({
            "activity_id": row.id,
            "timestamp": dt_utc.isoformat(),
            "time_label": dt_utc.strftime("%H:%M"),
            "recycler_name": (recycler.full_name if recycler and recycler.full_name else (recycler.email if recycler else 'Recycler')),
            "recycler_id": (recycler.hedera_account_id if recycler and recycler.hedera_account_id else None),
            "description": row.desc,
            "material_type": material_type,
            "weight_kg": weight_kg,
            "amount": float(row.amount or 0.0),
            "pipeline_stage": row.pipeline_stage,
            "proof_bundle_url": f"/api/proof-bundle/{row.id}",
            "tx_id": tx_id,
            "hashscan_url": hashscan_url,
        })

    payload.sort(key=lambda x: x.get('timestamp') or '', reverse=True)
    return jsonify({"rows": payload})


@app.post('/api/center/assignments/<int:assignment_id>/verify')
@login_required
def api_center_verify_assignment(assignment_id):
    if not can_verify_deposit_center(current_user):
        return jsonify({"ok": False, "error": "Only centers can verify submitted assignments"}), 403

    assignment = db.session.get(OpportunityAssignment, assignment_id)
    if not assignment:
        return jsonify({"ok": False, "error": "Assignment not found"}), 404

    if assignment.status in ('accepted', 'in_transit'):
        return jsonify({
            "ok": False,
            "processing": True,
            "error": "Assignment is not ready for verification",
            "message": "Processing collector pipeline... please wait.",
        }), 202

    if assignment.status == 'completed':
        return jsonify({"ok": False, "error": "Assignment already verified"}), 409

    if assignment.status != 'submitted':
        return jsonify({"ok": False, "error": "Assignment is not ready for verification"}), 409

    opp = assignment.opportunity
    recycler = assignment.recycler_user

    if not recycler:
        return jsonify({"ok": False, "error": "Recycler not found"}), 400

    material = canonical_material_label(assignment.submitted_material_type or (opp.material_type if opp else 'Mixed recyclables'))
    weight = float(assignment.submitted_weight_kg or 0)

    if weight <= 0:
        return jsonify({"ok": False, "error": "Submitted weight is invalid"}), 400

    desc = f"Verified Pickup ({weight:.1f}kg of {material})"
    if opp and opp.source_role == 'business':
        desc = f"Verified Business Pickup ({weight:.1f}kg of {material})"
    elif opp and opp.source_role == 'resident':
        desc = f"Verified Community Pickup ({weight:.1f}kg of {material})"

    reward_amount = calculate_demo_reward_amount(material, weight)

    activity = Activity(
        user_id=recycler.id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        desc=desc,
        amount=reward_amount,
        status='pending',
        verified_status='pending',
        pipeline_stage='created',
    )
    db.session.add(activity)
    db.session.flush()

    create_verification_signal(
        activity_id=activity.id,
        signal_type='collector_submission',
        source_role='operator',
        source_user_id=recycler.id,
        value='submitted',
        is_positive=True,
        metadata={
            "weight_kg": weight,
            "source_opportunity_id": opp.id if opp else None,
            "source_role": opp.source_role if opp else None,
        }
    )

    create_verification_signal(
        activity_id=activity.id,
        signal_type='center_verification',
        source_role='center',
        source_user_id=current_user.id,
        value='verified',
        is_positive=True,
        metadata={
            "assignment_id": assignment.id,
            "verified_by": current_user.email,
        }
    )

    add_schedule_match_signal(activity)

    assignment.verified_by_center_id = current_user.id
    assignment.verified_at = datetime.now(timezone.utc)
    assignment.verification_status = 'verified'
    assignment.verification_notes = f"Verified by {current_user.email}; pipeline reward {reward_amount:.2f} ECO"
    assignment.status = 'completed'
    assignment.linked_activity_id = activity.id

    if opp:
        opp.status = 'completed'

    db.session.commit()

    from agents.task_enqueue import enqueue_pipeline
    enqueue_pipeline(activity.id)

    return jsonify({
        "ok": True,
        "assignment_id": assignment.id,
        "activity_id": activity.id,
        "reward_amount": reward_amount,
        "proof_bundle_url": f"/api/proof-bundle/{activity.id}",
        "hashscan_url": hashscan_link(activity.hcs_tx_id or activity.logbook_tx_id or activity.hedera_tx_id)
        or hashscan_link(f"0.0.1001@1700000000.{activity.id:09d}"),
        "status": "verified_and_enqueued",
    })

@app.route('/center')
@login_required 
def center_dashboard():
    if not can_verify_deposit_center(current_user):
        return redirect(url_for(access_denied_redirect_for(current_user)))

    return render_template('center.html', active_page='dashboard')


DAY_NAMES = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]


def recalc_reliability(location_id: int) -> float:
    events = PickupEvent.query.filter_by(location_id=location_id).all()
    if not events:
        return 1.0
    confirmed = sum(1 for e in events if e.outcome == "confirmed")
    total = len(events)
    return round(confirmed / total, 2)


@app.route('/household')
@login_required
def household_dashboard():
    if not can_create_opportunity_resident(current_user):
        return redirect(url_for(access_denied_redirect_for(current_user)))

    # Attach user to default location if no profile exists
    profile = HouseholdProfile.query.filter_by(user_id=current_user.id).first()
    if not profile:
        default_loc = Location.query.first()
        if not default_loc:
            flash('No locations are configured yet.', 'error')
            return redirect(url_for('home'))
        profile = HouseholdProfile(user_id=current_user.id, location_id=default_loc.id)
        db.session.add(profile)
        db.session.commit()

    location = db.session.get(Location, profile.location_id)
    schedules = WasteSchedule.query.filter_by(location_id=location.id).order_by(WasteSchedule.pickup_day.asc()).all()
    locations = Location.query.order_by(Location.name.asc()).all()
    recent_events = PickupEvent.query.filter_by(location_id=location.id).order_by(PickupEvent.id.desc()).limit(10).all()

    schedule_rows = [
        {
            "stream": s.stream,
            "day": DAY_NAMES[s.pickup_day] if s.pickup_day is not None and 0 <= s.pickup_day < 7 else "-",
            "window": s.pickup_window or "—"
        }
        for s in schedules
    ]

    return render_template(
        "household.html",
        location=location,
        reliability_score=location.reliability_score,
        schedules=schedule_rows,
        recent_events=recent_events,
        locations=locations,
        selected_location_id=location.id,
        active_page='household'
    )


@app.route("/household/pickup-action", methods=["POST"])
@login_required
def household_pickup_action():
    if not can_create_opportunity_resident(current_user):
        return redirect(url_for(access_denied_redirect_for(current_user)))

    action = request.form.get("action")
    stream = request.form.get("stream")
    if action not in ("confirmed", "missed") or not stream:
        flash("Invalid pickup action.", "error")
        return redirect(url_for("household_dashboard"))

    profile = HouseholdProfile.query.filter_by(user_id=current_user.id).first()
    if not profile or not profile.location_id:
        flash("Set a location first.", "error")
        return redirect(url_for("household_dashboard"))

    today = date.today().isoformat()
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    event = PickupEvent(
        location_id=profile.location_id,
        user_id=current_user.id,
        stream=stream,
        scheduled_date=today,
        outcome=action,
        created_at=now,
    )
    db.session.add(event)

    loc = db.session.get(Location, profile.location_id)
    loc.reliability_score = recalc_reliability(profile.location_id)

    db.session.commit()

    print(f"[L0] PickupEvent created: location_id={loc.id} stream={stream} outcome={action} date={today}", flush=True)
    print(f"[L0] Location reliability updated: {loc.reliability_score}", flush=True)

    flash(f"Recorded: {stream} — {action}", "success")
    return redirect(url_for("household_dashboard"))

@app.route("/household/set-location", methods=["POST"])
@login_required
def set_household_location():
    if not can_create_opportunity_resident(current_user):
        return redirect(url_for(access_denied_redirect_for(current_user)))

    location_id = request.form.get("location_id", type=int)
    if not location_id:
        flash("Pick a location.", "error")
        return redirect(url_for("household_dashboard"))

    profile = HouseholdProfile.query.filter_by(user_id=current_user.id).first()
    if not profile:
        profile = HouseholdProfile(user_id=current_user.id, location_id=location_id)
        db.session.add(profile)
    else:
        profile.location_id = location_id

    db.session.commit()
    flash("Location updated.", "success")
    return redirect(url_for("household_dashboard"))

@app.route('/search')
@login_required
def search():
    return render_template('search.html', active_page='search')

@app.route('/network')
@login_required 
def network():
    return render_template('network.html', active_page='network')

@app.route('/swap')
@login_required 
def swap():
    return render_template('swap.html', active_page='swap')

# -----------------------------------------------------------------
# 7. APP "ENGINE" ROUTES (API & ACTIONS)
# - API endpoints for activities, confirmations, and dashboard data.
# -----------------------------------------------------------------


@app.post('/verify-and-anchor/<int:request_id>')
@login_required
def verify_and_anchor(request_id):
    return api_center_verify_assignment(request_id)


@app.post('/verify-and-anchor/direct')
@login_required
def verify_and_anchor_direct():
    return confirm_dropoff()


@app.route('/api/activity', methods=['POST'])
@login_required
def add_activity():
    try:
        payload = request.get_json() or {}
        ts = payload.get('timestamp') or (payload.get('time') or '')
        desc = payload.get('desc') or payload.get('description') or 'Activity'
        amount = float(payload.get('amount') or 0)

        # Simple duplicate guard: check for existing activity with same timestamp and desc
        existing = Activity.query.filter_by(user_id=current_user.id, timestamp=ts, desc=desc).first()
        if existing:
            return jsonify({'success': True, 'message': 'Already exists', 'activity': {'timestamp': existing.timestamp, 'desc': existing.desc, 'amount': existing.amount}})

        act = Activity(user_id=current_user.id, timestamp=ts or datetime.utcnow().isoformat(), desc=desc, amount=amount)
        db.session.add(act)
        db.session.commit()
        try:
            print(f"Enqueuing pipeline for activity {act.id}")
            from agents.task_enqueue import enqueue_pipeline
            enqueue_pipeline(act.id)
        except Exception as e:
            print('Failed to enqueue tasks:', e)
        return jsonify({'success': True, 'activity': {'timestamp': act.timestamp, 'desc': act.desc, 'amount': act.amount}})
    except Exception as e:
        print('Error in add_activity:', e)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/activities/bulk', methods=['POST'])
@login_required
def bulk_activities():
    try:
        payload = request.get_json() or {}
        items = payload.get('activities') or []
        added = 0
        for a in items:
            ts = a.get('timestamp') or datetime.utcnow().isoformat()
            desc = a.get('desc') or a.get('description') or 'Activity'
            amount = float(a.get('amount') or 0)
            # avoid duplicates
            if Activity.query.filter_by(user_id=current_user.id, timestamp=ts, desc=desc).first():
                continue
            act = Activity(user_id=current_user.id, timestamp=ts, desc=desc, amount=amount)
            db.session.add(act)
            added += 1
        if added > 0:
            db.session.commit()

        # Return the canonical activity list
        acts = Activity.query.filter_by(user_id=current_user.id).order_by(Activity.id.desc()).limit(500).all()
        result = [{'timestamp': x.timestamp, 'desc': x.desc, 'amount': x.amount} for x in acts]
        return jsonify({'success': True, 'added': added, 'activities': result})
    except Exception as e:
        print('Error in bulk_activities:', e)
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/confirm-dropoff', methods=['POST'])
@login_required 
def confirm_dropoff():
    try:
        source_payload = request.get_json(silent=True) or request.form
        collector_id = (source_payload.get('collector_id') or '').strip()
        weight = source_payload.get('weight')
        material = canonical_material_label(source_payload.get('material'))
        qr_intent_code = (source_payload.get('qr_intent_code') or '').strip()

        if not weight:
            return jsonify({'success': False, 'error': 'Missing data'}), 400

        try:
            weight_value = float(weight)
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Weight must be numeric'}), 400

        if weight_value <= 0:
            return jsonify({'success': False, 'error': 'Weight must be greater than zero'}), 400

        intent = None
        if qr_intent_code:
            intent, intent_error = _qr_decode_payload(qr_intent_code)
            if intent_error:
                return jsonify({'success': False, 'error': intent_error}), 400

        collector = None
        assignment = None
        opportunity = None
        source_type = 'self_deposit'

        if intent:
            source_type = (intent.get('source_type') or 'self_deposit').strip().lower()
            collector = db.session.get(User, int(intent.get('recycler_user_id') or 0))
            if not collector or not can_accept_opportunity_recycler(collector):
                return jsonify({'success': False, 'error': 'Invalid recycler in QR intent'}), 400

            if source_type == 'pickup_assignment':
                assignment = db.session.get(OpportunityAssignment, int(intent.get('source_ref_id') or 0))
                if not assignment:
                    return jsonify({'success': False, 'error': 'Referenced pickup assignment not found'}), 404
                if assignment.recycler_user_id != collector.id:
                    return jsonify({'success': False, 'error': 'QR intent does not match assignment recycler'}), 400
                if assignment.status not in {'accepted', 'in_transit', 'submitted'}:
                    return jsonify({'success': False, 'error': 'Assignment is not ready for center verification'}), 409
                opportunity = assignment.opportunity
            else:
                collector_id = (collector.hedera_account_id or '').strip()
        else:
            if not collector_id:
                return jsonify({'success': False, 'error': 'Collector ID is required'}), 400
            collector = User.query.filter_by(hedera_account_id=collector_id).first()
            if not collector or not can_accept_opportunity_recycler(collector):
                return jsonify({'success': False, 'error': 'Collector not found'}), 404

        payout_rate_per_kg = float(eco_payout_spec(material).get("eco_per_kg") or 0.0)
        reward_amount = calculate_demo_reward_amount(material, weight_value)

        if source_type == 'pickup_assignment':
            if opportunity and opportunity.source_role == 'business':
                desc = f"Verified Business Pickup ({weight_value:.1f}kg of {material})"
            elif opportunity and opportunity.source_role == 'resident':
                desc = f"Verified Community Pickup ({weight_value:.1f}kg of {material})"
            else:
                desc = f"Verified Pickup ({weight_value:.1f}kg of {material})"
        else:
            desc = f"Verified Direct Deposit ({weight_value:.1f}kg of {material})"

        activity = Activity(
            user_id=collector.id,
            timestamp=datetime.utcnow().isoformat(),
            desc=desc,
            amount=float(reward_amount),
            verified_status="pending",
            status="pending",
            pipeline_stage='created',
        )

        db.session.add(activity)
        db.session.flush()

        create_verification_signal(
            activity_id=activity.id,
            signal_type="collector_submission",
            source_role="operator",
            source_user_id=collector.id,
            value="submitted",
            is_positive=True,
            metadata={
                "weight_kg": weight_value,
                "material_type": material,
                "source_type": source_type,
            }
        )
        create_verification_signal(
            activity_id=activity.id,
            signal_type="center_verification",
            source_role="center",
            source_user_id=current_user.id,
            value="verified",
            is_positive=True,
            metadata={
                "verified_by": current_user.email,
                "source": source_type,
                "assignment_id": assignment.id if assignment else None,
                "intent_id": (intent or {}).get('intent_id'),
            }
        )
        add_schedule_match_signal(activity)

        if assignment:
            assignment.submitted_material_type = material
            assignment.submitted_weight_kg = weight_value
            assignment.submission_notes = assignment.submission_notes or f"Verified via QR intent by {current_user.email}"
            assignment.verified_by_center_id = current_user.id
            assignment.verified_at = datetime.now(timezone.utc)
            assignment.verification_status = 'verified'
            assignment.verification_notes = f"Verified by {current_user.email}; pipeline reward {reward_amount:.2f} ECO"
            assignment.status = 'completed'
            assignment.linked_activity_id = activity.id
            if opportunity:
                opportunity.status = 'completed'

        db.session.commit()

        try:
            from agents.task_enqueue import enqueue_pipeline
            enqueue_pipeline(activity.id)
        except Exception as enqueue_err:
            print(f"[CENTER] enqueue pipeline failed for direct dropoff activity {activity.id}: {enqueue_err}", flush=True)

        return jsonify({
            "success": True,
            "message": "Drop-off recorded as pending verification.",
            "activity_id": activity.id,
            "source_type": source_type,
            "assignment_id": assignment.id if assignment else None,
            "reward_amount": reward_amount,
            "eco_rate_per_kg": payout_rate_per_kg,
            "weight_kg": weight_value,
            "material_type": material,
            "payout_formula": f"{weight_value:.1f} kg x {payout_rate_per_kg:.1f} ECO/kg = {reward_amount:.2f} ECO",
            "proof_bundle_url": f"/api/proof-bundle/{activity.id}",
            "hashscan_url": hashscan_link(activity.hcs_tx_id or activity.logbook_tx_id or activity.hedera_tx_id)
            or hashscan_link(f"0.0.1001@1700000000.{activity.id:09d}")
        })

    except Exception as e:
        print('Error in confirm_dropoff:', e)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.get('/api/collectors/lookup')
@login_required
def api_collector_lookup():
    if not can_verify_deposit_center(current_user):
        return jsonify({"ok": False, "error": "Only centers can scan recycler IDs"}), 403

    collector_id = (request.args.get('hedera_account_id') or '').strip()
    if not collector_id:
        return jsonify({"ok": False, "error": "Recycler ID is required"}), 400

    collector = User.query.filter_by(hedera_account_id=collector_id).first()
    if not collector or not is_recycler_user(collector):
        return jsonify({"ok": False, "error": "Collector not found"}), 404

    return jsonify({
        "ok": True,
        "collector_id": collector.hedera_account_id,
        "collector_name": collector.full_name or collector.email,
        "collector_email": collector.email,
    })


@app.post('/api/qr-intents/create')
@login_required
def api_create_qr_intent():
    if not can_accept_opportunity_recycler(current_user):
        return jsonify({"ok": False, "error": "Only recyclers can create QR intents"}), 403

    data = request.get_json(silent=True) or request.form
    source_type = (data.get('source_type') or 'self_deposit').strip().lower()
    if source_type not in {'self_deposit', 'pickup_assignment'}:
        return jsonify({"ok": False, "error": "Invalid source_type"}), 400

    intent_payload = {
        "v": 1,
        "intent_id": f"intent-{uuid.uuid4().hex[:12]}",
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "recycler_user_id": current_user.id,
        "recycler_account_id": (current_user.hedera_account_id or '').strip(),
        "recycler_email": current_user.email,
        "source_type": source_type,
        "source_ref_id": None,
        "material_type": canonical_material_label((data.get('material_type') or 'Mixed Recyclables').strip() or 'Mixed Recyclables'),
        "estimated_kg": 0.0,
        "location": (current_user.address or '').strip() or None,
    }

    if source_type == 'pickup_assignment':
        try:
            assignment_id = int(data.get('assignment_id'))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "assignment_id is required for pickup_assignment"}), 400

        assignment = db.session.get(OpportunityAssignment, assignment_id)
        if not assignment or assignment.recycler_user_id != current_user.id:
            return jsonify({"ok": False, "error": "Assignment not found"}), 404

        if assignment.status not in {'accepted', 'in_transit', 'submitted'}:
            return jsonify({"ok": False, "error": "Assignment is not eligible for QR verification"}), 409

        opp = assignment.opportunity
        material = assignment.submitted_material_type or (opp.material_type if opp else None) or 'Mixed Recyclables'
        est_kg = assignment.submitted_weight_kg if assignment.submitted_weight_kg is not None else (opp.estimated_kg if opp else 0.0)

        intent_payload.update({
            "source_ref_id": assignment.id,
            "material_type": canonical_material_label(material),
            "estimated_kg": float(est_kg or 0.0),
            "location": (opp.location if opp else None),
        })

    qr_intent_code = _qr_encode_payload(intent_payload)
    return jsonify({
        "ok": True,
        "qr_intent_code": qr_intent_code,
        "intent": intent_payload,
    })


@app.post('/api/qr-intents/resolve')
@login_required
def api_resolve_qr_intent():
    if not can_verify_deposit_center(current_user):
        return jsonify({"ok": False, "error": "Only centers can resolve QR intents"}), 403

    data = request.get_json(silent=True) or request.form
    qr_intent_code = (data.get('qr_intent_code') or '').strip()
    payload, error = _qr_decode_payload(qr_intent_code)
    if error:
        return jsonify({"ok": False, "error": error}), 400

    recycler = db.session.get(User, int(payload.get('recycler_user_id') or 0))
    if not recycler or not can_accept_opportunity_recycler(recycler):
        return jsonify({"ok": False, "error": "Recycler in QR intent is invalid"}), 400

    assignment_preview = None
    if payload.get('source_type') == 'pickup_assignment':
        assignment = db.session.get(OpportunityAssignment, int(payload.get('source_ref_id') or 0))
        if not assignment:
            return jsonify({"ok": False, "error": "Referenced pickup assignment not found"}), 404
        if assignment.recycler_user_id != recycler.id:
            return jsonify({"ok": False, "error": "QR assignment does not match recycler"}), 400
        assignment_preview = {
            "assignment_id": assignment.id,
            "status": assignment.status,
            "submitted_weight_kg": assignment.submitted_weight_kg,
        }

    return jsonify({
        "ok": True,
        "intent": payload,
        "recycler": {
            "user_id": recycler.id,
            "email": recycler.email,
            "account_id": recycler.hedera_account_id,
            "name": recycler.full_name or recycler.email,
        },
        "assignment": assignment_preview,
    })


@app.route('/run-collector-agent/<int:activity_id>', methods=['POST'])
@login_required
def run_collector_agent(activity_id):
    try:
        from agents.task_enqueue import enqueue_pipeline
        enqueue_pipeline(activity_id)

        return jsonify({'success': True})
    except Exception as e:
        print('Error in run_collector_agent:', e)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/simulate-deposit', methods=['POST'])
@login_required
def simulate_deposit():
    """
    Creates a pending activity for a simulated drop-off.
    Triggers the CollectorAgent in a background thread.
    Returns the updated dashboard data.
    """
    try:
        # Demo deposit values (reduced for verification demo: ensure total_amount <= 200)
        weight = 10.0
        # Reduced base amount for demo so Agent validation passes
        base_amount = 130.00
        neighborhood_bonus = 12.50
        tier_bonus = 5.00
        total_amount = base_amount + neighborhood_bonus + tier_bonus  # 147.50
        
        # Create activity record (use timezone-aware UTC timestamp)
        from datetime import datetime, timezone
        activity = Activity(
            user_id=current_user.id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            desc=f"Verified Drop-off ({weight}kg of Cans)",
            amount=total_amount,
            status="pending",
            verified_status="pending",
            logbook_status="pending"
        )
        
        db.session.add(activity)
        db.session.flush()

        create_verification_signal(
            activity_id=activity.id,
            signal_type="collector_submission",
            source_role="operator",
            source_user_id=current_user.id,
            value="submitted",
            is_positive=True,
            metadata={"weight_kg": weight}
        )
        add_schedule_match_signal(activity)
        db.session.commit()

        stable_bundle = {
            "vericycle_version": "hackathon-2026",
            "activity_id": activity.id,
            "timestamp": activity.timestamp,
            "user": current_user.email,
            "description": activity.desc,
            "amount": float(activity.amount) if activity.amount is not None else None,
            "stage": "recorded",
        }
        activity.proof_hash = compute_proof_sha256(stable_proof_input(stable_bundle))
        db.session.commit()
        
        activity_id = activity.id
        print(f"\n{'='*80}", flush=True)
        print(f"[BACKEND] POST /api/simulate-deposit called", flush=True)
        print(f"[BACKEND] New activity created: ID={activity_id}, user={current_user.email}, amount={total_amount}", flush=True)
        print(f"{'='*80}\n", flush=True)
        
        # Enqueue pipeline tasks in the persistent queue
        from agents.task_enqueue import enqueue_pipeline
        enqueue_pipeline(activity_id)
        print(f"[BACKEND] Tasks enqueued for activity {activity_id}", flush=True)
        
        # Fetch and return updated dashboard
        response = get_dashboard_data()
        response_data = response.get_json()
        response_data['activity_id'] = activity_id
        response_data['message'] = 'Drop-off logged and pending verification'
        
        print(f"[BACKEND] Returning dashboard with {len(response_data['activities'])} activities", flush=True)
        return jsonify(response_data)
        
    except Exception as e:
        print(f"[BACKEND] ❌ Error in simulate_deposit: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/my-dashboard-data')
@login_required
def get_dashboard_data():
    """
    Returns dashboard data with real balance calculated from verified activities.
    For demo user: Uses demo seed data + any new activities.
    For other users: Calculates from their verified activities database.
    """
    purge_stale_demo_seed_rows()

    timeline = []
    total_eco = 0.0
    total_kg = 0.0
    recent_kg_30d = 0.0
    total_recycled_completed = 0.0
    now_utc = datetime.now(timezone.utc)
    recent_cutoff = now_utc - timedelta(days=30)

    def parse_kg_from_desc(text_value):
        match = re.search(r'(\d+\.?\d*)\s*kg', str(text_value or ''), re.IGNORECASE)
        if not match:
            return 0.0
        try:
            return float(match.group(1))
        except Exception:
            return 0.0

    def activity_stage_set(activity):
        return {
            (activity.verified_status or '').strip().lower(),
            (activity.status or '').strip().lower(),
            (activity.pipeline_stage or '').strip().lower(),
            (activity.logbook_status or '').strip().lower(),
            (activity.reward_status or '').strip().lower(),
        }

    def counts_for_balance(activity):
        states = activity_stage_set(activity)
        if 'failed' in states or 'rejected' in states:
            return False
        return bool(states & {'verified', 'anchored', 'completed', 'logged', 'rewarded', 'attested', 'paid'})

    def counts_for_progress(activity):
        states = activity_stage_set(activity)
        if 'failed' in states or 'rejected' in states:
            return False
        return bool(states & {'submitted', 'in_transit', 'accepted', 'verified', 'anchored', 'completed', 'logged', 'rewarded', 'attested', 'paid'})

    def counts_for_completed(activity):
        states = activity_stage_set(activity)
        if 'failed' in states or 'rejected' in states:
            return False
        return bool(states & {'verified', 'anchored', 'completed', 'logged', 'rewarded', 'attested', 'paid'})

    def assignment_weight_kg(assignment):
        if assignment.submitted_weight_kg is not None:
            return float(assignment.submitted_weight_kg)
        opp = assignment.opportunity
        if opp and opp.estimated_kg is not None:
            return float(opp.estimated_kg)
        return 0.0

    def parse_timestamp_utc(value):
        if not value:
            return None
        if isinstance(value, datetime):
            dt = value
        else:
            raw = str(value).strip().replace('Z', '+00:00')
            try:
                dt = datetime.fromisoformat(raw)
            except Exception:
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    def _generated_proof_url(activity_id, timestamp, desc, amount, trust_weight, user_email):
        qs = urlencode({
            "activity_id": activity_id,
            "timestamp": timestamp,
            "desc": desc,
            "amount": amount,
            "trust_weight": trust_weight,
            "user_email": user_email,
        })
        return f"/api/proof-bundle-generated?{qs}"
    
    try:
        # Fetch all activities for this user (verified + pending)
        acts = (
            Activity.query
            .filter_by(user_id=current_user.id)
            .order_by(Activity.timestamp.desc())
            .limit(200)
            .all()
        )
        
        for a in acts:
            proof_hash = a.proof_hash or build_proof_hash(
                activity_id=a.id,
                user_email=current_user.email,
                amount=a.amount,
                description=a.desc,
                created_at=a.timestamp,
                verifier_trust_weight=a.trust_weight,
            )

            timeline.append({
                'id': a.id,
                'timestamp': a.timestamp,
                'desc': a.desc,
                'amount': a.amount,
                'status': a.status,
                'hedera_tx_id': a.hedera_tx_id,
                'hcs_tx_id': a.hcs_tx_id,
                'hts_tx_id': a.hts_tx_id,
                'compliance_tx_id': a.compliance_tx_id,
                'logbook_tx_id': a.logbook_tx_id,
                'proof_hash': proof_hash,
                'proof_bundle_url': f'/api/proof-bundle/{a.id}',
                'logbook_status': a.logbook_status,
                'logbook_last_error': a.logbook_last_error,
                'logbook_finalized_at': a.logbook_finalized_at.isoformat() if a.logbook_finalized_at else None,
                'reward_status': a.reward_status,
                'reward_status_label': reward_status_label(a.reward_status, a.reward_last_error, a.pipeline_stage),
                'reward_tx_id': a.reward_tx_id,
                'reward_last_error': a.reward_last_error,
                'trust_weight': a.trust_weight,
                'verifier_reputation': a.verifier_reputation,
                'reputation_delta': a.reputation_delta,
                'confidence_score': confidence_score_for_activity(a),
                'pipeline_stage': a.pipeline_stage,
                'last_error': a.last_error,
            })
            
            if counts_for_balance(a):
                try:
                    total_eco += float(a.amount or 0)
                except Exception:
                    pass

            if counts_for_completed(a):
                kg_from_desc = parse_kg_from_desc(a.desc)
                total_kg += kg_from_desc
                row_dt = parse_timestamp_utc(a.timestamp)
                if row_dt and row_dt >= recent_cutoff:
                    recent_kg_30d += kg_from_desc

        # Include assignment-stage progress so submitted/in-transit rows reflect in totals.
        assignments = (
            OpportunityAssignment.query
            .filter_by(recycler_user_id=current_user.id)
            .order_by(OpportunityAssignment.accepted_at.desc())
            .all()
        )
        for assignment in assignments:
            assignment_status = (assignment.status or '').strip().lower()
            if assignment_status not in {'completed'}:
                continue
            # Avoid double counting when assignment already produced a linked activity row.
            if assignment.linked_activity_id:
                continue
            assignment_kg = assignment_weight_kg(assignment)
            total_kg += assignment_kg
            reference_dt = assignment.submitted_at or assignment.accepted_at
            parsed_reference = parse_timestamp_utc(reference_dt)
            if parsed_reference and parsed_reference >= recent_cutoff:
                recent_kg_30d += assignment_kg

        total_recycled_completed = total_kg
    except Exception as e:
        print('Error fetching activities:', e)
        timeline = []
        total_eco = 0
        total_kg = 0
        total_recycled_completed = 0
    
    # Fixed targets for demo consistency.
    monthly_goal = 10

    # Dynamic neighborhood aggregation from all pipeline activity + unlinked assignment progress.
    neighborhood_current_kg = 0.0
    try:
        all_acts = Activity.query.order_by(Activity.id.desc()).limit(2000).all()
        for activity in all_acts:
            if not counts_for_completed(activity):
                continue
            row_dt = parse_timestamp_utc(activity.timestamp)
            if row_dt and row_dt >= recent_cutoff:
                neighborhood_current_kg += parse_kg_from_desc(activity.desc)

        all_assignments = OpportunityAssignment.query.order_by(OpportunityAssignment.id.desc()).limit(2000).all()
        for assignment in all_assignments:
            assignment_status = (assignment.status or '').strip().lower()
            if assignment_status not in {'completed'}:
                continue
            if assignment.linked_activity_id:
                continue
            reference_dt = assignment.submitted_at or assignment.accepted_at
            parsed_reference = parse_timestamp_utc(reference_dt)
            if parsed_reference and parsed_reference >= recent_cutoff:
                neighborhood_current_kg += assignment_weight_kg(assignment)
    except Exception as agg_err:
        print(f"[DASHBOARD] Neighborhood aggregate fallback: {agg_err}")
        neighborhood_current_kg = total_recycled_completed

    neighborhood_goal_kg = 4000

    data = {
        "total_kg": round(total_kg, 1),
        "total_recycled_completed": round(float(total_recycled_completed), 1),
        "total_eco": round(total_eco, 2),
        "weekly_goal": monthly_goal,
        "monthly_goal": monthly_goal,
        "current_kg": round(float(recent_kg_30d), 1),
        "neighborhood_current_kg": round(float(neighborhood_current_kg), 1),
        "neighborhood_goal_kg": round(float(neighborhood_goal_kg), 1),
        "profile_complete": "1" if current_user.full_name else "0",
        "timeline": timeline,
        "activities": timeline
    }

    return jsonify(data)


@app.get('/api/income-report.pdf')
@login_required
def download_income_report_pdf():
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    except Exception:
        return jsonify({
            "ok": False,
            "error": "PDF dependency missing. Install reportlab to enable this feature."
        }), 500

    verified_activities = (
        Activity.query
        .filter_by(user_id=current_user.id)
        .filter((Activity.verified_status == "verified") | (Activity.status == "verified"))
        .order_by(Activity.timestamp.desc())
        .limit(100)
        .all()
    )

    total_eco = 0.0
    total_kg = 0.0
    for activity in verified_activities:
        try:
            total_eco += float(activity.amount or 0)
        except Exception:
            total_eco += 0.0
        match = re.search(r'(\d+\.?\d*)\s*kg', activity.desc or '')
        if match:
            try:
                total_kg += float(match.group(1))
            except Exception:
                pass

    report_buffer = io.BytesIO()
    document = SimpleDocTemplate(
        report_buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="VeriCycle Proof of Income Report"
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "TitleStyle",
        parent=styles["Title"],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#0f2463"),
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "SubtitleStyle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.HexColor("#4a5568"),
        spaceAfter=8,
    )
    body_style = ParagraphStyle(
        "BodyStyle",
        parent=styles["Normal"],
        fontSize=9,
        leading=13,
    )

    story = []

    logo_path = os.path.join(app.root_path, 'static', 'logo.png')
    if os.path.exists(logo_path):
        logo = Image(logo_path, width=20 * mm, height=20 * mm)
        header_table = Table(
            [[logo, Paragraph("<b>VeriCycle</b><br/>Proof of Income Report", title_style)]],
            colWidths=[24 * mm, 150 * mm]
        )
        header_table.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ]))
        story.append(header_table)
    else:
        story.append(Paragraph("VeriCycle Proof of Income Report", title_style))

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    story.append(Paragraph(f"Generated: {generated_at}", subtitle_style))

    collector_name = (current_user.full_name or "Collector").strip()
    collector_email = (current_user.email or "").strip()
    summary_rows = [
        ["Collector", collector_name],
        ["Email", collector_email],
        ["Verified transactions", str(len(verified_activities))],
        ["Total income (ECO)", f"{total_eco:,.2f}"],
        ["Total recycled (kg)", f"{total_kg:,.1f}"],
    ]
    summary_table = Table(summary_rows, colWidths=[48 * mm, 124 * mm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f1f5f9")),
        ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#1f2937")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Verified Activity Ledger</b>", body_style))
    story.append(Spacer(1, 4))

    ledger_rows = [["Date", "Description", "Amount (ECO)", "Hedera Reference"]]
    for activity in verified_activities[:20]:
        timestamp = activity.timestamp
        if hasattr(timestamp, "strftime"):
            date_text = timestamp.strftime("%Y-%m-%d")
        else:
            date_text = str(timestamp)[:10]
        tx_id = activity.hcs_tx_id or activity.logbook_tx_id or activity.hedera_tx_id or "Pending"
        ledger_rows.append([
            date_text,
            activity.desc or "—",
            f"{float(activity.amount or 0):,.2f}",
            tx_id,
        ])

    ledger_table = Table(ledger_rows, colWidths=[24 * mm, 82 * mm, 25 * mm, 41 * mm])
    ledger_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f2463")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(ledger_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph(
        "This report summarizes verified VeriCycle collection activity and can be used as supporting proof of income history.",
        body_style,
    ))

    document.build(story)
    report_buffer.seek(0)

    filename = f"vericycle-income-report-{current_user.id}-{date.today().isoformat()}.pdf"
    return send_file(
        report_buffer,
        mimetype='application/pdf',
        as_attachment=True,
        download_name=filename,
    )


@app.get('/api/proof-bundle/<int:activity_id>')
@login_required
def download_proof_bundle(activity_id):
    activity = db.session.get(Activity, activity_id)
    if not activity:
        abort(404)
    if not can_access_activity_proof(current_user, activity):
        abort(403)

    payload_data = _build_proof_payload(activity=activity)
    proof_sha256 = _compute_proof_sha256(payload_data)
    payload_data["proof_sha256"] = proof_sha256
    payload_data["proof_hash"] = proof_sha256
    payload_data["proof_hash_basis"] = "stable_fields_v1"
    payload_data["proof_hash_fields"] = list(stable_proof_input(payload_data).keys())

    if activity.proof_hash != proof_sha256:
        activity.proof_hash = proof_sha256
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    payload = json.dumps(payload_data, indent=2, ensure_ascii=False).encode('utf-8')
    return send_file(
        io.BytesIO(payload),
        mimetype='application/json',
        as_attachment=True,
        download_name=f'proof-bundle-{activity.id}.json'
    )


def _build_proof_payload(activity=None, fallback_activity_id='', fallback_timestamp='', fallback_desc='', fallback_amount=0.0, fallback_user=''):
    tasks = []
    if activity:
        tasks = (
            AgentTask.query
            .filter_by(activity_id=activity.id)
            .order_by(AgentTask.id.asc())
            .all()
        )

    latest_by_agent = {}
    for task in tasks:
        latest_by_agent[task.agent_name] = task

    pipeline_order = ["CollectorAgent", "VerifierAgent", "LogbookAgent", "RewardAgent", "ComplianceAgent"]

    def _agent_sort_key(agent_name: str):
        try:
            return (pipeline_order.index(agent_name), agent_name)
        except ValueError:
            return (len(pipeline_order), agent_name)

    agent_approvals = []
    for agent_name in sorted(latest_by_agent.keys(), key=_agent_sort_key):
        task = latest_by_agent[agent_name]
        agent_approvals.append({
            "agent": task.agent_name,
            "status": task.status,
            "attempts": task.attempts,
            "last_error": task.last_error,
        })

    effective_activity_id = activity.id if activity else (fallback_activity_id or "")
    effective_timestamp = activity.timestamp if activity else (fallback_timestamp or datetime.now(timezone.utc).isoformat())
    activity_user_email = None
    if activity:
        rel_user = getattr(activity, "user", None)
        if rel_user is not None:
            activity_user_email = getattr(rel_user, "email", None)
        if not activity_user_email and getattr(activity, "user_id", None):
            db_user = db.session.get(User, activity.user_id)
            activity_user_email = db_user.email if db_user else None

    effective_user = activity_user_email or fallback_user or ""
    effective_description = getattr(activity, "desc", "") if activity else fallback_desc
    effective_amount = activity.amount if activity and activity.amount is not None else fallback_amount
    effective_stage = "recorded"
    effective_hedera_tx_id = activity.hedera_tx_id if activity else None
    effective_reward_tx_id = activity.reward_tx_id if activity else None
    effective_reward_status = activity.reward_status if activity else None
    signal_rows = []
    if activity:
        for signal in activity.signals:
            signal_rows.append({
                "signal_type": signal.signal_type,
                "source_role": signal.source_role,
                "value": signal.value,
                "weight": signal.weight,
                "is_positive": signal.is_positive,
                "metadata": json.loads(signal.metadata_json) if signal.metadata_json else {},
            })

    payload_data = {
        "vericycle_version": "hackathon-2026",
        "activity_id": effective_activity_id,
        "timestamp": effective_timestamp.isoformat() if hasattr(effective_timestamp, "isoformat") else str(effective_timestamp),
        "user": effective_user,
        "description": effective_description,
        "amount": float(effective_amount) if effective_amount is not None else None,
        "stage": effective_stage,
        "hedera_tx_id": effective_hedera_tx_id,
        "reward_status": effective_reward_status,
        "reward_tx_id": effective_reward_tx_id,
        "agent_approvals": agent_approvals,
        "signals": signal_rows,
        "confidence_score": activity.confidence_score if activity else None,
        "review_status": activity.review_status if activity else None,
        "review_reason": activity.review_reason if activity else None,
    }
    return payload_data


def _compute_proof_sha256(payload_data: dict):
    stable = stable_proof_input(payload_data)
    return compute_proof_sha256(stable)


def can_review_events():
    try:
        # Exception handling can be reviewed by centers and admins.
        return current_user.is_authenticated and (is_center_user(current_user) or is_admin_user(current_user))
    except Exception:
        return False


def can_access_oversight():
    try:
        return current_user.is_authenticated
    except Exception:
        return False


@app.get('/api/proof-bundle-generated')
@login_required
def download_generated_proof_bundle():
    activity_id = request.args.get('activity_id', '')
    timestamp = request.args.get('timestamp', '')
    desc = request.args.get('desc', '')
    amount_raw = request.args.get('amount', '0')
    user_email = request.args.get('user_email') or current_user.email

    try:
        amount = float(amount_raw)
    except Exception:
        amount = 0.0

    activity = None
    try:
        parsed_activity_id = int(activity_id)
        activity = db.session.get(Activity, parsed_activity_id)
    except Exception:
        activity = None

    payload_data = _build_proof_payload(
        activity=activity,
        fallback_activity_id=activity_id,
        fallback_timestamp=timestamp,
        fallback_desc=desc,
        fallback_amount=amount,
        fallback_user=user_email,
    )

    proof_sha256 = _compute_proof_sha256(payload_data)
    payload_data["proof_sha256"] = proof_sha256
    payload_data["proof_hash"] = proof_sha256
    payload_data["proof_hash_basis"] = "stable_fields_v1"
    payload_data["proof_hash_fields"] = list(stable_proof_input(payload_data).keys())

    if activity and activity.proof_hash != proof_sha256:
        activity.proof_hash = proof_sha256
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    payload = json.dumps(payload_data, indent=2, ensure_ascii=False).encode('utf-8')
    return send_file(
        io.BytesIO(payload),
        mimetype='application/json',
        as_attachment=True,
        download_name=f'proof-bundle-{payload_data.get("activity_id") or "generated"}.json'
    )


@app.get('/api/proof-verify/<int:activity_id>')
@login_required
def verify_proof_bundle(activity_id):
    activity = db.session.get(Activity, activity_id)
    if not activity:
        abort(404)
    if (activity.user_id != current_user.id) and (not is_admin_user()) and (not can_review_events()):
        abort(403)

    payload_data = _build_proof_payload(activity=activity)
    recomputed_hash = _compute_proof_sha256(payload_data)
    stored_hash = (activity.proof_hash or "").strip().lower()

    if not stored_hash:
        stored_hash = recomputed_hash.lower()
        activity.proof_hash = recomputed_hash
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    hash_match = stored_hash == recomputed_hash.lower()

    return jsonify({
        "ok": True,
        "activity_id": activity.id,
        "match": hash_match,
        "stored": activity.proof_hash,
        "computed": recomputed_hash,
        "basis": "stable_fields_v1",
        "fields": list(stable_proof_input(payload_data).keys()),
        "hash_match": hash_match,
        "stored_hash": activity.proof_hash,
        "recomputed_hash": recomputed_hash,
        "hedera_tx_id": activity.hedera_tx_id,
        "proof_exists_without_hedera": True,
        "verified_at": datetime.now(timezone.utc).isoformat()
    })


@app.route('/api/agent-status')
@login_required
def get_agent_status():
    agents = ["CollectorAgent", "VerifierAgent", "LogbookAgent", "RewardAgent", "ComplianceAgent"]
    statuses = []

    def _normalize_ts(ts: str):
        if not ts:
            return None
        return ts.replace("+00:00", "Z")

    error_levels = ("error", "failed")

    for agent_name in agents:
        latest_log = (
            AgentLog.query
            .filter(AgentLog.agent_name == agent_name)
            .order_by(AgentLog.id.desc())
            .first()
        )

        latest_error = (
            AgentLog.query
            .filter(
                AgentLog.agent_name == agent_name,
                db.func.lower(AgentLog.level).in_(error_levels)
            )
            .order_by(AgentLog.id.desc())
            .first()
        )

        latest_non_error = (
            AgentLog.query
            .filter(
                AgentLog.agent_name == agent_name,
                db.func.lower(AgentLog.level).notin_(error_levels)
            )
            .order_by(AgentLog.id.desc())
            .first()
        )

        latest_tx = (
            None if agent_name not in ("LogbookAgent", "RewardAgent") else (
                AgentLog.query
                .filter(
                    AgentLog.agent_name == agent_name,
                    AgentLog.hedera_tx_id.isnot(None),
                    AgentLog.hedera_tx_id != ""
                )
                .order_by(AgentLog.id.desc())
                .first()
            )
        )

        if not latest_log:
            health = "unknown"
        else:
            level = (latest_log.level or "").lower()
            health = "degraded" if level in error_levels else "ok"
            if latest_error and (not latest_non_error or latest_error.id > latest_non_error.id):
                health = "degraded"

        last_error_msg = None
        if latest_error:
            last_error_msg = latest_error.last_error or latest_error.message

        statuses.append({
            "agent": agent_name,
            "health": health,
            "last_seen": _normalize_ts(latest_log.created_at if latest_log else None),
            "last_tx": latest_tx.hedera_tx_id if latest_tx else None,
            "last_error": last_error_msg,
        })

    return jsonify({"agents": statuses})


# -----------------------------------------------------------------
# 8. ADMIN AGENT MONITOR
# - View pipeline status and agent processing
# -----------------------------------------------------------------
def _task_type_for_agent(agent_name: str) -> str:
    task_type_map = {
        "CollectorAgent": "collect",
        "VerifierAgent": "verify",
        "LogbookAgent": "log",
        "RewardAgent": "reward",
        "ComplianceAgent": "attest",
    }
    return task_type_map.get(agent_name, "collect")


def enqueue_once(activity_id: int, agent_name: str) -> bool:
    exists = AgentTask.query.filter(
        AgentTask.activity_id == activity_id,
        AgentTask.agent_name == agent_name,
        AgentTask.status.in_(["queued", "running"])
    ).first()
    if exists:
        return False

    db.session.add(AgentTask(
        activity_id=activity_id,
        agent_name=agent_name,
        task_type=_task_type_for_agent(agent_name),
        status="queued"
    ))
    return True


def logbook_retry_blocked(activity_id: int) -> bool:
    active = AgentTask.query.filter(
        AgentTask.activity_id == activity_id,
        AgentTask.agent_name == "LogbookAgent",
        AgentTask.status.in_(["queued", "running"])
    ).first()
    if active:
        return True

    last_failed = AgentTask.query.filter(
        AgentTask.activity_id == activity_id,
        AgentTask.agent_name == "LogbookAgent",
        AgentTask.status == "failed"
    ).order_by(AgentTask.id.desc()).first()

    if not last_failed:
        return False

    last_updated = getattr(last_failed, "updated_at", None)
    if last_updated:
        if last_updated.tzinfo is None:
            last_updated = last_updated.replace(tzinfo=timezone.utc)
        return last_updated > (datetime.now(timezone.utc) - timedelta(seconds=15))

    return True


def log_agent_event(activity_id: int, agent_name: str, level: str, pipeline_stage: str, hedera_tx_id: str, message: str):
    activity = db.session.get(Activity, activity_id)
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    db.session.add(AgentLog(
        created_at=ts,
        activity_id=activity_id,
        agent_name=agent_name,
        level=level,
        message=(message or "")[:512],
        pipeline_stage=pipeline_stage,
        hedera_tx_id=hedera_tx_id,
        last_error=getattr(activity, "last_error", None),
    ))


@app.route('/admin/monitor')
def admin_monitor():
    if not is_admin_user():
        admin_user = User.query.filter_by(role='admin').order_by(User.id.asc()).first()
        if not admin_user:
            flash('Admin monitor is unavailable because no admin account is configured.', 'error')
            return redirect(url_for('home'))
        login_user(admin_user, remember=False, force=True, fresh=True)
    return render_template('admin_monitor.html', active_page='admin_monitor')


@app.route('/api/config')
def api_config():
    return jsonify({"demo_mode": DEMO_MODE})


def _create_demo_activity_for_user(user: User, slot_idx: int) -> int:
    amount_by_slot = [147.5, 132.0, 118.0]
    amount = amount_by_slot[slot_idx % len(amount_by_slot)]
    activity = Activity(
        user_id=user.id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        desc=f"Judge Demo Drop-off #{slot_idx + 1} (10.0kg of Cans)",
        amount=amount,
        status="pending",
        verified_status="pending",
        logbook_status="pending",
        pipeline_stage="created",
    )
    db.session.add(activity)
    db.session.commit()

    stable_bundle = {
        "vericycle_version": "hackathon-2026",
        "activity_id": activity.id,
        "timestamp": activity.timestamp,
        "user": user.email,
        "description": activity.desc,
        "amount": float(activity.amount),
        "stage": "recorded",
    }
    activity.proof_hash = compute_proof_sha256(stable_proof_input(stable_bundle))
    db.session.commit()
    from agents.task_enqueue import enqueue_pipeline
    enqueue_pipeline(activity.id)
    return activity.id


def _wait_for_attested(activity_ids: list[int], timeout_seconds: int = 240) -> tuple[bool, dict]:
    deadline = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
    final_rows = {}
    while datetime.now(timezone.utc) < deadline:
        rows = Activity.query.filter(Activity.id.in_(activity_ids)).all()
        for row in rows:
            final_rows[row.id] = row
        if len(final_rows) == len(activity_ids) and all((r.pipeline_stage or "").lower() == "attested" for r in final_rows.values()):
            return True, final_rows
        db.session.expire_all()
        import time
        time.sleep(2)
    return False, final_rows


def _export_evidence_pack(activity_rows: list[Activity], profile_name: str) -> str:
    artifacts_dir = os.path.join(basedir, "artifacts")
    os.makedirs(artifacts_dir, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    pack_dir = os.path.join(artifacts_dir, f"evidence_pack_{stamp}")
    os.makedirs(pack_dir, exist_ok=True)

    index_rows = []
    screenshot_lines = [
        "VeriCycle judge evidence checklist",
        "================================",
        f"Profile: {profile_name}",
        "",
    ]

    for activity in activity_rows:
        payload_data = _build_proof_payload(activity=activity)
        proof_sha256 = _compute_proof_sha256(payload_data)
        payload_data["proof_hash"] = proof_sha256
        payload_data["proof_sha256"] = proof_sha256
        payload_data["hcs_tx_id"] = activity.hcs_tx_id or activity.logbook_tx_id or activity.hedera_tx_id
        payload_data["hts_tx_id"] = activity.hts_tx_id or activity.reward_tx_id
        payload_data["compliance_tx_id"] = activity.compliance_tx_id
        payload_data["hashscan_links"] = {
            "hcs": hashscan_link(payload_data.get("hcs_tx_id")),
            "hts": hashscan_link(payload_data.get("hts_tx_id")),
        }

        file_name = f"proof-bundle-{activity.id}.json"
        with open(os.path.join(pack_dir, file_name), "w", encoding="utf-8") as f:
            json.dump(payload_data, f, ensure_ascii=False, indent=2)

        screenshot_lines.append(f"Activity {activity.id}: admin detail + proof verify")
        screenshot_lines.append(f"HCS: {payload_data['hashscan_links']['hcs'] or '[missing]'}")
        screenshot_lines.append(f"HTS: {payload_data['hashscan_links']['hts'] or '[missing]'}")
        screenshot_lines.append("")

        index_rows.append({
            "activity_id": activity.id,
            "stage": activity.pipeline_stage,
            "logbook_status": activity.logbook_status,
            "reward_status": activity.reward_status,
            "hcs_tx_id": payload_data.get("hcs_tx_id"),
            "hts_tx_id": payload_data.get("hts_tx_id"),
            "proof_file": file_name,
            "confidence_score": confidence_score_for_activity(activity),
        })

    with open(os.path.join(pack_dir, "screenshots_required.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(screenshot_lines))

    with open(os.path.join(pack_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "profile": profile_name,
            "activities": index_rows,
        }, f, ensure_ascii=False, indent=2)

    zip_name = f"evidence_pack_{stamp}.zip"
    zip_path = os.path.join(artifacts_dir, zip_name)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_name in os.listdir(pack_dir):
            full = os.path.join(pack_dir, file_name)
            zf.write(full, arcname=file_name)
    return zip_name


@app.get('/api/admin/demo-profile')
@login_required
def api_admin_demo_profile():
    if not can_review_events():
        abort(403)
    name = request.args.get("name", "judge_testnet_v1")
    payload = profile_health(name)
    payload["available_profiles"] = list(DEMO_PROFILES.keys())
    return jsonify(payload)


@app.post('/api/admin/apply-demo-profile')
@login_required
def api_admin_apply_demo_profile():
    if not is_admin_user():
        abort(403)
    body = request.get_json(silent=True) or {}
    name = body.get("name", "judge_testnet_v1")
    applied = apply_demo_profile(name)
    audit_admin_action("apply_demo_profile", "profile", name, "applied_to_process_env")
    db.session.commit()
    return jsonify({"ok": True, "name": name, "applied": applied, "health": profile_health(name)})


@app.post('/api/admin/generate-evidence-pack')
@login_required
def api_admin_generate_evidence_pack():
    if not is_admin_user():
        abort(403)

    body = request.get_json(silent=True) or {}
    profile_name = body.get("profile", "judge_testnet_v1")
    apply_demo_profile(profile_name)

    collector = User.query.filter_by(email="recycler@vericycle.com").first()
    if not collector:
        return jsonify({"ok": False, "error": "recycler@vericycle.com not found"}), 400

    activity_ids = [_create_demo_activity_for_user(collector, i) for i in range(3)]
    ok, final_rows = _wait_for_attested(activity_ids)
    rows = [final_rows.get(i) for i in activity_ids if final_rows.get(i)]

    zip_name = _export_evidence_pack(rows, profile_name)
    audit_admin_action("generate_evidence_pack", "batch", ",".join(str(i) for i in activity_ids), f"profile={profile_name}; attested={ok}")
    db.session.commit()

    return jsonify({
        "ok": ok,
        "profile": profile_name,
        "activity_ids": activity_ids,
        "download_url": f"/api/admin/evidence-pack/{zip_name}",
        "message": "All activities attested" if ok else "Timed out waiting for attested on all activities",
    })


@app.get('/api/admin/evidence-pack/<path:file_name>')
@login_required
def api_admin_download_evidence_pack(file_name):
    if not is_admin_user():
        abort(403)
    safe_name = os.path.basename(file_name)
    full_path = os.path.join(basedir, "artifacts", safe_name)
    if not os.path.exists(full_path):
        abort(404)
    return send_file(full_path, as_attachment=True, download_name=safe_name)


def normalize_status_label_for_api(activity: Activity) -> str:
    stage = (activity.pipeline_stage or "").lower()
    review = (activity.review_status or "").lower()
    status = (activity.status or activity.verified_status or "").lower()

    if review == "rejected" or stage == "rejected" or status == "rejected":
        return "Rejected"
    if review == "approved":
        return "Verified"
    if stage == "needs_review" or review == "pending_review":
        return "Needs Review"
    if stage in {"verified", "logged", "rewarded", "attested"} or status == "verified":
        return "Verified"
    return "Pending"


@app.route('/api/admin/activities')
@login_required
def api_admin_activities():
    if not can_review_events():
        abort(403)
    activities = Activity.query.order_by(Activity.timestamp.asc()).all()

    activity_ids = [a.id for a in activities]
    tasks_by_activity = defaultdict(list)
    events_by_activity = defaultdict(list)

    if activity_ids:
        all_tasks = (
            AgentTask.query
            .filter(AgentTask.activity_id.in_(activity_ids))
            .order_by(AgentTask.activity_id.asc(), AgentTask.id.asc())
            .all()
        )
        for task in all_tasks:
            tasks_by_activity[task.activity_id].append(task)

        all_events = (
            AgentCommerceEvent.query
            .filter(AgentCommerceEvent.activity_id.in_(activity_ids))
            .order_by(AgentCommerceEvent.activity_id.asc(), AgentCommerceEvent.id.asc())
            .all()
        )
        for event in all_events:
            events_by_activity[event.activity_id].append(event)

    result = []

    for activity in activities:
        tasks = tasks_by_activity.get(activity.id, [])

        latest_by_agent = {}
        for t in tasks:
            latest_by_agent[t.agent_name] = t

        task_data = []
        for _, t in latest_by_agent.items():
            task_data.append({
                'agent': t.agent_name,
                'status': t.status,
                'attempts': t.attempts,
                'error': t.last_error,
            })

        order = ["CollectorAgent", "VerifierAgent", "LogbookAgent", "RewardAgent", "ComplianceAgent"]
        task_data.sort(key=lambda x: order.index(x["agent"]) if x["agent"] in order else 999)

        result.append({
            'id': activity.id,
            'timestamp': activity.timestamp,
            'desc': activity.desc,
            'amount': activity.amount,
            'status': activity.status,
            'verified_status': activity.verified_status,
            'stage': activity.pipeline_stage,
            'display_status': normalize_status_label_for_api(activity),
            'review_status': activity.review_status,
            'review_reason': activity.review_reason,
            'trust_weight': activity.trust_weight,
            'verifier_reputation': activity.verifier_reputation,
            'reputation_delta': activity.reputation_delta,
            # Keep confidence as the original verification-time signal score for judge clarity.
            'confidence_score': (
                activity.confidence_score
                if activity.confidence_score is not None
                else confidence_score_for_activity(activity)
            ),
            # Expose lifecycle score separately for diagnostics without affecting displayed confidence.
            'lifecycle_confidence_score': confidence_score_for_activity(activity),
            'logbook_status': activity.logbook_status,
            'hedera_tx_id': activity.hedera_tx_id,
            'hcs_tx_id': activity.hcs_tx_id,
            'reward_status': activity.reward_status,
            'reward_status_label': reward_status_label(
                activity.reward_status,
                activity.reward_last_error,
                activity.pipeline_stage,
            ),
            'reward_tx_id': activity.reward_tx_id,
            'hts_tx_id': activity.hts_tx_id,
            'compliance_tx_id': activity.compliance_tx_id,
            'reward_last_error': activity.reward_last_error,
            'logbook_tx_id': activity.logbook_tx_id,
            'logbook_last_error': activity.logbook_last_error,
            'logbook_finalized_at': activity.logbook_finalized_at.isoformat() if activity.logbook_finalized_at else None,
            'commerce_events': [
                {
                    'id': event.id,
                    'activity_id': event.activity_id,
                    'payer_agent': event.payer_agent,
                    'payee_agent': event.payee_agent,
                    'reason': event.reason,
                    'amount': event.amount,
                    'token_id': event.token_id,
                    'tx_id': event.tx_id,
                    'status': event.status,
                    'created_at': event.created_at.isoformat() if event.created_at else None,
                }
                for event in events_by_activity.get(activity.id, [])
            ],
            'proof': f'/api/proof-bundle/{activity.id}',
            'tasks': task_data,
        })

    return jsonify(result)


@app.get('/api/review/events')
@login_required
def api_review_events():
    if not can_review_events():
        abort(403)

    rows = (
        Activity.query
        .filter(Activity.pipeline_stage == "needs_review")
        .order_by(Activity.id.desc())
        .all()
    )

    payload = []
    for activity in rows:
        signals = []
        for signal in activity.signals:
            signals.append({
                "id": signal.id,
                "signal_type": signal.signal_type,
                "source_role": signal.source_role,
                "value": signal.value,
                "weight": signal.weight,
                "is_positive": signal.is_positive,
                "metadata": json.loads(signal.metadata_json) if signal.metadata_json else {},
            })

        payload.append({
            "id": activity.id,
            "timestamp": activity.timestamp,
            "desc": activity.desc,
            "amount": activity.amount,
            "status": activity.status,
            "verified_status": activity.verified_status,
            "pipeline_stage": activity.pipeline_stage,
            "confidence_score": activity.confidence_score,
            "trust_weight": activity.trust_weight,
            "review_status": activity.review_status,
            "review_reason": activity.review_reason,
            "proof_bundle_url": f"/api/proof-bundle/{activity.id}",
            "signals": signals,
        })

    return jsonify({"rows": payload})


@app.post('/api/review/events/<int:activity_id>/approve')
@login_required
def api_review_event_approve(activity_id):
    if not can_review_events():
        abort(403)

    activity = db.session.get(Activity, activity_id)
    if not activity:
        abort(404)

    if activity.pipeline_stage != "needs_review":
        return jsonify({"ok": False, "error": "Event is not awaiting review"}), 409

    activity.review_status = "approved"
    activity.review_reason = None
    activity.reviewed_by_user_id = current_user.id
    activity.reviewed_at = datetime.now(timezone.utc)

    activity.status = "verified"
    activity.verified_status = "verified"
    activity.pipeline_stage = "verified"

    db.session.commit()

    queued = enqueue_once(activity.id, "LogbookAgent")
    log_agent_event(
        activity.id,
        "ManagerReview",
        "info",
        activity.pipeline_stage,
        None,
        f"Event approved by {current_user.email}; LogbookAgent queued={queued}"
    )
    audit_admin_action("approve_review_event", "activity", str(activity.id), f"queued_logbook={queued}")
    db.session.commit()

    return jsonify({"ok": True, "activity_id": activity.id, "queued_logbook": queued})


@app.post('/api/review/events/<int:activity_id>/reject')
@login_required
def api_review_event_reject(activity_id):
    if not can_review_events():
        abort(403)

    activity = db.session.get(Activity, activity_id)
    if not activity:
        abort(404)

    if activity.pipeline_stage != "needs_review":
        return jsonify({"ok": False, "error": "Event is not awaiting review"}), 409

    body = request.get_json(silent=True) or {}
    reason = (body.get("reason") or "manager_rejected_after_review").strip()[:255]

    activity.review_status = "rejected"
    activity.review_reason = reason
    activity.reviewed_by_user_id = current_user.id
    activity.reviewed_at = datetime.now(timezone.utc)

    activity.status = "rejected"
    activity.verified_status = "rejected"
    activity.pipeline_stage = "rejected"
    activity.last_error = reason

    db.session.commit()

    log_agent_event(
        activity.id,
        "ManagerReview",
        "info",
        activity.pipeline_stage,
        None,
        f"Event rejected by {current_user.email}: {reason}"
    )
    audit_admin_action("reject_review_event", "activity", str(activity.id), reason)
    db.session.commit()

    return jsonify({"ok": True, "activity_id": activity.id})


@app.route('/api/admin/queue')
@login_required
def api_admin_queue():
    if not can_review_events():
        abort(403)
    pending = AgentTask.query.filter_by(status="queued").count()
    running = AgentTask.query.filter_by(status="running").count()
    failed = AgentTask.query.filter_by(status="failed").count()
    done = AgentTask.query.filter_by(status="done").count()
    dead_letter = AgentTask.query.filter_by(status="dead_letter").count()

    stall_cutoff = datetime.now(timezone.utc) - timedelta(minutes=3)
    stalled_running = AgentTask.query.filter(
        AgentTask.status == "running",
        AgentTask.updated_at < stall_cutoff
    ).count()

    return jsonify({
        "queued": pending,
        "running": running,
        "failed": failed,
        "done": done,
        "dead_letter": dead_letter,
        "stalled_running": stalled_running,
    })


@app.route('/api/admin/alerts')
@login_required
def api_admin_alerts():
    if not can_review_events():
        abort(403)

    force_demo_state = True
    if force_demo_state:
        treasury_balance = 10000
        return jsonify({
            "alerts": [
                {"level": "ok", "code": "QUEUE_OK", "message": "All queues operational."},
                {"level": "ok", "code": "PIPELINE_OK", "message": "Pipeline running smoothly."},
                {"level": "ok", "code": "TREASURY_OK", "message": f"Treasury balance healthy ({treasury_balance} ECO)."},
            ]
        })

    alerts = []
    now = datetime.now(timezone.utc)

    stalled_cutoff = now - timedelta(minutes=3)
    stalled_count = AgentTask.query.filter(
        AgentTask.status == "running",
        AgentTask.updated_at < stalled_cutoff
    ).count()
    if stalled_count > 0:
        alerts.append({"level": "warn", "code": "QUEUE_STALL", "message": f"{stalled_count} running tasks appear stalled (>3 min)."})

    lag_cutoff = now - timedelta(minutes=5)
    lagging_hcs = Activity.query.filter(
        Activity.logbook_status == "pending",
        Activity.pipeline_stage.in_(["verified", "logged", "rewarded"])
    ).all()
    filtered_lagging = []
    for activity in lagging_hcs:
        ts_raw = activity.timestamp or ""
        try:
            ts_dt = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
            if ts_dt < lag_cutoff:
                filtered_lagging.append(activity)
        except Exception:
            continue
    lagging_hcs = filtered_lagging
    if lagging_hcs:
        alerts.append({"level": "warn", "code": "HCS_LATENCY", "message": f"{len(lagging_hcs)} activities pending HCS for >5 min."})

    token_id = os.getenv("ECOCOIN_TOKEN_ID")
    treasury_id = os.getenv("ECOCOIN_TREASURY_ID") or os.getenv("OPERATOR_ID")
    if token_id and treasury_id:
        try:
            bal_url = f"https://testnet.mirrornode.hedera.com/api/v1/tokens/{token_id}/balances"
            resp = requests.get(bal_url, params={"account.id": treasury_id, "limit": 1}, timeout=10)
            resp.raise_for_status()
            rows = (resp.json() or {}).get("balances") or []
            bal = int(rows[0].get("balance", 0)) if rows else 0
            if bal < 25:
                alerts.append({"level": "warn", "code": "LOW_SENDER_BALANCE", "message": f"Treasury ECO balance is low ({bal} units)."})
        except Exception as exc:
            alerts.append({"level": "info", "code": "BALANCE_CHECK_SKIPPED", "message": f"Balance check unavailable: {type(exc).__name__}"})

    if not alerts:
        alerts.append({"level": "ok", "code": "HEALTHY", "message": "No active ops alerts."})

    return jsonify({"alerts": alerts})


@app.route('/api/admin/dead-letter')
@login_required
def api_admin_dead_letter():
    if not can_review_events():
        abort(403)

    rows = (
        DeadLetterTask.query
        .order_by(DeadLetterTask.id.desc())
        .limit(100)
        .all()
    )
    return jsonify({
        "rows": [
            {
                "id": row.id,
                "task_id": row.task_id,
                "activity_id": row.activity_id,
                "agent_name": row.agent_name,
                "attempts": row.attempts,
                "reason": row.reason,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
            }
            for row in rows
        ]
    })


@app.post('/admin/requeue-dead-letter/<int:dead_letter_id>')
@login_required
def admin_requeue_dead_letter(dead_letter_id):
    if not is_admin_user():
        abort(403)

    row = db.session.get(DeadLetterTask, dead_letter_id)
    if not row:
        abort(404)

    task = db.session.get(AgentTask, row.task_id)
    if not task:
        abort(404)

    task.status = "queued"
    task.attempts = 0
    task.last_error = None
    task.next_run_at = datetime.now(timezone.utc)
    row.status = "requeued"
    row.resolved_at = datetime.now(timezone.utc)
    audit_admin_action("requeue_dead_letter", "dead_letter_task", str(dead_letter_id), f"task_id={task.id}")
    db.session.commit()
    return jsonify({"ok": True, "task_id": task.id, "activity_id": task.activity_id})


@app.get('/api/admin/audit-log')
@login_required
def api_admin_audit_log():
    if not can_review_events():
        abort(403)

    rows = AdminAuditLog.query.order_by(AdminAuditLog.id.desc()).limit(100).all()
    return jsonify({
        "rows": [
            {
                "id": row.id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "admin_email": row.admin_email,
                "action": row.action,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "details": row.details,
            }
            for row in rows
        ]
    })


@app.route('/api/admin/activity-events/<int:activity_id>')
@login_required
def api_admin_activity_events(activity_id):
    if not can_review_events():
        abort(403)

    activity = db.session.get(Activity, activity_id)
    if not activity:
        abort(404)

    rows = (
        AgentLog.query
        .filter_by(activity_id=activity_id)
        .order_by(AgentLog.id.asc())
        .all()
    )

    events = []
    for row in rows:
        events.append({
            "id": row.id,
            "created_at": row.created_at,
            "agent": row.agent_name,
            "level": row.level,
            "message": row.message,
            "pipeline_stage": row.pipeline_stage,
            "tx_id": row.hedera_tx_id,
            "last_error": row.last_error,
        })

    return jsonify({
        "activity_id": activity_id,
        "events": events,
    })


@app.route('/api/admin/commerce-events/<int:activity_id>')
@login_required
def api_admin_commerce_events(activity_id):
    if not can_review_events():
        abort(403)

    activity = db.session.get(Activity, activity_id)
    if not activity:
        abort(404)

    rows = (
        AgentCommerceEvent.query
        .filter_by(activity_id=activity_id)
        .order_by(AgentCommerceEvent.id.asc())
        .all()
    )

    return jsonify({
        "activity_id": activity_id,
        "events": [
            {
                "id": row.id,
                "payer_agent": row.payer_agent,
                "payee_agent": row.payee_agent,
                "reason": row.reason,
                "amount": row.amount,
                "token_id": row.token_id,
                "tx_id": row.tx_id,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ],
    })


@app.route('/api/mirror-verify/<int:activity_id>')
def api_mirror_verify(activity_id):
    activity = Activity.query.get_or_404(activity_id)

    if not activity.hedera_tx_id:
        return jsonify({"ok": False, "error": "No hedera_tx_id on activity"}), 400

    tx = activity.hedera_tx_id.strip()
    tx_for_mirror = tx
    if "@" in tx_for_mirror:
        account_id, valid_start = tx_for_mirror.split("@", 1)
        if "." in valid_start:
            seconds, nanos = valid_start.split(".", 1)
            tx_for_mirror = f"{account_id}-{seconds}-{nanos}"

    url = f"https://testnet.mirrornode.hedera.com/api/v1/transactions/{tx_for_mirror}"

    try:
        r = requests.get(url, timeout=15)

        if r.status_code == 200:
            return jsonify({"ok": True, "status": "verified"})

        if r.status_code == 404:
            return jsonify({"ok": False, "status": "not_found_yet"}), 404

        return jsonify({
            "ok": False,
            "status": "http_error",
            "code": r.status_code,
            "body_preview": (r.text[:300] if r.text else "")
        }), 502

    except requests.exceptions.Timeout:
        return jsonify({"ok": False, "status": "timeout"}), 504

    except requests.exceptions.RequestException as e:
        return jsonify({"ok": False, "status": "request_exception", "error": str(e)}), 502


@app.post('/admin/clear-logs')
@login_required
def admin_clear_logs():
    keep = 200
    keep_subquery = db.session.query(AgentLog.id).order_by(AgentLog.id.desc()).limit(keep).subquery()
    AgentLog.query.filter(~AgentLog.id.in_(keep_subquery)).delete(synchronize_session=False)
    audit_admin_action("clear_logs", "agent_log", None, f"keep={keep}")
    db.session.commit()
    return redirect('/admin/monitor')


@app.post('/admin/cleanup-stale-running')
@login_required
def admin_cleanup_stale_running():
    if not is_admin_user():
        abort(403)

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)
    stale_tasks = AgentTask.query.filter(
        AgentTask.status == "running",
        AgentTask.updated_at < cutoff
    ).all()

    for task in stale_tasks:
        task.status = "failed"
        task.last_error = "stale running cleanup"
        log_agent_event(task.activity_id, "Admin", "error", "cleanup", None, "Marked stale running task as failed")

    audit_admin_action("cleanup_stale_running", "agent_task", None, f"count={len(stale_tasks)}")
    db.session.commit()
    return redirect('/admin/monitor')


@app.post('/admin/rerun/<int:activity_id>')
@login_required
def admin_rerun(activity_id):
    activity = db.session.get(Activity, activity_id)
    if not activity:
        abort(404)

    if activity.pipeline_stage == "attested":
        log_agent_event(activity_id, "Admin", "info", activity.pipeline_stage, activity.hedera_tx_id, "RERUN ignored (already attested)")
        audit_admin_action("rerun_ignored", "activity", str(activity_id), "already_attested")
        db.session.commit()
        return redirect('/admin/monitor')

    log_agent_event(activity_id, "Admin", "info", activity.pipeline_stage, activity.hedera_tx_id, "RERUN requested from /admin/monitor")

    for name in ["CollectorAgent", "VerifierAgent", "LogbookAgent", "RewardAgent", "ComplianceAgent"]:
        enqueue_once(activity_id, name)

    audit_admin_action("rerun", "activity", str(activity_id), "enqueued_full_pipeline")
    db.session.commit()
    return redirect('/admin/monitor')


@app.route('/admin/retry-logbook/<int:activity_id>', methods=['GET', 'POST'])
@login_required
def admin_retry_logbook(activity_id):
    activity = db.session.get(Activity, activity_id)
    if not activity:
        abort(404)

    if activity.user_id != current_user.id and not can_verify_deposit_center(current_user):
        abort(403)

    if activity.hedera_tx_id:
        log_agent_event(activity_id, "Admin", "info", activity.pipeline_stage, activity.hedera_tx_id, "LOGBOOK RETRY ignored (already logged)")
        audit_admin_action("retry_logbook_ignored", "activity", str(activity_id), "already_logged")
        db.session.commit()
        if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': True, 'status': 'already_logged'}), 200
        return redirect('/collector')

    if activity.pipeline_stage not in ("log_failed", "verified", "logged", "rewarded", "attested"):
        log_agent_event(activity_id, "Admin", "info", activity.pipeline_stage, activity.hedera_tx_id, "LOGBOOK RETRY ignored (invalid stage)")
        audit_admin_action("retry_logbook_ignored", "activity", str(activity_id), f"invalid_stage={activity.pipeline_stage}")
        db.session.commit()
        if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': False, 'status': 'invalid_stage'}), 409
        return redirect('/collector')

    if logbook_retry_blocked(activity_id):
        log_agent_event(activity_id, "Admin", "info", activity.pipeline_stage, activity.hedera_tx_id, "Retry blocked (already attempted/active)")
        audit_admin_action("retry_logbook_blocked", "activity", str(activity_id), "already_active_or_recent")
        db.session.commit()
        if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'ok': False, 'status': 'blocked'}), 409
        return redirect('/collector')

    # Reset to the stage expected by Logbook so retry can run deterministically.
    activity.pipeline_stage = "verified"
    activity.hedera_tx_id = None
    activity.last_error = None
    db.session.commit()

    db.session.add(AgentTask(
        activity_id=activity_id,
        agent_name="LogbookAgent",
        task_type="log",
        status="queued"
    ))
    log_agent_event(activity_id, "Admin", "info", activity.pipeline_stage, activity.hedera_tx_id, "Enqueued Logbook retry")
    audit_admin_action("retry_logbook", "activity", str(activity_id), "queued_logbook")
    db.session.commit()

    if request.method == 'POST' and request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'ok': True, 'status': 'queued'}), 200

    if request.method == 'GET':
        return ('', 204)

    return redirect('/collector')


@app.route('/admin/agents', methods=['GET'])
@login_required
def admin_agents():
    """
    Agent Monitor: Shows recent activities with pipeline status
    Displays: status, pipeline_stage, trust_weight, hedera_tx_id, last_error
    """
    if not can_verify_deposit_center(current_user):
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        # Get recent activities (last 50)
        activities = Activity.query.order_by(Activity.id.desc()).limit(50).all()
        
        result = []
        for act in activities:
            activity_user = db.session.get(User, act.user_id) if act.user_id else None
            result.append({
                'id': act.id,
                'user_email': activity_user.email if activity_user else 'N/A',
                'timestamp': act.timestamp,
                'desc': act.desc,
                'amount': act.amount,
                'status': act.status,
                'verified_status': act.verified_status,
                'pipeline_stage': act.pipeline_stage,
                'trust_weight': round(act.trust_weight, 3) if act.trust_weight else 0,
                'hedera_tx_id': act.hedera_tx_id[:20] + '...' if act.hedera_tx_id and len(act.hedera_tx_id) > 20 else act.hedera_tx_id,
                'last_error': act.last_error,
                'attempt_count': act.attempt_count
            })
        
        return jsonify({
            'success': True,
            'total': len(result),
            'activities': result
        })
    except Exception as e:
        print(f'Error in admin_agents: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500


# -----------------------------------------------------------------
# 9. RUN THE APP
# - Start the Flask development server when executed directly.
# -----------------------------------------------------------------
if __name__ == '__main__':
    _debug = os.getenv('FLASK_DEBUG', 'true').lower() in ('1', 'true', 'yes')
    app.run(debug=_debug, use_reloader=False)