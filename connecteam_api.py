# connecteam_api.py
import requests
import os
import datetime
import json
from zoneinfo import ZoneInfo

# Configuration
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
LA_TZ = ZoneInfo("America/Los_Angeles")

# Fetch active users and build a mapping userId -> "First LastInitial"
def get_active_users():
    url = f"{BASE_URL}/users/v1/users"
    params = {"limit": 200, "offset": 0, "order": "asc", "userStatus": "active"}
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    payload = resp.json()
    users = payload.get("data", {}).get("users", [])
    return {u.get("userId"): f"{u.get('firstName','')} {u.get('lastName','')[:1]}" for u in users}

USER_MAP = get_active_users()

def format_duration(seconds):
    """Format seconds into H:MM"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}:{minutes:02}"


def format_time(dt):
    """Format datetime into 12-hour with AM/PM"""
    return dt.strftime("%I:%M %p").lstrip('0')


def get_employee_status_by_timeclock_id(clock_id, date=None):
    """
    Get today's employee clock data with segment, totals, breaks, lunch & OT.
    Uses LA timezone for date.
    """
    if date is None:
        date = datetime.datetime.now(LA_TZ).date()
    start_str = date.isoformat()
    end_str = start_str

    # Daily activities
    url = f"{BASE_URL}/time-clock/v1/time-clocks/{clock_id}/time-activities"
    params = {"startDate": start_str, "endDate": end_str}
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    activities = resp.json().get("data", {}).get("timeActivitiesByUsers", [])

    # Weekly summary
    weekly_summary = get_weekly_totals_by_timeclock_id(clock_id, date)

    employees = []
    now_dt = datetime.datetime.now(LA_TZ)
    now_ts = int(now_dt.timestamp())

    for ua in activities:
        uid = ua.get("userId")
        shifts = ua.get("shifts", [])
        if not shifts:
            continue

        total_secs = 0
        current_start = None
        for shift in shifts:
            st = shift.get("start", {}).get("timestamp")
            en = shift.get("end", {}).get("timestamp")
            if st:
                if en:
                    total_secs += en - st
                else:
                    current_start = st
                    total_secs += now_ts - st

        break_secs = 0
        on_break = False
        for br in ua.get("manualBreaks", []):
            bs = br.get("start", {}).get("timestamp")
            be = br.get("end", {}).get("timestamp")
            if bs and not be:
                on_break = True
            if bs and be:
                break_secs += be - bs

        net_secs = max(0, total_secs - break_secs)

        daily_ot = max(0, net_secs - 8*3600)
        weekly_data = weekly_summary.get(uid, {})
        weekly_secs = weekly_data.get("weeklySecs", 0)
        weekly_ot = max(0, weekly_secs - 40*3600)
        ot_secs = max(daily_ot, weekly_ot)

        break_taken = format_duration(break_secs)
        needs_lunch = total_secs >= 4*3600 and break_secs < 30*60
        status = "On Lunch" if on_break else ("Clocked In" if current_start else "Off")

        if current_start:
            seg_dt = datetime.datetime.fromtimestamp(current_start, LA_TZ)
            seg_start = format_time(seg_dt)
            seg_secs = now_ts - current_start
            seg_time = format_duration(seg_secs)
        else:
            seg_start = None
            seg_time = "0:00"
            seg_secs = 0

        employees.append({
            "name": USER_MAP.get(uid, str(uid)),
            "status": status,
            "currentSegmentStart": seg_start,
            "currentTimeOnClock": seg_time,
            "currentSegmentSecs": seg_secs,
            "totalTimeOnClock": format_duration(net_secs),
            "otToday": format_duration(ot_secs),
            "breakTaken": break_taken,
            "needsLunch": needs_lunch
        })

    employees.sort(key=lambda x: x["currentSegmentSecs"], reverse=True)
    for e in employees:
        e.pop("currentSegmentSecs", None)

    return employees


def get_weekly_totals_by_timeclock_id(clock_id, week_ending=None):
    """
    Compute weekly summary (Mon–Sun) using LA timezone for consistency.
    """
    if week_ending is None:
        week_ending = datetime.datetime.now(LA_TZ).date()
    week_start = week_ending - datetime.timedelta(days=week_ending.weekday())
    now_ts = int(datetime.datetime.now(LA_TZ).timestamp())
    summary = {}

    for i in range(7):
        day = week_start + datetime.timedelta(days=i)
        d_str = day.isoformat()
        url = f"{BASE_URL}/time-clock/v1/time-clocks/{clock_id}/time-activities"
        params = {"startDate": d_str, "endDate": d_str}
        resp = requests.get(url, headers=HEADERS, params=params)
        resp.raise_for_status()
        users = resp.json().get("data", {}).get("timeActivitiesByUsers", [])

        for ua in users:
            uid = ua.get("userId")
            secs = 0
            for shift in ua.get("shifts", []):
                st = shift.get("start", {}).get("timestamp")
                en = shift.get("end", {}).get("timestamp")
                if st:
                    secs += (en or now_ts) - st
            b_secs = sum(
                (br.get("end", {}).get("timestamp") - br.get("start", {}).get("timestamp"))
                for br in ua.get("manualBreaks", [])
                if br.get("start", {}).get("timestamp") and br.get("end", {}).get("timestamp")
            )
            net = max(0, secs - b_secs)
            entry = summary.setdefault(uid, {"dailySecs": {}, "weeklySecs": 0})
            entry["dailySecs"][d_str] = net
            entry["weeklySecs"] += net

    for data in summary.values():
        data["dailyOver8"] = {day: s >= 8*3600 for day, s in data["dailySecs"].items()}
        data["weekOver40"] = data["weeklySecs"] > 40*3600

    return summary
