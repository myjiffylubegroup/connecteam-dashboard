# connecteam_api.py
import requests
import os
import datetime
import json

# Load configuration
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

API_KEY = config.get("connecteam_api_key")
STORE_MAP = config.get("store_map", {})
BASE_URL = "https://api.connecteam.com"
HEADERS = {
    "accept": "application/json",
    "X-API-KEY": API_KEY
}

# Fetch active users and build a mapping userId -> "First LastInitial"
def get_active_users():
    url = f"{BASE_URL}/users/v1/users"
    params = {"limit": 200, "offset": 0, "order": "asc", "userStatus": "active"}
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    payload = resp.json()
    users = payload.get("data", {}).get("users", [])
    return {
        u.get("userId"): f"{u.get('firstName','')} {u.get('lastName','')[:1]}"
        for u in users
    }

USER_MAP = get_active_users()

def format_duration(seconds):
    """
    Format a duration in seconds into H:MM (drop leading zero for hours).
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}:{minutes:02}"

def format_time(dt):
    """
    Format a datetime object into 12-hour clock with AM/PM.
    """
    return dt.strftime("%I:%M %p").lstrip('0')

def get_weekly_totals_by_timeclock_id(clock_id, week_ending=None):
    """
    Compute weekly summary for a given timeClockId.
    Returns a dict mapping userId → {"dailySecs":{...}, "weeklySecs":..., "dailyOver8":..., "weekOver40":...}
    """
    if week_ending is None:
        week_ending = datetime.date.today()
    week_start = week_ending - datetime.timedelta(days=week_ending.weekday())
    now_ts = int(datetime.datetime.now().timestamp())
    weekly_summary = {}

    for i in range(7):
        day = week_start + datetime.timedelta(days=i)
        day_str = day.isoformat()
        url = f"{BASE_URL}/time-clock/v1/time-clocks/{clock_id}/time-activities"
        params = {"startDate": day_str, "endDate": day_str}
        resp = requests.get(url, headers=HEADERS, params=params)
        resp.raise_for_status()
        users_data = resp.json().get("data", {}).get("timeActivitiesByUsers", [])

        for ua in users_data:
            uid = ua.get("userId")
            total = 0
            for shift in ua.get("shifts", []):
                st = shift.get("start", {}).get("timestamp")
                en = shift.get("end", {}).get("timestamp")
                if st:
                    total += (en or now_ts) - st
            breaks = sum(
                (br.get("end", {}).get("timestamp") - br.get("start", {}).get("timestamp"))
                for br in ua.get("manualBreaks", [])
                if br.get("start", {}).get("timestamp") and br.get("end", {}).get("timestamp")
            )
            net = max(0, total - breaks)

            entry = weekly_summary.setdefault(uid, {"dailySecs": {}, "weeklySecs": 0})
            entry["dailySecs"][day_str] = net
            entry["weeklySecs"] += net

    for entry in weekly_summary.values():
        entry["dailyOver8"] = {
            d: secs >= 8 * 3600 for d, secs in entry["dailySecs"].items()
        }
        entry["weekOver40"] = entry["weeklySecs"] > 40 * 3600

    return weekly_summary

def get_employee_status_by_timeclock_id(clock_id, date=None):
    """
    Fetch and compute per-employee daily status for a given timeClockId.
    Returns a list of dicts:
      name, currentSegmentStart, currentTimeOnClock, totalTimeOnClock,
      otToday, breakTaken, status, lunchStatus, lunchClass
    Sorted by length of current segment (longest first).
    """
    if date is None:
        date = datetime.date.today()
    ds = date.isoformat()

    # Fetch today's activities
    url = f"{BASE_URL}/time-clock/v1/time-clocks/{clock_id}/time-activities"
    params = {"startDate": ds, "endDate": ds}
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    activities = resp.json().get("data", {}).get("timeActivitiesByUsers", [])

    weekly = get_weekly_totals_by_timeclock_id(clock_id, date)
    now_ts = int(datetime.datetime.now().timestamp())
    employees = []

    for ua in activities:
        uid = ua.get("userId")
        shifts = ua.get("shifts", [])
        if not shifts:
            continue

        # Sum shift segments
        total = 0
        curr_start = None
        for shift in shifts:
            st = shift.get("start", {}).get("timestamp")
            en = shift.get("end", {}).get("timestamp")
            if st:
                if en:
                    total += en - st
                else:
                    curr_start = st
                    total += now_ts - st

        # Sum breaks
        breaks = 0
        on_break = False
        for br in ua.get("manualBreaks", []):
            bs = br.get("start", {}).get("timestamp")
            be = br.get("end", {}).get("timestamp")
            if bs and not be:
                on_break = True
            if bs and be:
                breaks += be - bs

        net_daily = max(0, total - breaks)

        # Overtime
        daily_ot = max(0, net_daily - 8 * 3600)
        week_secs = weekly.get(uid, {}).get("weeklySecs", 0)
        weekly_ot = max(0, week_secs - 40 * 3600)
        ot = max(daily_ot, weekly_ot)

        # Lunch status logic
        if breaks > 0:
            lunch_status = "Taken"
            lunch_class = "lunch-ok"
        else:
            if total < 4 * 3600:
                lunch_status = "Not Yet Due"
                lunch_class = "lunch-ok"
            elif total < 5 * 3600:
                lunch_status = "Due Now"
                lunch_class = "lunch-due"
            else:
                overdue = total - 5 * 3600
                lunch_status = f"Overdue by {format_duration(overdue)}"
                lunch_class = "lunch-overdue"

        status = "On Lunch" if on_break else ("Clocked In" if curr_start else "Off")

        # Current segment formatting
        if curr_start:
            seg_secs = now_ts - curr_start
            seg_time = format_duration(seg_secs)
            seg_start = format_time(datetime.datetime.fromtimestamp(curr_start))
        else:
            seg_start = None
            seg_time = "0:00"
            seg_secs = 0

        employees.append({
            "name": USER_MAP.get(uid, str(uid)),
            "currentSegmentStart": seg_start,
            "currentTimeOnClock": seg_time,
            "_segmentSecs": seg_secs,
            "totalTimeOnClock": format_duration(net_daily),
            "otToday": format_duration(ot),
            "breakTaken": format_duration(breaks),
            "status": status,
            "lunchStatus": lunch_status,
            "lunchClass": lunch_class
        })

    # Sort by current segment length desc, drop helper
    employees.sort(key=lambda x: x["_segmentSecs"], reverse=True)
    for e in employees:
        e.pop("_segmentSecs", None)

    return employees
