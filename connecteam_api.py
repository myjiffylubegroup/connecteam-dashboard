from datetime import datetime, timedelta

def get_employee_status_by_store(store_id):
    mock_data = {
        "2501": [
            mock_employee("Jason", "M", "08:00", lunch_taken=True, total_hours=5.2),
            mock_employee("Marie", "B", "07:30", lunch_taken=False, total_hours=4.5),
            mock_employee("Liam", "K", "06:00", lunch_taken=True, total_hours=9.1)
        ],
        "1257": [
            mock_employee("Nina", "T", "09:15", lunch_taken=False, total_hours=3.7),
            mock_employee("Eli", "R", "05:45", lunch_taken=True, total_hours=8.8)
        ]
    }
    return mock_data.get(store_id, [])

def mock_employee(first, last_initial, clock_in_time_str, lunch_taken, total_hours):
    now = datetime.now()
    clock_in_time = datetime.strptime(clock_in_time_str, "%H:%M")
    time_on_clock = (now - clock_in_time.replace(year=now.year, month=now.month, day=now.day)).total_seconds() / 3600

    return {
        "name": f"{first} {last_initial}.",
        "clock_in": clock_in_time.strftime("%I:%M %p"),
        "time_on_clock": round(time_on_clock, 2),
        "total_hours": round(total_hours, 2),
        "lunch_needed": not lunch_taken and time_on_clock >= 4.0,
        "overtime": total_hours >= 8.0
    }
