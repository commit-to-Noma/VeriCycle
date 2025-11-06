from dotenv import load_dotenv
load_dotenv() 

from flask import Flask, render_template, request, redirect, url_for, send_file, flash
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
login_manager.login_view = 'index'
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
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        flash('That email is already taken. Please log in.', 'error')
        return redirect(url_for('index', _anchor='auth-modal')) # Redirect back to homepage

    print("--- CALLING HEDERA ENGINE: Creating new collector account... ---")
    try:
        operator_id = os.getenv("OPERATOR_ID")
        operator_key = os.getenv("OPERATOR_KEY")
        if not operator_id or not operator_key:
            raise Exception("Missing environment variables")

        # This is your fixed subprocess call
        result = subprocess.run(
            ["node", "collector-account.js", operator_id, operator_key],
            check=True, capture_output=True, text=True
        )
        
        output = result.stdout
        new_id_match = re.search(r"New Account ID: (0.0\.\d+)", output)
        new_key_match = re.search(r"New Account Private Key \(DER\): (302e\S+)", output)

        if not new_id_match or not new_key_match:
            raise Exception("Script output was invalid.")

        new_id = new_id_match.group(1)
        new_key = new_key_match.group(1)
        print(f"--- SUCCESS: Created Hedera Account {new_id} ---")

        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')
        new_user = User(
            email=email, 
            password_hash=hashed_password, 
            hedera_account_id=new_id, 
            hedera_private_key=new_key
        )
        db.session.add(new_user)
        db.session.commit()

        return redirect(url_for('index', _anchor='auth-modal')) # Redirect back to homepage

    except Exception as e:
        print(f"--- HEDERA/PYTHON SIGNUP FAILED ---")
        print(e)
        flash('A problem occurred while creating your account. Please try again.', 'error')
        return redirect(url_for('login'))
            

@app.route("/login", methods=['POST'])
def login():
    # This route only handles the POST data from the modal form
    email = request.form.get('email')
    password = request.form.get('password')
    user = User.query.filter_by(email=email).first()
    
    if user and bcrypt.check_password_hash(user.password_hash, password):
        login_user(user, remember=True)
        
        # --- THIS IS THE FIX FOR THE "WRONG REDIRECT" BUG (BUG 3) ---
        next_page = request.args.get('next')
        if next_page:
            # If they were trying to go to /collector, send them there!
            return redirect(next_page)
        else:
            # If they just logged in from the homepage, send them back to the homepage.
            return redirect(url_for('index'))
        # --- END OF THE FIX ---
            
    else:
        flash('Login Unsuccessful. Please check email and password.', 'error')
        return redirect(url_for('index'))

@app.route("/logout")
@login_required 
def logout():
    logout_user()
    return redirect(url_for('index'))

# -----------------------------------------------------------------
# 6. ALL YOUR OTHER ROUTES (These are perfect)
# -----------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/collector')
@login_required 
def collector_dashboard():
    return render_template('collector.html')

@app.route('/center')
@login_required 
def center_dashboard():
    return render_template('center.html')

@app.route('/generate-qr')
@login_required 
def generate_qr():
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
# 7. RUN THE APP
# -----------------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)