#!/usr/bin/env python3
"""Write the small JSON file the iPhone home screen widget reads.

    python3 scripts/build_widget_json.py data/concerts.csv _site/data/widget.json

It holds how many shows you've been to and the next upcoming ones. The widget
counts any of those that have since passed, so the number stays right between deploys.
"""
import csv, json, sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Los_Angeles")


def col(row, *names):
    for n in names:
        v = (row.get(n) or "").strip()
        if v:
            return v
    return ""


def parse_date(s):
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(s.strip(), fmt).date()
        except ValueError:
            pass
    return None


def split_bands(s):
    out = []
    for part in s.replace("|", ";").replace(" / ", ";").split(";"):
        part = part.strip()
        if part and part not in out:
            out.append(part)
    return out


def main(src, dst):
    today = datetime.now(TZ).date()
    attended, upcoming = 0, []
    with open(src, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            d = parse_date(col(row, "Start Date", "Date"))
            status = col(row, "Status").lower()
            if status in ("cancelled", "canceled", "rescheduled", "postponed"):
                continue
            future = d is not None and d >= today
            if status == "upcoming" or (not status and future):
                if not future:
                    continue  # stale "Upcoming"; the calendar sync flips these to Past
                bands = split_bands(col(row, "Bands Seen", "Concert Name", "Bands Not Seen"))
                url = col(row, "URL")
                location = col(row, "Location")
                upcoming.append({
                    "date": d.isoformat(),
                    "title": bands[0] if bands else col(row, "Concert Name") or "Concert",
                    "with": bands[1:],
                    "venue": col(row, "Venue"),
                    "city": location.split(",")[0].strip() if location else "",
                    "id": url.rstrip("/").split("/")[-1] if url else "",
                })
            elif status == "past" or (not status and d is not None):
                attended += 1
    upcoming.sort(key=lambda s: s["date"])
    out = {"generated": datetime.now(TZ).isoformat(timespec="seconds"),
           "attended": attended, "upcoming": upcoming[:12]}
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(f"widget.json: {attended} shows attended, {len(upcoming)} upcoming")


if __name__ == "__main__":
    main(*sys.argv[1:3])
