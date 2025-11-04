from flask import Flask, render_template

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

# Start the Flask development server when this file is executed directly
if __name__ == '__main__':
    app.run(debug=True, use_reloader=False)