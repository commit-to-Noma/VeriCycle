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
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
import qrcode
import io
import subprocess
import os 
import re 

# -----------------------------------------------------------------
# 1. APP CONFIGURATION
# -----------------------------------------------------------------
basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a-really-secret-key-that-you-should-change'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'vericycle.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# -----------------------------------------------------------------
# 2. INITIALIZE TOOLS
# -----------------------------------------------------------------
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)

login_manager.login_view = 'home'
login_manager.login_message = None
login_manager.login_message_category = None

# -----------------------------------------------------------------
# 3. DATABASE MODEL
# -----------------------------------------------------------------
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

# -----------------------------------------------------------------
# 4. HELPER FUNCTION FOR FLASK-LOGIN
# -----------------------------------------------------------------
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# -----------------------------------------------------------------
# 5. AUTHENTICATION ROUTES (LOGIN, LOGOUT, SIGNUP)
# -----------------------------------------------------------------

@app.route("/signup", methods=['POST'])
def signup():
    email = request.form.get('email')
    password = request.form.get('password')
    role = request.form.get('role')
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        flash('That email is already taken. Please log in.', 'error')
        return redirect(url_for('home', _anchor='auth-modal'))

    try:
        new_id = None
        new_key = None
        
        # --- Logic for Collectors ---
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

        # --- Logic for Centers ---
        else: # role == 'center'
            print("--- SKIPPING HEDERA: Registering a verified Center account. ---")
            hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
            new_user = User(
                email=email, password_hash=hashed_password, role=role,
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
        
        # --- NEW PROFILE CHECK (for Collectors ONLY) ---
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
        
        # --- NEW: Smart redirect based on role ---
        if current_user.role == 'center':
            return redirect(url_for('center_dashboard'))
        else:
            return redirect(url_for('collector_dashboard'))

    # GET request
    return render_template('profile.html', active_page='profile')

@app.route('/collector')
@login_required 
def collector_dashboard():
    # --- NEW PROFILE GATE ---
    if not current_user.full_name or not current_user.phone_number or not current_user.id_number:
        flash('You must complete your profile before accessing the dashboard.', 'error')
        return redirect(url_for('profile'))
    
    return render_template('collector.html', active_page='dashboard')


@app.route('/request-pickup')
@login_required 
def request_pickup():
    # We pass the user's address to pre-fill the form
    return render_template('request_pickup.html', active_page='dashboard')

@app.route('/center')
@login_required 
def center_dashboard():
    return render_template('center.html', active_page='dashboard')

@app.route('/search')
@login_required
def search():
    return render_template('search.html', active_page='search')

@app.route('/network')
@login_required 
def network():
    return render_template('network.html', active_page='network')

@app.route('/rewards')
@login_required 
def rewards():
    return render_template('rewards.html', active_page='rewards')

# -----------------------------------------------------------------
# 7. APP "ENGINE" ROUTES (API & ACTIONS)
# -----------------------------------------------------------------

@app.route('/generate-qr')
@login_required 
def generate_qr():
    # --- NEW PROFILE GATE ---
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

@app.route('/confirm-dropoff', methods=['POST'])
@login_required 
def confirm_dropoff():
    # This route is only for Centers
    if current_user.role != 'center':
        return "Unauthorized", 403
        
    collector_id = request.form['collector_id']
    weight_kg = float(request.form['weight'])
    reward_amount = "750" # This should be calculated based on weight, but 750 is our demo

    print("--- CONFIRMATION RECEIVED! (demo mode - no token transfer) ---")
    # NOTE: Demo flow — we intentionally skip calling the Hedera transfer script
    # because many collectors in the demo environment may not have associated
    # the demo token. Sending would fail with TOKEN_NOT_ASSOCIATED_TO_ACCOUNT.
    # For a production flow, implement token association and return success
    # based on the subprocess result.
    return jsonify({"success": True, "message": "Transaction verified!"})

@app.route('/api/my-dashboard-data')
@login_required
def get_dashboard_data():
    # New users start at 0
    data = {
        "total_kg": 0.0,
        "total_eco": 0,
        "weekly_goal": 20,
        "current_kg": 0.0,
    "neighborhood_current_kg": 150.0,
        "neighborhood_goal_kg": 1000 
    }
    return jsonify(data)

# -----------------------------------------------------------------
# 8. RUN THE APP
# -----------------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)