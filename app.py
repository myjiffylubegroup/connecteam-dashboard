# app.py

from flask import Flask, render_template, request, abort
import json
import sys
import os

# Add current script's directory to sys.path so Python can find local modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
print("✔️ sys.path includes:", os.path.dirname(os.path.abspath(__file__)))

# Import your local module (must be in same folder)
import connecteam_api

app = Flask(__name__)

# Load store PINs from config
with open("config.json", "r") as f:
    STORE_PINS = json.load(f)

@app.route("/")
def home():
    return "✅ Connecteam Dashboard Running. Use /store/<store_id>?pin=xxxx"

@app.route("/store/<store_id>")
def store_dashboard(store_id):
    pin = request.args.get("pin")
    if store_id not in STORE_PINS or STORE_PINS[store_id] != pin:
        return abort(403)

    employees = connecteam_api.get_employee_status_by_store(store_id)
    return render_template("dashboard.html", employees=employees, store_id=store_id)

if __name__ == "__main__":
    app.run(debug=True, port=5050)
