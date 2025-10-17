from flask import Flask, render_template, jsonify
import os
import requests
from dotenv import load_dotenv
import time

load_dotenv()

app = Flask(__name__, static_folder=None)  # Disable static folder to avoid redirects

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/availability')
def get_availability():
    try:
        start_time = time.time()
        response = requests.get(os.getenv("OCI_API_URL", "http://168.107.19.211:5000/api/availability"), timeout=15)  # Increase to 15 seconds
        response.raise_for_status()
        print(f"API request took {time.time() - start_time} seconds")
        return jsonify(response.json())
    except requests.RequestException as e:
        print(f"API error: {e}")
        return jsonify({"error": "Failed to fetch availability from Oracle"}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)