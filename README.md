# Connecteam Live Dashboard

This Flask app displays real-time employee timeclock data per store, with lunch/overtime warnings. Designed for ScreenCloud and California labor compliance.

---

## ✅ Features

- PIN-protected dashboards per store (e.g. `/store/2501?pin=secure1`)
- Displays:
  - First name + last initial
  - Clock In time
  - Time on Clock
  - Total Daily Time
  - Lunch Needed (⚠️ if ≥ 4 hrs + no break)
  - Overtime (✅ if >8 hrs/day or 40+/week)
- Auto-refreshes every 60 seconds
- Tailwind UI, TV-friendly
- Deployable to Render.com

---

## 🛠 Local Setup

1. Clone the repo or download the files
2. Install dependencies:
