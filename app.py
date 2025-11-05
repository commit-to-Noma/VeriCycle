from flask import Flask, render_template, request, redirect, url_for, jsonify

# Initialize the Flask application
app = Flask(__name__)

# This "route" tells the app what to do when someone visits the main landing page
@app.route('/')
def index():
    # This function finds and displays the index.html page
    return render_template('index.html')

# This route is for the collector's dashboard
@app.route('/collector')
def collector_dashboard():
    return render_template('collector.html')

# This route is for the center's dashboard
@app.route('/center')
def center_dashboard():
    return render_template('center.html')

# --- ADD THIS NEW TEST CODE ---
@app.route('/hello')
def hello_world():
    return "Hello Noma! The server is loading my new file!"
# --- END OF NEW TEST CODE ---

# (The application will be started at the bottom after all routes are defined)


# --- ADD THIS NEW CODE AT THE BOTTOM OF APP.PY ---

# We need to import the new tools
import qrcode
import io
from flask import send_file

# This new route is specifically for creating the QR code
@app.route('/generate-qr')
def generate_qr():
    
    # This is the data we will put in the QR code.
    # This is your TEST collector ID from your .env file!
    # LATER, we will change this to be the ID of the logged-in user.
    collector_id = "0.0.7191569"
    
    # Generate the QR code in memory
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(collector_id)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    
    # Save the image to a "memory buffer" instead of a file
    img_io = io.BytesIO()
    img.save(img_io, 'PNG')
    img_io.seek(0)
    
    # Send the image back to the browser
    return send_file(img_io, mimetype='image/png')

# --- END OF NEW CODE ---

# Debug helper: return the list of registered routes as JSON
@app.route('/_routes')
def _routes():
    routes = []
    for rule in app.url_map.iter_rules():
        routes.append({
            'rule': str(rule),
            'methods': sorted([m for m in rule.methods if m not in ('HEAD','OPTIONS')])
        })
    return jsonify(routes)

# --- ADD THIS NEW CODE AT THE BOTTOM OF APP.PY ---

# This new route "catches" the data sent by our new form.
# It only accepts "POST" requests, which is how forms send data.
@app.route('/confirm-dropoff', methods=['GET', 'POST'])
def confirm_dropoff():
    """Accept GET for quick debugging and POST for real form submissions."""
    if request.method == 'POST':
        # 1. Read the data that came from the form
        collector_id = request.form.get('collector_id')
        weight = request.form.get('weight')

        # 2. THIS IS THE "WOW" MOMENT!
        # For now, we'll just print it to the terminal to prove it works.
        print("--- CONFIRMATION RECEIVED! ---")
        print(f"Collector ID: {collector_id}")
        print(f"Weight (kg): {weight}")
        print("--- (Next step: Call Hedera JavaScript functions!) ---")

        # 3. (LATER, we will call your Hedera scripts here)

        # 4. Send the user back to the center's dashboard
        return redirect(url_for('center_dashboard'))

    # If someone visits the URL in a browser (GET), show a short debug message
    return "confirm_dropoff endpoint: send a POST with 'collector_id' and 'weight'"

# --- END OF NEW CODE ---


# Print the registered routes to help debugging and then start the server
if __name__ == '__main__':
    print("Registered routes:")
    for rule in app.url_map.iter_rules():
        print(f"{rule.methods} -> {rule}")
    app.run(debug=True, use_reloader=False)