# connecteam_api.py
import os
import json
import requests
import datetime

# Fixed Timezone support (Python 3.9+)
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

# Load config.json (store_map only)
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
with open(CONFIG_PATH, "r") as f:
    config = json.load(f)

STORE_MAP = config.get("store_map", {})

# API key & timezone from environment
API_KEY = os.getenv("CONNECTEAM_API_KEY")
if not API_KEY:
    raise RuntimeError("Missing CONNECTEAM_API_KEY environment variable")

TIMEZONE = os.getenv("TIMEZONE", "America/Los_Angeles")
TZ = ZoneInfo(TIMEZONE)

BASE_URL = "https://api.connecteam.com"
HEADERS = {
    "accept": "application/json",
    "X-API-KEY": API_KEY
}

def is_within_business_hours():
    now = datetime.datetime.now(tz=TZ)
    weekday = now.weekday()  # Monday=0, Sunday=6
    current_hour = now.hour

    if weekday == 6:  # Sunday
        return 9 <= current_hour < 17
    else:  # Monday to Saturday
        return 8 <= current_hour < 18

def format_duration(seconds: int) -> str:
    """Format seconds as H:MM (drop leading zero for hours)."""
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours}:{minutes:02}"

def format_time_utc_timestamp(ts: int) -> str:
    """
    Convert a UTC timestamp (seconds since epoch) into a localized
    12-hour time string (e.g. '1:48 PM') in the configured TZ.
    """
    dt_utc = datetime.datetime.fromtimestamp(ts, tz=ZoneInfo("UTC"))
    dt_local = dt_utc.astimezone(TZ)
    return dt_local.strftime("%I:%M %p").lstrip("0")

def get_active_users() -> dict:
    """Fetch active users and map userId → 'First L'."""
    url = f"{BASE_URL}/users/v1/users"
    params = {"limit": 200, "offset": 0, "order": "asc", "userStatus": "active"}
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    users = resp.json().get("data", {}).get("users", [])
    return {
        u["userId"]: f"{u.get('firstName','')} {u.get('lastName','')[:1]}"
        for u in users
    }

USER_MAP = get_active_users()

def get_weekly_totals_by_timeclock_id(clock_id: int, week_ending: datetime.date=None) -> dict:
    if week_ending is None:
        week_ending = datetime.date.today()
    week_start = week_ending - datetime.timedelta(days=week_ending.weekday())
    now_utc = datetime.datetime.now(tz=ZoneInfo("UTC"))
    now_ts = int(now_utc.timestamp())

    summary = {}
    for day_offset in range(7):
        day = week_start + datetime.timedelta(days=day_offset)
        ds = day.isoformat()
        url = f"{BASE_URL}/time-clock/v1/time-clocks/{clock_id}/time-activities"
        params = {"startDate": ds, "endDate": ds}
        resp = requests.get(url, headers=HEADERS, params=params)
        resp.raise_for_status()
        users_data = resp.json().get("data", {}).get("timeActivitiesByUsers", [])

        for ua in users_data:
            uid = ua["userId"]
            total_secs = 0
            for shift in ua.get("shifts", []):
                st = shift["start"]["timestamp"]
                en = shift.get("end", {}).get("timestamp")
                if st:
                    total_secs += (en or now_ts) - st
            break_secs = sum(
                (br["end"]["timestamp"] - br["start"]["timestamp"])
                for br in ua.get("manualBreaks", [])
                if br.get("start", {}).get("timestamp") and br.get("end", {}).get("timestamp")
            )
            net = max(0, total_secs - break_secs)

            entry = summary.setdefault(uid, {"dailySecs": {}, "weeklySecs": 0})
            entry["dailySecs"][ds] = net
            entry["weeklySecs"] += net

    for entry in summary.values():
        entry["dailyOver8"] = {
            d: secs >= 8*3600 for d, secs in entry["dailySecs"].items()
        }
        entry["weekOver40"] = entry["weeklySecs"] > 40*3600

    return summary

def get_employee_status_by_timeclock_id(clock_id: int, date: datetime.date=None) -> list:
    if not is_within_business_hours():
        print(f"⏰ Skipping API call for clock ID {clock_id} — outside of business hours.")
        return []

    if date is None:
        date = datetime.date.today()
    ds = date.isoformat()

    url = f"{BASE_URL}/time-clock/v1/time-clocks/{clock_id}/time-activities"
    params = {"startDate": ds, "endDate": ds}
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    activities = resp.json().get("data", {}).get("timeActivitiesByUsers", [])

    weekly = get_weekly_totals_by_timeclock_id(clock_id, date)
    now_utc = datetime.datetime.now(tz=ZoneInfo("UTC"))
    now_ts = int(now_utc.timestamp())

    employees = []
    for ua in activities:
        uid = ua["userId"]
        shifts = ua.get("shifts", [])
        if not shifts:
            continue

        total_secs = 0
        current_start_ts = None
        for shift in shifts:
            st = shift["start"]["timestamp"]
            en = shift.get("end", {}).get("timestamp")
            if st:
                if en:
                    total_secs += en - st
                else:
                    current_start_ts = st
                    total_secs += now_ts - st

        break_secs = 0
        on_break = False
        for br in ua.get("manualBreaks", []):
            bs = br["start"]["timestamp"]
            be = br.get("end", {}).get("timestamp")
            if bs and not be:
                on_break = True
            if bs and be:
                break_secs += be - bs

        net_daily_secs = max(0, total_secs - break_secs)

        daily_ot = max(0, net_daily_secs - 8*3600)
        weekly_secs = weekly.get(uid, {}).get("weeklySecs", 0)
        weekly_ot = max(0, weekly_secs - 40*3600)
        ot_secs = max(daily_ot, weekly_ot)

        if break_secs > 0:
            lunch_status = "Taken"
            lunch_class = "lunch-ok"
        else:
            if total_secs < 4*3600:
                lunch_status = "Not Yet Due"
                lunch_class = "lunch-ok"
            elif total_secs < 5*3600:
                lunch_status = "Due Now"
                lunch_class = "lunch-due"
            else:
                overdue = total_secs - 5*3600
                lunch_status = f"Overdue by {format_duration(overdue)}"
                lunch_class = "lunch-overdue"

        status = "On Lunch" if on_break else ("Clocked In" if current_start_ts else "Off")

        if current_start_ts:
            current_time_on_clock = format_duration(now_ts - current_start_ts)
            current_segment_start = format_time_utc_timestamp(current_start_ts)
            segment_secs = now_ts - current_start_ts
        else:
            current_time_on_clock = "0:00"
            current_segment_start = None
            segment_secs = 0

        employees.append({
            "name": USER_MAP.get(uid, str(uid)),
            "currentSegmentStart": current_segment_start,
            "currentTimeOnClock": current_time_on_clock,
            "_segmentSecs": segment_secs,
            "totalTimeOnClock": format_duration(net_daily_secs),
            "otToday": format_duration(ot_secs),
            "breakTaken": format_duration(break_secs),
            "status": status,
            "lunchStatus": lunch_status,
            "lunchClass": lunch_class
        })

    employees.sort(key=lambda e: e["_segmentSecs"], reverse=True)
    for e in employees:
        e.pop("_segmentSecs", None)

    return employees
