"""
================================================================================
VeriCycle - Main Flask Application (app.py)
================================================================================
This is the "brain" of the VeriCycle application. It handles:
- All server-side logic and routing.
- Database models (using Flask-SQLAlchemy).
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
- qrcode: To generate the collector's QR code.
================================================================================
"""

from dotenv import load_dotenv
load_dotenv() 

from flask import Flask, render_template, request, redirect, url_for, send_file, flash, jsonify, abort
from datetime import datetime, timezone, date, timedelta
from flask_login import login_user, login_required, logout_user, current_user
import qrcode
import io
import zipfile
import subprocess
import os 
import requests
import json
import hashlib
import re 
import threading
from collections import defaultdict
from sqlalchemy.exc import OperationalError
from sqlalchemy import text
from urllib.parse import urlencode

# -----------------------------------------------------------------
# 1. APP CONFIGURATION
# - Sets up Flask configuration and database file path.
# -----------------------------------------------------------------
basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a-really-secret-key-that-you-should-change'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'vericycle.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
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

# worker will be started when running the app directly (see bottom run block)

login_manager.login_view = 'home'
login_manager.login_message = None
login_manager.login_message_category = None

# -----------------------------------------------------------------
# 3. DATABASE MODEL
# - Define `User` and `Activity` models used across routes.
# -----------------------------------------------------------------
from models import User, Activity, Location, WasteSchedule, HouseholdProfile, PickupEvent, AgentLog, AgentTask, AgentCommerceEvent, DeadLetterTask, AdminAuditLog
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


def hashscan_link(tx_id: str | None) -> str | None:
    if not tx_id:
        return None
    return f"https://hashscan.io/testnet/transaction/{tx_id}"


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

@app.route("/signup", methods=['POST'])
def signup():
    email = request.form.get('email')
    password = request.form.get('password')
    role = request.form.get('role')
    
    # ===== CRITICAL: Check if email exists BEFORE expensive Hedera account creation =====
    # This prevents:
    # 1. Burning testnet funds on duplicate account attempts
    # 2. Race conditions where two requests try to create the same account
    # Must be checked BEFORE any subprocess calls to collector-account.js
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        print(f"[SIGNUP] Email {email} already exists, rejecting signup")
        flash('That email is already taken. Please log in.', 'error')
        return redirect(url_for('home', _anchor='auth-modal'))
    
    print(f"[SIGNUP] Email {email} is new. Proceeding with account creation for role={role}")

    try:
        new_id = None
        new_key = None
        
        # Handle collector signup and create a Hedera account
        if role == 'collector':
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
            return redirect(url_for('profile')) # COLLECTORS go to profile

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
        return redirect(url_for('home'))
    except Exception as e:
        print(f"--- HEDERA/PYTHON SIGNUP FAILED (General Exception) ---")
        print(e)
        flash('A problem occurred while creating your account. Please try again.','error')
        return redirect(url_for('home'))


@app.route("/login", methods=['POST'])
def login():
    email = request.form.get('email')
    password = request.form.get('password')
    user = User.query.filter_by(email=email).first()
    
    if user and bcrypt.check_password_hash(user.password_hash, password):
        login_user(user, remember=True)
        
        next_page = request.args.get('next')
        
        # Ensure collectors have completed their profile
        if current_user.role == 'collector':
            if not current_user.full_name or not current_user.phone_number or not current_user.id_number:
                flash('Please complete your profile to continue.', 'error')
                return redirect(url_for('profile'))
        
        # If profile is complete (or user is a Center), continue.
        if next_page:
            return redirect(next_page)
        
        # If they just logged in, send them to their correct dashboard
        if current_user.role == 'center':
            return redirect(url_for('center_dashboard'))
        else: # 'collector'
            return redirect(url_for('collector_dashboard'))
            
    else:
        flash('Login Unsuccessful. Please check email and password.', 'error')
        return redirect(url_for('home'))

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
    return render_template('home.html', active_page='home')


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
    return render_template('profile.html', active_page='profile')

@app.route('/collector')
@login_required 
def collector_dashboard():
    # Require profile completion for collectors
    if not current_user.full_name or not current_user.phone_number or not current_user.id_number:
        flash('You must complete your profile before accessing the dashboard.', 'error')
        return redirect(url_for('profile'))
    # Expose one newest-first activity list for the dashboard table.
    activities = (
        Activity.query
        .filter_by(user_id=current_user.id)
        .order_by(Activity.timestamp.desc())
        .all()
    )
    return render_template('collector.html', activities=activities, active_page='dashboard', demo_mode=DEMO_MODE)


@app.route('/request-pickup')
@login_required 
def request_pickup():
    # We pass the user's address to pre-fill the form
    return render_template('request_pickup.html', active_page='dashboard')

@app.route('/center')
@login_required 
def center_dashboard():
    # Allow only 'center' users to access center dashboard
    if current_user.role != 'center':
        flash('You do not have permission to access this page.', 'error')
        return redirect(url_for('collector_dashboard'))
    
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

    location = Location.query.get(profile.location_id)
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
# - API endpoints for activities, confirmations, QR generation and dashboard data.
# -----------------------------------------------------------------

@app.route('/generate-qr')
@login_required 
def generate_qr():
    # Require complete profile to generate QR
    if not current_user.full_name or not current_user.phone_number or not current_user.id_number:
        return "Profile incomplete", 403 
    
    collector_id = current_user.hedera_account_id
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
    qr.add_data(collector_id)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img_io = io.BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    return send_file(img_io, mimetype='image/png')


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
    if current_user.role != 'center':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

    try:
        collector_id = request.form.get('collector_id')
        weight = request.form.get('weight')

        if not collector_id or not weight:
            return jsonify({'success': False, 'error': 'Missing data'}), 400

        collector = User.query.filter_by(hedera_account_id=collector_id).first()
        if not collector:
            return jsonify({'success': False, 'error': 'Collector not found'}), 404

        activity = Activity(
            user_id=collector.id,
            timestamp=datetime.utcnow().isoformat(),
            desc=f"Pending Drop-off ({weight}kg)",
            amount=float(weight),
            verified_status="pending"
        )

        db.session.add(activity)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Drop-off recorded as pending verification.",
            "activity_id": activity.id
        })

    except Exception as e:
        print('Error in confirm_dropoff:', e)
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/run-collector-agent/<int:activity_id>', methods=['POST'])
@login_required
def run_collector_agent(activity_id):
    if current_user.role != 'center':
        return jsonify({'success': False, 'error': 'Unauthorized'}), 403

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
    timeline = []
    total_eco = 0
    total_kg = 0

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
                'reward_tx_id': a.reward_tx_id,
                'reward_last_error': a.reward_last_error,
                'trust_weight': a.trust_weight,
                'verifier_reputation': a.verifier_reputation,
                'reputation_delta': a.reputation_delta,
                'confidence_score': confidence_score_for_activity(a),
                'pipeline_stage': a.pipeline_stage,
                'last_error': a.last_error,
            })
            
            # Only count VERIFIED activities toward balance
            if a.verified_status == "verified" or a.status == "verified":
                total_eco += a.amount
                # Extract kg from description (e.g., "Verified Drop-off (10.0kg of Cans)")
                import re
                match = re.search(r'(\d+\.?\d*)\s*kg', a.desc)
                if match:
                    total_kg += float(match.group(1))
    except Exception as e:
        print('Error fetching activities:', e)
        timeline = []
        total_eco = 0
        total_kg = 0
    
    # Demo user gets seed data plus their activities
    if current_user.email.lower().strip() == 'test@gmail.com':
        seed1_ts = "2025-11-12T10:00:00Z"
        seed1_desc = "Verified Drop-off (8.5kg of Paper)"
        seed1_amount = 425.00
        seed2_ts = "2025-11-08T14:30:00Z"
        seed2_desc = "Verified Drop-off (15.0kg of Cans)"
        seed2_amount = 750.00

        seed1_hash = build_proof_hash(
            activity_id="demo-seed-1",
            user_email=current_user.email,
            amount=seed1_amount,
            description=seed1_desc,
            created_at=seed1_ts,
            verifier_trust_weight=0.85,
        )
        seed2_hash = build_proof_hash(
            activity_id="demo-seed-2",
            user_email=current_user.email,
            amount=seed2_amount,
            description=seed2_desc,
            created_at=seed2_ts,
            verifier_trust_weight=0.85,
        )

        demo_seed = [
            {
                "id": None,
                "timestamp": seed1_ts,
                "desc": seed1_desc,
                "amount": seed1_amount,
                "status": "verified",
                "hedera_tx_id": None,
                "proof_hash": seed1_hash,
                "proof_bundle_url": _generated_proof_url("demo-seed-1", seed1_ts, seed1_desc, seed1_amount, 0.85, current_user.email),
                "logbook_status": "pending",
                "pipeline_stage": "attested",
                "last_error": None
            },
            {
                "id": None,
                "timestamp": seed2_ts,
                "desc": seed2_desc,
                "amount": seed2_amount,
                "status": "verified",
                "hedera_tx_id": None,
                "proof_hash": seed2_hash,
                "proof_bundle_url": _generated_proof_url("demo-seed-2", seed2_ts, seed2_desc, seed2_amount, 0.85, current_user.email),
                "logbook_status": "pending",
                "pipeline_stage": "attested",
                "last_error": None
            }
        ]
        total_eco += 425.00 + 750.00  # Add seed data to balance
        total_kg += 8.5 + 15.0
        timeline = demo_seed + timeline  # Seed activities first, then user activities
    
    data = {
        "total_kg": round(total_kg, 1),
        "total_eco": round(total_eco, 2),
        "weekly_goal": 30,
        "current_kg": min(total_kg, 30),  # Personal weekly goal progress
        "neighborhood_current_kg": 165.0,  # Static for now
        "neighborhood_goal_kg": 1000,
        "profile_complete": "1" if current_user.full_name else "0",
        "timeline": timeline,
        "activities": timeline
    }

    return jsonify(data)


@app.get('/api/proof-bundle/<int:activity_id>')
@login_required
def download_proof_bundle(activity_id):
    activity = db.session.get(Activity, activity_id)
    if not activity:
        abort(404)
    if (activity.user_id != current_user.id) and (not is_admin_user()):
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
    }
    return payload_data


def _compute_proof_sha256(payload_data: dict):
    stable = stable_proof_input(payload_data)
    return compute_proof_sha256(stable)


def is_admin_user():
    try:
        return current_user.is_authenticated and getattr(current_user, "role", None) == "admin"
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
    if (activity.user_id != current_user.id) and (not is_admin_user()):
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
@login_required
def admin_monitor():
    if not is_admin_user():
        abort(403)
    return render_template('admin_monitor.html')


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
    if not is_admin_user():
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

    collector = User.query.filter_by(email="test@gmail.com").first()
    if not collector:
        return jsonify({"ok": False, "error": "test@gmail.com not found"}), 400

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


@app.route('/api/admin/activities')
@login_required
def api_admin_activities():
    if not is_admin_user():
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
            'stage': activity.pipeline_stage,
            'trust_weight': activity.trust_weight,
            'verifier_reputation': activity.verifier_reputation,
            'reputation_delta': activity.reputation_delta,
            'confidence_score': confidence_score_for_activity(activity),
            'logbook_status': activity.logbook_status,
            'hedera_tx_id': activity.hedera_tx_id,
            'hcs_tx_id': activity.hcs_tx_id,
            'reward_status': activity.reward_status,
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


@app.route('/api/admin/queue')
@login_required
def api_admin_queue():
    if not is_admin_user():
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
    if not is_admin_user():
        abort(403)

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
    if not is_admin_user():
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
    if not is_admin_user():
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
    if not is_admin_user():
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
    if not is_admin_user():
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

    if activity.user_id != current_user.id and current_user.role not in ('admin', 'center'):
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
    if current_user.role not in ('admin', 'center'):
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        # Get recent activities (last 50)
        activities = Activity.query.order_by(Activity.id.desc()).limit(50).all()
        
        result = []
        for act in activities:
            result.append({
                'id': act.id,
                'user_email': User.query.get(act.user_id).email if act.user_id else 'N/A',
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
    # Start background worker only when running the app directly
    start_worker_background()
    app.run(debug=True, use_reloader=False)