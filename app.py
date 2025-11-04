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

# This line makes the app run when you execute the python file
if __name__ == '__main__':
    app.run(debug=True)