# --- We add 'subprocess' to let Python run terminal commands ---
from flask import Flask, render_template, request, redirect, url_for, send_file
import qrcode
import io
import subprocess # <-- ADD THIS IMPORT

app = Flask(__name__)

# --- (Your other routes are all the same) ---
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/collector')
def collector_dashboard():
    return render_template('collector.html')

@app.route('/center')
def center_dashboard():
    return render_template('center.html')

@app.route('/hello')
def hello_world():
    return "Hello Noma! The server is loading my new file!"

@app.route('/generate-qr')
def generate_qr():
    collector_id = "0.0.7191569" # Your test collector ID
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
    qr.add_data(collector_id)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    img_io = io.BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    return send_file(img_io, mimetype='image/png')

# --------------------------------------------------
# --- THIS IS THE UPGRADED "MAGIC" FUNCTION ---
# --------------------------------------------------
@app.route('/confirm-dropoff', methods=['POST'])
def confirm_dropoff():
    
    # 1. Read the data that came from the form
    collector_id = request.form['collector_id']
    # We convert the weight (text) into a floating-point number
    weight_kg = float(request.form['weight'])
    
    # 2. Calculate the reward
    # Let's say 1 kg = 50 EcoCoins (50.00)
    # Since our token has 2 decimals, we must use integers.
    # 1.5 kg * 50 = 75. But we must multiply by 100 for the decimals.
    # 1.5 * 50 * 100 = 7500.
    # Let's keep it simple for now: 1kg = 5000 (which is 50.00 ECO)
    # We'll calculate a simple 250 ECO reward for this test.
    
    # --- SIMPLE REWARD FOR THE TEST ---
    reward_amount = "250" # Send 2.50 ECO
    
    print("--- CONFIRMATION RECEIVED! ---")
    print(f"Collector ID: {collector_id}")
    print(f"Weight (kg): {weight_kg}")
    print(f"Calculated Reward: {reward_amount} units")
    
    # 3. THIS IS THE MAGIC!
    # We are telling Python to run a command in the terminal:
    # "node 4-transfer-reward.js [collector_id] [reward_amount]"
    print("--- CALLING HEDERA ENGINE (JAVASCRIPT) ---")
    
    try:
        # Run the JavaScript file and pass in our variables
        subprocess.run(
            ["node", "transfer-reward.js", collector_id, reward_amount],
            check=True, # This makes it stop if the script fails
            capture_output=True, # This hides the JS output from our main console
            text=True
        )
        print("--- HEDERA ENGINE CALL SUCCESSFUL! ---")
    
    except subprocess.CalledProcessError as e:
        print("--- !!! HEDERA ENGINE FAILED !!! ---")
        print(e.stderr) # Print the error from the JavaScript file
    
    # 4. Send the user back to the center's dashboard
    return redirect(url_for('center_dashboard'))

# --- END OF UPGRADED FUNCTION ---

if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)