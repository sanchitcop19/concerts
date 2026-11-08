#!/usr/bin/env python3
"""Pull shows from the "Sanchit's Concert Archive" Google Calendar into data/concerts.csv.

Concert Archives adds every show to that calendar as an event like:
    SUMMARY:  Russian Circles / Primitive Man @ The Showbox
    LOCATION: The Showbox, Seattle, Washington, United States
    DESCRIPTION: View on Concert Archives: https://www.concertarchives.org/sanchitcop19/concerts/...

We read Concert Archives' calendar feed (env CALENDAR_ICS_URL, kept as a GitHub secret),
then MERGE into the existing CSV, keyed by the Concert Archives URL:
  * new shows are added (bands come from the event title, the only place the feed has them),
  * existing shows get their date / venue / location / status refreshed, but NEVER their bands:
    the event title mixes in "bands not seen" and uses the event name for festivals
    (e.g. "NAMM"), so the export's "Bands Seen" is the better list,
  * a CANCELLED event marks the show Cancelled (the feed also uses this for rescheduled shows,
    so an existing Rescheduled status is kept),
  * nothing is ever deleted.

Usage:  CALENDAR_ICS_URL=... python3 scripts/sync_calendar.py [--ics local.ics] [--dry-run]
Standard library only.
"""
import csv, io, os, re, sys, urllib.error, urllib.request
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(ROOT, "data", "concerts.csv")
HEADERS = ["Start Date", "End Date", "Nonstandard Concert Type", "Status", "Concert Name",
           "Bands Seen", "Bands Not Seen", "Venue", "Location", "URL"]
HOME_TZ = ZoneInfo("America/Los_Angeles")
CA_URL = re.compile(r"https://www\.concertarchives\.org/[^\s\"<>\\]+")


# ---------- iCal parsing ----------
def unfold(text):
    """iCal wraps long lines with a leading space on the continuation line."""
    return re.sub(r"\r?\n[ \t]", "", text).splitlines()

def unescape(v):
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")

def parse_date(name, value):
    """DTSTART;VALUE=DATE:20261115 | DTSTART:20261116T040000Z | DTSTART;TZID=America/New_York:20261115T200000"""
    params = dict(p.split("=", 1) for p in name.split(";")[1:] if "=" in p)
    if len(value) == 8:
        return datetime.strptime(value, "%Y%m%d").date()
    dt = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        # A UTC time: use the date where the show actually happened. A late-evening
        # Pacific show is already "tomorrow" in UTC.
        return dt.replace(tzinfo=timezone.utc).astimezone(HOME_TZ).date()
    return dt.date()  # floating or TZID time: the wall-clock date is the show date

def parse_ics(text):
    events, cur = [], None
    for line in unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            if cur is not None:
                events.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            name, value = line.split(":", 1)
            key = name.split(";", 1)[0].upper()
            if key == "DTSTART":
                cur["date"] = parse_date(name, value)
            elif key in ("SUMMARY", "LOCATION", "DESCRIPTION", "URL", "STATUS"):
                cur[key.lower()] = unescape(value).strip()
    return events

def to_row(ev):
    """Turn one calendar event into a CSV row (or None if it isn't a show)."""
    if "date" not in ev or not ev.get("summary"):
        return None
    m = CA_URL.search(ev.get("url", "") + " " + ev.get("description", ""))
    if not m:
        return None  # not a Concert Archives event
    summary = ev["summary"]
    bands, venue = (summary.rsplit(" @ ", 1) + [""])[:2] if " @ " in summary else (summary, "")
    location = ev.get("location", "")
    if venue and location.startswith(venue + ","):
        location = location[len(venue) + 1:].strip()
    return {
        "Start Date": ev["date"].strftime("%m/%d/%Y"),
        "Status": "Cancelled" if ev.get("status", "").upper() == "CANCELLED"
                  else "Upcoming" if ev["date"] >= datetime.now(HOME_TZ).date() else "Past",
        "Bands Seen": bands.strip(),
        "Venue": venue.strip(),
        "Location": location,
        "URL": m.group(0).rstrip(".,);"),
    }


# ---------- merge ----------
def sort_key(row):
    try:
        return datetime.strptime(row["Start Date"], "%m/%d/%Y").date()
    except ValueError:
        return date.min

def merge(existing, cal_rows):
    by_url = {r["URL"]: r for r in existing if r.get("URL")}
    added = updated = 0
    for c in cal_rows:
        row = by_url.get(c["URL"])
        if row is None and c["Status"] == "Cancelled":
            continue  # never add a show that's already cancelled
        if row is None:
            row = {h: "" for h in HEADERS}
            row.update(c)
            existing.append(row)
            by_url[c["URL"]] = row
            added += 1
            continue
        before = dict(row)
        for k in ("Start Date", "Venue", "Location"):
            if c[k]:
                row[k] = c[k]
        if row.get("Status", "").lower() not in ("cancelled", "rescheduled"):
            row["Status"] = c["Status"]
        updated += row != before
    # Shows that slipped into the past since the last run
    today = datetime.now(HOME_TZ).date()
    for r in existing:
        if r.get("Status") == "Upcoming" and sort_key(r) < today:
            r["Status"] = "Past"
    existing.sort(key=sort_key, reverse=True)
    return added, updated


def main():
    args = sys.argv[1:]
    if "--ics" in args:
        text = open(args[args.index("--ics") + 1], encoding="utf-8").read()
    else:
        url = os.environ.get("CALENDAR_ICS_URL", "").strip()
        if not url:
            sys.exit("Set CALENDAR_ICS_URL (the Concert Archives calendar feed link).")
        if url.lower().startswith("webcal://"):  # calendar apps' scheme for the same https feed
            url = "https://" + url[len("webcal://"):]
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; concerts-calendar-sync)",
                                                   "Accept": "text/calendar, */*"})
        try:
            text = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if "Just a moment" in body or "cf-" in body:
                sys.exit(f"HTTP {e.code}: the feed is behind Cloudflare's bot check and blocked this server.")
            sys.exit(f"HTTP {e.code} fetching the calendar feed. Check the link.")
    if "BEGIN:VCALENDAR" not in text:
        sys.exit("That link didn't return a calendar. Check the feed link.")

    cal_rows = [r for r in map(to_row, parse_ics(text)) if r]
    with open(CSV_PATH, newline="", encoding="utf-8-sig") as f:
        existing = list(csv.DictReader(f))
    if cal_rows == [] and existing:
        sys.exit("Calendar had no Concert Archives events; leaving the data alone.")

    added, updated = merge(existing, cal_rows)
    print(f"calendar: {len(cal_rows)} shows · added {added} · updated {updated} · total {len(existing)}")
    if "--dry-run" in args:
        return
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=HEADERS, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(existing)
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())


if __name__ == "__main__":
    main()
