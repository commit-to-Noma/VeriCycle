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

from flask import Flask, render_template, request, redirect, url_for, send_file, flash, jsonify
from datetime import datetime
from flask_login import login_user, login_required, logout_user, current_user
import qrcode
import io
import subprocess
import os 
import re 
from agents.agent_coordinator import AgentCoordinator
import threading

# -----------------------------------------------------------------
# 1. APP CONFIGURATION
# - Sets up Flask configuration and database file path.
# -----------------------------------------------------------------
basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a-really-secret-key-that-you-should-change'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'vericycle.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# -----------------------------------------------------------------
# 2. INITIALIZE TOOLS
# - Initialize extensions: database, encryption and login manager.
# -----------------------------------------------------------------
from extensions import db, bcrypt, login_manager

# Initialize extensions with the app
db.init_app(app)
bcrypt.init_app(app)
login_manager.init_app(app)

# Ensure tables exist (creates Activity table for persistence)
with app.app_context():
    db.create_all()

login_manager.login_view = 'home'
login_manager.login_message = None
login_manager.login_message_category = None

# -----------------------------------------------------------------
# 3. DATABASE MODEL
# - Define `User` and `Activity` models used across routes.
# -----------------------------------------------------------------
from models import User, Activity

# -----------------------------------------------------------------
# 4. HELPER FUNCTION FOR FLASK-LOGIN
# - Provide the user loader required by Flask-Login.
# -----------------------------------------------------------------
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

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
            new_user = User(
                email=email, password_hash=hashed_password, 
                hedera_account_id=new_id, hedera_private_key=new_key, role=role
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
            new_user = User(
                email=email, password_hash=hashed_password, 
                hedera_account_id=new_id, hedera_private_key=new_key, role=role,
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
    # Expose the user's activities to the template so the UI can show agent status and Hedera TX
    activities = Activity.query.filter_by(user_id=current_user.id).all()
    return render_template('collector.html', activities=activities, active_page='dashboard')


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
            print(f"AgentCoordinator triggered for activity {act.id}")
            coord = AgentCoordinator()
            threading.Thread(target=lambda: coord.run_pipeline(act.id), daemon=True).start()
        except Exception as e:
            print('Failed to start AgentCoordinator thread:', e)
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
        coord = AgentCoordinator()
        result = coord.run_pipeline(activity_id)

        return jsonify({'success': result})
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
        
        # Create activity record
        from datetime import datetime
        activity = Activity(
            user_id=current_user.id,
            timestamp=datetime.utcnow().isoformat() + 'Z',
            desc=f"Verified Drop-off ({weight}kg of Cans)",
            amount=total_amount,
            status="pending",
            verified_status="pending"
        )
        
        db.session.add(activity)
        db.session.commit()
        
        activity_id = activity.id
        print(f"\n{'='*80}", flush=True)
        print(f"[BACKEND] POST /api/simulate-deposit called", flush=True)
        print(f"[BACKEND] New activity created: ID={activity_id}, user={current_user.email}, amount={total_amount}", flush=True)
        print(f"{'='*80}\n", flush=True)
        
        # Trigger agent in background thread
        def process_async():
            print(f"[BACKEND] Background thread started for activity {activity_id}", flush=True)
            try:
                coord = AgentCoordinator()
                result = coord.run_pipeline(activity_id)
                if result:
                    print(f"[BACKEND] ✅ Pipeline finished successfully", flush=True)
                else:
                    print(f"[BACKEND] ❌ Pipeline failed", flush=True)
            except Exception as e:
                print(f"[BACKEND] 💥 Background thread crashed: {e}", flush=True)
                import traceback
                traceback.print_exc()
        
        background_thread = threading.Thread(target=process_async, daemon=True)
        background_thread.start()
        print(f"[BACKEND] Background thread spawned (daemon=True)", flush=True)
        
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
    activities = []
    total_eco = 0
    total_kg = 0
    
    try:
        # Fetch all activities for this user (verified + pending)
        acts = Activity.query.filter_by(user_id=current_user.id).order_by(Activity.id.desc()).limit(200).all()
        
        for a in acts:
            activities.append({
                'timestamp': a.timestamp,
                'desc': a.desc,
                'amount': a.amount,
                'status': a.status,
                'hedera_tx_id': a.hedera_tx_id
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
        activities = []
        total_eco = 0
        total_kg = 0
    
    # Demo user gets seed data plus their activities
    if current_user.email.lower().strip() == 'test@gmail.com':
        demo_seed = [
            { "timestamp": "2025-11-12T10:00:00Z", "desc": "Verified Drop-off (8.5kg of Paper)", "amount": 425.00, "status": "verified", "hedera_tx_id": None },
            { "timestamp": "2025-11-08T14:30:00Z", "desc": "Verified Drop-off (15.0kg of Cans)", "amount": 750.00, "status": "verified", "hedera_tx_id": None }
        ]
        total_eco += 425.00 + 750.00  # Add seed data to balance
        total_kg += 8.5 + 15.0
        activities = demo_seed + activities  # Seed activities first, then user activities
    
    data = {
        "total_kg": round(total_kg, 1),
        "total_eco": round(total_eco, 2),
        "weekly_goal": 30,
        "current_kg": min(total_kg, 30),  # Personal weekly goal progress
        "neighborhood_current_kg": 165.0,  # Static for now
        "neighborhood_goal_kg": 1000,
        "profile_complete": "1" if current_user.full_name else "0",
        "activities": activities
    }

    return jsonify(data)


# -----------------------------------------------------------------
# 8. ADMIN AGENT MONITOR
# - View pipeline status and agent processing
# -----------------------------------------------------------------
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
    app.run(debug=True, use_reloader=False)