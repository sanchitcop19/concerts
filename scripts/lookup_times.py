#!/usr/bin/env python3
"""Look up start and doors times for upcoming shows on Ticketmaster.

    TICKETMASTER_API_KEY=... python3 scripts/lookup_times.py data/concerts.csv _site/data/times.json

Writes {"<show id>": {"start": "20:00", "doors": "19:00", "url": "..."}} for every
upcoming show it can match. "doors" is only there when Ticketmaster lists it
(as a doors time, or written in the event notes like "Doors 7pm").
Without an API key it writes an empty file, so the site still works.
"""
import csv, json, os, re, sys, time, unicodedata, urllib.parse, urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_widget_json import TZ, col, parse_date, split_bands  # noqa: E402

API = "https://app.ticketmaster.com/discovery/v2/events.json"


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"^the\s+|\s+(theatre|theater|ballroom|club|hall)$", "", s.strip())
    return re.sub(r"[^a-z0-9]+", "", s)


def same(a, b):
    a, b = norm(a), norm(b)
    return bool(a and b) and (a in b or b in a)


def hhmm(t):
    return t[:5] if t and re.match(r"^\d\d:\d\d", t) else None


def doors_from_text(text):
    """'Doors: 7:00 PM' / 'doors open at 7pm' / 'Doors 19:30' -> '19:00'."""
    m = re.search(r"doors?(?:\s+open)?(?:\s+at)?\s*[:\-@]?\s*(\d{1,2})(?::(\d\d))?\s*([ap]\.?m\.?)?", text or "", re.I)
    if not m:
        return None
    h, mins, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ap.startswith("p") and h < 12:
        h += 12
    elif ap.startswith("a") and h == 12:
        h = 0
    elif not ap and 1 <= h <= 11:
        h += 12  # "Doors 7" at a concert means the evening
    return f"{h:02d}:{mins:02d}" if h < 24 and mins < 60 else None


def search(key, keyword, day):
    # The API filters in UTC, so search a wider window and match the local date ourselves.
    q = {
        "apikey": key, "keyword": keyword, "size": 50,  # no music-only filter: comedy and theater count too
        "startDateTime": f"{day - timedelta(days=1)}T00:00:00Z",
        "endDateTime": f"{day + timedelta(days=2)}T00:00:00Z",
    }
    req = urllib.request.Request(f"{API}?{urllib.parse.urlencode(q)}", headers={"User-Agent": "stubs-concerts"})
    time.sleep(0.25)  # stay under 5 requests a second
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r).get("_embedded", {}).get("events", [])
    except Exception as e:  # one failed lookup shouldn't break the deploy
        print(f"  lookup failed for {keyword!r}: {e}")
        return []


def best_match(events, show):
    """Same local date, then prefer the right venue, then the right artist."""
    scored = []
    for ev in events:
        start = ev.get("dates", {}).get("start", {})
        if start.get("localDate") != show["date"].isoformat():
            continue
        venues = ev.get("_embedded", {}).get("venues", [])
        artists = [a.get("name", "") for a in ev.get("_embedded", {}).get("attractions", [])]
        at_venue = any(same(v.get("name"), show["venue"]) for v in venues)
        in_city = any(same(v.get("city", {}).get("name"), show["city"]) for v in venues)
        has_band = any(same(a, b) for a in artists + [ev.get("name", "")] for b in show["bands"])
        if not (at_venue or (in_city and has_band)):
            continue
        scored.append((at_venue * 2 + has_band, ev))
    return max(scored, key=lambda x: x[0])[1] if scored else None


NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "thirty": 30, "forty-five": 45, "ninety": 90}


def doors_before_start(text, start):
    """'Doors open one hour before show time' / 'doors 30 minutes prior' + start '18:00' -> '17:00'."""
    m = re.search(r"doors?(?:\s+open)?\s+(half an|\d+|[a-z-]+)\s+(hours?|minutes?|mins?)\s+(?:before|prior)", text or "", re.I)
    if not (m and start):
        return None
    n, unit = m.group(1).lower(), m.group(2).lower()
    if n == "half an":
        mins = 30
    else:
        count = int(n) if n.isdigit() else NUMBERS.get(n)
        mins = count and count * (60 if unit.startswith("h") else 1)
    if not mins or mins > 180:
        return None
    h, mm = map(int, start.split(":"))
    t = h * 60 + mm - mins
    return f"{t // 60:02d}:{t % 60:02d}" if t >= 0 else None


def times_for(ev):
    dates = ev.get("dates", {})
    out = {"start": hhmm(dates.get("start", {}).get("localTime"))}
    doors = hhmm((dates.get("doorsTimes") or {}).get("localTime"))
    notes = " ".join(filter(None, [ev.get("pleaseNote"), ev.get("info")]))
    doors = doors or doors_before_start(notes, out["start"]) or doors_from_text(notes)
    if doors:
        out["doors"] = doors
    if ev.get("url"):
        out["url"] = ev["url"]
    return {k: v for k, v in out.items() if v}


def upcoming_shows(src):
    today = datetime.now(TZ).date()
    with open(src, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            d = parse_date(col(row, "Start Date", "Date"))
            if not d or d < today or col(row, "Status").lower() not in ("upcoming", ""):
                continue
            url, loc = col(row, "URL"), col(row, "Location")
            yield {
                "id": url.rstrip("/").split("/")[-1] if url else "",
                "date": d,
                "bands": split_bands(col(row, "Bands Seen", "Concert Name", "Bands Not Seen")),
                "venue": col(row, "Venue"),
                "city": loc.split(",")[0].strip() if loc else "",
            }


def previous_times():
    """Times from the last deploy. Ticketmaster stops listing a show once it's over,
    so this is how past shows keep their doors/start times."""
    url = os.environ.get("PREVIOUS_TIMES_URL", "").strip()
    if not url:
        return {}
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "stubs-concerts"})
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.load(r)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"  couldn't load previous times: {e}")
        return {}


def main(src, dst):
    key = os.environ.get("TICKETMASTER_API_KEY", "").strip()
    upcoming_ids = {s["id"] for s in upcoming_shows(src)}
    # Keep old times for shows that are no longer upcoming; upcoming ones get looked up fresh.
    found = {k: v for k, v in previous_times().items() if k not in upcoming_ids}
    kept = len(found)
    if not key:
        print("times.json: no TICKETMASTER_API_KEY, skipping lookups")
    else:
        for show in upcoming_shows(src):
            if not show["id"]:
                continue
            # Try the headliner first, then the venue (catches festivals and renamed acts).
            ev = None
            for kw in [*show["bands"][:1], show["venue"]]:
                if kw and (ev := best_match(search(key, kw, show["date"]), show)):
                    break
            label = f"{show['date']} {show['bands'][:1]} @ {show['venue']}"
            if ev and (t := times_for(ev)):
                found[show["id"]] = t
                print(f"  {label}: {t.get('doors', '?')} doors, {t.get('start', '?')} start")
            else:
                print(f"  {label}: not found")
        print(f"times.json: matched {len(found) - kept} upcoming shows")
    print(f"times.json: kept {kept} past shows from the last deploy")
    with open(dst, "w", encoding="utf-8") as f:
        json.dump(found, f, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:3])
