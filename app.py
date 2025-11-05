from flask import Flask, render_template, request, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
import qrcode
import io
import subprocess
import os # We'll need this to find our database

# -----------------------------------------------------------------
# 1. APP CONFIGURATION (THE SETUP)
# -----------------------------------------------------------------

# Find the absolute path of the folder this file is in
basedir = os.path.abspath(os.path.dirname(__file__))

app = Flask(__name__)

# This is a secret key to keep your user sessions secure
app.config['SECRET_KEY'] = 'a-really-secret-key-that-you-should-change'

# This is where our new database will be saved.
# We are using SQLite, which is a simple file (vericycle.db)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'vericycle.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# -----------------------------------------------------------------
# 2. INITIALIZE OUR NEW TOOLS
# -----------------------------------------------------------------
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login' # If a user tries to see a locked page, send them to /login
login_manager.login_message_category = 'info' # (Optional, for styling)

# -----------------------------------------------------------------
# 3. THE USER DATABASE "BLUEPRINT" (THE MODEL)
# -----------------------------------------------------------------
# This UserMixin is a magic tool from flask-login
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(60), nullable=False)

    # VeriCycle-specific fields
    hedera_account_id = db.Column(db.String(100), nullable=True)
    hedera_private_key = db.Column(db.String(255), nullable=True) # Storing keys like this is okay for a hackathon MVP

    def __repr__(self):
        return f"User('{self.email}', '{self.hedera_account_id}')"

# -----------------------------------------------------------------
# 4. A REQUIRED "HELPER" FUNCTION FOR FLASK-LOGIN
# -----------------------------------------------------------------
@login_manager.user_loader
def load_user(user_id):
    # This tells flask-login how to find a specific user
    return db.session.get(User, int(user_id))

# -----------------------------------------------------------------
# 5. ALL YOUR OLD ROUTES (THEY STILL WORK!)
# -----------------------------------------------------------------

# This "route" tells the app what to do when someone visits the main landing page
@app.route('/')
def index():
    # This function finds and displays the index.html page
    return render_template('index.html')

# This route is for the collector's dashboard
@app.route('/collector')
@login_required # <-- NEW: This page is now locked!
def collector_dashboard():
    return render_template('collector.html')

# This route is for the center's dashboard
@app.route('/center')
@login_required # <-- NEW: This page is also locked!
def center_dashboard():
    return render_template('center.html')

@app.route('/hello')
def hello_world():
    return "Hello Noma! The server is loading my new file!"

@app.route('/generate-qr')
@login_required # <-- NEW: Only logged-in users can make a QR code
def generate_qr():
    # This is the data we will put in the QR code.
    # We now get it from the user who is *currently logged in*!
    collector_id = current_user.hedera_account_id

    # Generate the QR code in memory
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
    qr.add_data(collector_id)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img_io = io.BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    return send_file(img_io, mimetype='image/png')

@app.route('/confirm-dropoff', methods=['POST'])
@login_required # <-- NEW: Only logged-in centers can confirm
def confirm_dropoff():

    # 1. Read the data that came from the form
    collector_id = request.form['collector_id']
    weight_kg = float(request.form['weight'])

    # 2. Calculate the reward
    reward_amount = "250" # Send 2.50 ECO

    print("--- CONFIRMATION RECEIVED! ---")
    print(f"Collector ID: {collector_id}")
    print(f"Weight (kg): {weight_kg}")
    print(f"Calculated Reward: {reward_amount} units")

    # 3. THIS IS THE MAGIC!
    print("--- CALLING HEDERA ENGINE (JAVASCRIPT) ---")

    try:
        # Run the JavaScript file and pass in our variables
        subprocess.run(
            ["node", "4-transfer-reward.js", collector_id, reward_amount],
            check=True, 
            capture_output=True,
            text=True
        )
        print("--- HEDERA ENGINE CALL SUCCESSFUL! ---")

    except subprocess.CalledProcessError as e:
        print("--- !!! HEDERA ENGINE FAILED !!! ---")
        print(e.stderr) 

    # 4. Send the user back to the center's dashboard
    return redirect(url_for('center_dashboard'))

# -----------------------------------------------------------------
# 6. RUN THE APP
# -----------------------------------------------------------------
if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)