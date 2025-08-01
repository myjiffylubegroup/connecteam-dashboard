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
    """Format a duration in seconds into H:MM (drop leading zero for hours)."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours}:{minutes:02}"

def format_time(dt):
    """Format a datetime object into 12-hour clock with AM/PM."""
    return dt.strftime("%I:%M %p").lstrip('0')

def get_employee_status_by_timeclock_id(clock_id, date=None):
    """
    Fetch active time activities for a given timeClockId on a specific date
    (defaults to today). Returns a list of dicts with:
      - name
      - status / segment start / current time
      - totalTimeOnClock
      - otToday (daily vs weekly OT)
      - breakTaken / needsLunch
    Sorted by who’s been on their current segment the longest.
    """
    if date is None:
        date = datetime.date.today()
    start_str = date.isoformat()
    end_str = start_str

    # 1) Daily activities
    url = f"{BASE_URL}/time-clock/v1/time-clocks/{clock_id}/time-activities"
    params = {"startDate": start_str, "endDate": end_str}
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    payload = resp.json()
    activities = payload.get("data", {}).get("timeActivitiesByUsers", [])

    # 2) Weekly summary
    weekly_summary = get_weekly_totals_by_timeclock_id(clock_id, date)

    employees = []
    now_ts = int(datetime.datetime.now().timestamp())

    for ua in activities:
        user_id = ua.get("userId")
        shifts = ua.get("shifts", [])
        if not shifts:
            continue

        # sum up all shift segments, track current open one
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

        # sum up breaks
        break_secs = 0
        on_break = False
        for br in ua.get("manualBreaks", []):
            bs = br.get("start", {}).get("timestamp")
            be = br.get("end", {}).get("timestamp")
            if bs and not be:
                on_break = True
            if bs and be:
                break_secs += be - bs

        net_daily_secs = max(0, total_secs - break_secs)

        # daily & weekly OT
        daily_ot = max(0, net_daily_secs - 8 * 3600)
        weekly_data = weekly_summary.get(user_id, {})
        weekly_secs = weekly_data.get("weeklySecs", 0)
        weekly_ot = max(0, weekly_secs - 40 * 3600)
        ot_today_secs = max(daily_ot, weekly_ot)

        # format fields
        break_taken = format_duration(break_secs)
        needs_lunch = total_secs >= 4 * 3600 and break_secs < 30 * 60
        status = "On Lunch" if on_break else ("Clocked In" if current_start else "Off")

        if current_start:
            current_dt = datetime.datetime.fromtimestamp(current_start)
            current_segment_start = format_time(current_dt)
            current_segment_secs = now_ts - current_start
            current_time_on_clock = format_duration(current_segment_secs)
        else:
            current_segment_start = None
            current_time_on_clock = "0:00"
            current_segment_secs = 0

        employees.append({
            "userId": user_id,
            "name": USER_MAP.get(user_id, str(user_id)),
            "status": status,
            "currentSegmentStart": current_segment_start,
            "currentTimeOnClock": current_time_on_clock,
            "currentSegmentSecs": current_segment_secs,
            "totalTimeOnClock": format_duration(net_daily_secs),
            "otToday": format_duration(ot_today_secs),
            "breakTaken": break_taken,
            "needsLunch": needs_lunch
        })

    # sort by longest current segment
    employees.sort(key=lambda x: x["currentSegmentSecs"], reverse=True)

    # remove helper fields
    for emp in employees:
        emp.pop("userId", None)
        emp.pop("currentSegmentSecs", None)

    return employees

def get_weekly_totals_by_timeclock_id(clock_id, week_ending=None):
    """
    Compute weekly summary for a given timeClockId.
    Returns a dict: userId -> {
      dailySecs: { 'YYYY-MM-DD': secs, … },
      weeklySecs: total_secs,
      dailyOver8: { day: bool, … },
      weekOver40: bool
    }
    """
    if week_ending is None:
        week_ending = datetime.date.today()
    week_start = week_ending - datetime.timedelta(days=week_ending.weekday())
    now_ts = int(datetime.datetime.now().timestamp())
    summary = {}

    for i in range(7):
        day = week_start + datetime.timedelta(days=i)
        start_str = day.isoformat()
        url = f"{BASE_URL}/time-clock/v1/time-clocks/{clock_id}/time-activities"
        params = {"startDate": start_str, "endDate": start_str}
        resp = requests.get(url, headers=HEADERS, params=params)
        resp.raise_for_status()
        payload = resp.json()
        users_data = payload.get("data", {}).get("timeActivitiesByUsers", [])

        for ua in users_data:
            uid = ua.get("userId")
            total_secs = 0
            for shift in ua.get("shifts", []):
                st = shift.get("start", {}).get("timestamp")
                en = shift.get("end", {}).get("timestamp")
                if st:
                    total_secs += (en or now_ts) - st
            break_secs = sum(
                (br.get("end", {}).get("timestamp") - br.get("start", {}).get("timestamp"))
                for br in ua.get("manualBreaks", [])
                if br.get("start", {}).get("timestamp") and br.get("end", {}).get("timestamp")
            )
            net = max(0, total_secs - break_secs)

            entry = summary.setdefault(uid, {"dailySecs": {}, "weeklySecs": 0})
            entry["dailySecs"][start_str] = net
            entry["weeklySecs"] += net

    for data in summary.values():
        data["dailyOver8"] = {
            d: secs >= 8 * 3600 for d, secs in data["dailySecs"].items()
        }
        data["weekOver40"] = data["weeklySecs"] > 40 * 3600

    return summary
