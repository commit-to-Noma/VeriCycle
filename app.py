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
# 1. APP CONFIGURATION (THE SETUP)
# -----------------------------------------------------------------
basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)
app.config['SECRET_KEY'] = 'a-really-secret-key-that-you-should-change'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'vericycle.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# -----------------------------------------------------------------
# 2. INITIALIZE OUR NEW TOOLS
# -----------------------------------------------------------------
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)

# --- LOGIN BEHAVIOR: redirect to homepage but DO NOT auto-flash a message ---
# We intentionally do NOT set login_manager.login_message so Flask-Login
# won't flash a message on redirect. That prevents the homepage from
# auto-opening the auth modal when a user directly loads '/'.
login_manager.login_view = 'home'
login_manager.login_message = None
login_manager.login_message_category = None
# --- END LOGIN BEHAVIOR ---

# -----------------------------------------------------------------
# 3. THE USER DATABASE "BLUEPRINT" (THE MODEL)
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
    
    # --- THIS IS THE NEW LINE ---
    role = db.Column(db.String(20), nullable=False, default='collector')

# -----------------------------------------------------------------
# 4. A REQUIRED "HELPER" FUNCTION FOR FLASK-LOGIN
# -----------------------------------------------------------------
@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

# -----------------------------------------------------------------
# 5. NEW LOGIN & SIGNUP ROUTES
# -----------------------------------------------------------------

@app.route("/signup", methods=['POST'])
def signup():
    # This route only handles the POST data from the modal form
    email = request.form.get('email')
    password = request.form.get('password')
    role = request.form.get('role')  # <-- ADD THIS per spec
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        flash('That email is already taken. Please log in.', 'error')
        # Send them back to the homepage (do not open the auth modal)
        return redirect(url_for('home'))

    print("--- CALLING HEDERA ENGINE: Creating new collector account... ---")
    try:
        operator_id = os.getenv("OPERATOR_ID")
        operator_key = os.getenv("OPERATOR_KEY")
        if not operator_id or not operator_key:
            raise Exception("Missing environment variables")

        # This is your fixed subprocess call
        # Ensure the Node process receives the operator env vars (so the JS script can read them)
        child_env = os.environ.copy()
        child_env.update({
            "OPERATOR_ID": operator_id,
            "OPERATOR_KEY": operator_key,
        })

        result = subprocess.run(
            ["node", "collector-account.js", operator_id, operator_key],
            check=True, capture_output=True, text=True, env=child_env
        )
        # Print full stdout/stderr for troubleshooting the JS script output
        print("--- collector-account.js stdout ---")
        print(result.stdout)
        print("--- collector-account.js stderr ---")
        print(result.stderr)

        # Be permissive when parsing the script output: capture any non-space value after the labels
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        new_id_match = re.search(r"New Account ID:\s*(\S+)", output)
        new_key_match = re.search(r"New Account Private Key \(DER\):\s*(\S+)", output)

        if not new_id_match or not new_key_match:
            raise Exception("Script output was invalid.")

        new_id = new_id_match.group(1)
        new_key = new_key_match.group(1)
        print(f"--- SUCCESS: Created Hedera Account {new_id} ---")

        # Ensure role has a default if missing
        role = role or 'collector'

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(
            email=email,
            password_hash=hashed_password,
            hedera_account_id=new_id,
            hedera_private_key=new_key,
            role=role
        )
        db.session.add(new_user)
        db.session.commit()
        # After successful signup, send user to the homepage without opening the auth modal
        return redirect(url_for('home')) # Redirect back to homepage

    except Exception as e:
        print(f"--- HEDERA/PYTHON SIGNUP FAILED ---")
        print(e)
        flash('A problem occurred while creating your account. Please try again.', 'error')
        return redirect(url_for('home'))
            

@app.route("/login", methods=['POST'])
def login():
    # This route only handles the POST data from the modal form
    email = request.form.get('email')
    password = request.form.get('password')
    user = User.query.filter_by(email=email).first()
    
    if user and bcrypt.check_password_hash(user.password_hash, password):
        login_user(user, remember=True)

        next_page = request.args.get('next')

        # --- PROFILE CHECK (MANDATORY) ---
        if not current_user.full_name or not current_user.phone_number or not current_user.id_number:
            flash('Please complete your profile to continue.', 'error')
            return redirect(url_for('profile'))

        # --- NEW "SMART" ROLE-BASED REDIRECT ---

        # If they were trying to go to a specific page, send them there
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
# 6. ALL YOUR OTHER ROUTES (These are perfect)
# -----------------------------------------------------------------

@app.route('/')
def splash():
    return render_template('splash.html')


@app.route('/home')
def home():
    return render_template('home.html', active_page='home')

@app.route('/collector')
@login_required 
def collector_dashboard():
    # Ensure profile is complete before allowing access to the collector dashboard
    if not current_user.full_name or not current_user.phone_number or not current_user.id_number:
        flash('Please complete your profile before accessing the collector dashboard.', 'error')
        return redirect(url_for('profile'))

    return render_template('collector.html', active_page='dashboard')

@app.route('/center')
@login_required 
def center_dashboard():
    return render_template('center.html', active_page='dashboard')

@app.route('/network')
@login_required 
def network():
    return render_template('network.html', active_page='network')


@app.route('/rewards')
@login_required 
def rewards():
    return render_template('rewards.html', active_page='rewards')

@app.route('/generate-qr')
@login_required 
def generate_qr():
    # Require profile completion (full name, phone and ID) before allowing QR generation
    if not current_user.full_name or not current_user.phone_number or not current_user.id_number:
        flash('Please complete your profile before generating your QR code.', 'error')
        return redirect(url_for('profile'))

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
    collector_id = request.form['collector_id']
    weight_kg = float(request.form['weight'])
    reward_amount = "250" 
    print("--- CONFIRMATION RECEIVED! ---")
    try:
        subprocess.run(
            ["node", "transfer-reward.js", collector_id, reward_amount],
            check=True, 
            capture_output=True,
            text=True
        )
        print("--- HEDERA ENGINE CALL SUCCESSFUL! ---")
    except subprocess.CalledProcessError as e:
        print("--- !!! HEDERA ENGINE FAILED !!! ---")
        print(e.stderr) 
    return redirect(url_for('center_dashboard'))

# -----------------------------------------------------------------
# 6. (NEW) API FOR OUR "WOW" DASHBOARD
# -----------------------------------------------------------------
@app.route('/api/my-dashboard-data')
@login_required
def get_dashboard_data():
    # In the future, we will get this data from the database.
    # For now, we send "fake" data to build our "wow" features,
    # just like the GreenTrace winners did.
    data = {
        "total_kg": 21.5,
        "total_eco": 1850,
        "weekly_goal": 10,
        "current_kg": 5,
        "neighborhood_current_kg": 150,  # <-- NEW
        "neighborhood_goal_kg": 1000     # <-- NEW
        # "neighborhood_goal_percent" is no longer needed
    }
    return jsonify(data)

# -----------------------------------------------------------------
# 7. (NEW) PROFILE PAGE ROUTE
# -----------------------------------------------------------------
@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        # --- This is the POST (Save) logic ---
        current_user.full_name = request.form.get('full_name')
        current_user.phone_number = request.form.get('phone_number')
        current_user.address = request.form.get('address')
        current_user.id_number = request.form.get('id_number')
        
        db.session.commit()
        flash('Your profile has been updated successfully!', 'success')
    # After saving, send user to their collector dashboard
    return redirect(url_for('collector_dashboard'))

    # --- This is the GET (View) logic ---
    return render_template('profile.html', active_page='profile')

# 8. (NEW) SMART SEARCH PAGE ROUTE
# -----------------------------------------------------------------
@app.route('/search')
@login_required
def search():
    # In a real app, we'd do a database query.
    # For the MVP, we just show the page.
    return render_template('search.html', active_page='search')

# -----------------------------------------------------------------
# 7. RUN THE APP
# -----------------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)