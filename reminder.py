#!/usr/bin/env python3
"""
reminder.py - Hourly "check LinkedIn" nudge to your phone via ntfy.

Only fires during your waking hours (8am-9pm America/Chicago). It's driven by an
hourly GitHub Action, but the send/skip decision is made HERE against real Chicago
local time — so daylight-saving is handled automatically and the window never drifts.

Pure standard library (no pip install needed).
"""
import os
import sys
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Chicago")
START_HOUR, END_HOUR = 8, 21          # inclusive: pings at 8:00 … 21:00 local
LINKEDIN = ("https://www.linkedin.com/jobs/search/"
            "?keywords=intern&sortBy=DD&f_TPR=r3600")   # interns, newest, past hour


def get_topic():
    t = os.environ.get("NTFY_TOPIC")
    if t:
        return t
    try:  # fall back to config.yaml if the secret isn't set
        import yaml
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "config.yaml")) as f:
            return (yaml.safe_load(f) or {}).get("ntfy_topic", "")
    except Exception:
        return ""


def main():
    now = datetime.now(TZ)
    if not (START_HOUR <= now.hour <= END_HOUR):
        print(f"{now:%H:%M} Chicago — outside {START_HOUR}:00-{END_HOUR}:00, skipping.")
        return

    topic = get_topic()
    if not topic or "CHANGE-ME" in topic:
        print("No ntfy topic configured; skipping.")
        return

    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
    req = urllib.request.Request(
        f"{server}/{topic}",
        data=b"Scan LinkedIn + Indeed for new internships and apply to anything fresh.",
        headers={
            "Title": "Job check",          # ASCII only (HTTP headers are latin-1)
            "Click": LINKEDIN,             # tap the notification -> LinkedIn, last hour
            "Tags": "bell",
            "Priority": "default",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=15)
        print(f"{now:%H:%M} Chicago — reminder sent.")
    except Exception as e:
        print(f"ntfy failed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
