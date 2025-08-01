# app.py
from flask import Flask, render_template, request, abort
import json
import os
import sys
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Add current directory to path so connecteam_api can be imported
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

try:
    import connecteam_api
except ImportError as e:
    logging.error(f"Failed to import connecteam_api: {e}")
    raise

# Load store config
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

try:
    with open(CONFIG_PATH, "r") as f:
        config = json.load(f)
    STORE_MAP = config.get("store_map", {})
    if not STORE_MAP:
        logging.warning("STORE_MAP is empty. Check config.json format.")
except (FileNotFoundError, json.JSONDecodeError) as e:
    STORE_MAP = {}
    logging.error(f"Failed to load config.json: {e}")

app = Flask(__name__)

@app.route("/")
def home():
    return "Connecteam Dashboard Running. Use /store/<store_id>?pin=xxxx"

@app.route("/store/<store_id>")
def store_dashboard(store_id):
    pin = request.args.get("pin")
    if store_id not in STORE_MAP:
        logging.warning(f"Attempted access to invalid store ID: {store_id}")
        return abort(404, description="Store ID not found.")

    if STORE_MAP[store_id].get("pin") != pin:
        logging.warning(f"Invalid PIN attempt for store ID: {store_id}")
        return abort(403, description="Invalid PIN.")

    try:
        time_clock_id = STORE_MAP[store_id].get("timeClockId")
        if not time_clock_id:
            raise ValueError("Missing timeClockId for this store.")
        employees = connecteam_api.get_employee_status_by_timeclock_id(time_clock_id)
    except Exception as e:
        logging.error(f"Error retrieving employee data for store {store_id}: {e}")
        return f"Error retrieving employee data: {str(e)}"

    return render_template("dashboard.html", employees=employees, store_id=store_id)

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0")
