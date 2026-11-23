#!/usr/bin/env python3
"""Shows added in the app (data/added.json), next to the Concert Archives shows (data/concerts.csv).

The site writes data/added.json through the GitHub API when you add a show. The calendar
sync never touches it. Once you also log the show on Concert Archives and it arrives in
concerts.csv, `prune` drops the added copy so it isn't counted twice.

    python3 scripts/added_shows.py merge data/concerts.csv data/added.json OUT.csv
        concerts.csv plus every added show not already in it, with an extra ID column
        (what the site uses in #/show/<id>), for the widget and show-times scripts.
    python3 scripts/added_shows.py prune data/concerts.csv data/added.json
        remove added shows that concerts.csv now has (prints what it removed).

added.json: {"shows":[{"id","date":"YYYY-MM-DD","bands":[...],"title","venue","city","state",
"country","status":"" or "cancelled","start":"20:00","url":event page,"source":"tm:..."}]}
"""
import csv, json, re, sys, unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Los_Angeles")
HEADERS = ["Start Date", "End Date", "Nonstandard Concert Type", "Status", "Concert Name",
           "Bands Seen", "Bands Not Seen", "Venue", "Location", "URL"]


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower().replace("&", "and")
    s = re.sub(r"\b(the|theatre|theater|ballroom|club|hall)\b", "", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def overlap(a, b):
    a, b = norm(a), norm(b)
    return bool(a and b) and (a in b or b in a)


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return [s for s in data.get("shows", []) if s.get("id") and s.get("date")]


def csv_date(row):
    try:
        return datetime.strptime((row.get("Start Date") or "").strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return ""


def csv_bands(row):
    s = row.get("Bands Seen") or row.get("Concert Name") or ""
    return [p.strip() for p in s.replace(" / ", ";").split(";") if p.strip()]


def same_show(show, row):
    """The same night, and the same venue or a shared act. Mirrors sameShow() in index.html."""
    if csv_date(row) != show["date"]:
        return False
    if overlap(show.get("venue"), row.get("Venue")):
        return True
    return any(overlap(a, b) for a in show.get("bands", []) for b in csv_bands(row))


def to_row(show, today):
    status = (show.get("status") or "").strip().lower()
    if status not in ("cancelled", "canceled"):
        status = "upcoming" if show["date"] > today else "past"
    y, m, d = show["date"].split("-")
    return {
        "Start Date": f"{m}/{d}/{y}", "End Date": "", "Nonstandard Concert Type": "",
        "Status": status.capitalize(), "Concert Name": show.get("title", ""),
        "Bands Seen": " / ".join(show.get("bands", [])), "Bands Not Seen": "",
        "Venue": show.get("venue", ""),
        "Location": ", ".join(p for p in (show.get("city"), show.get("state"), show.get("country")) if p),
        "URL": "", "ID": show["id"],
    }


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def merge(concerts_path, added_path, out_path, today=None):
    today = today or datetime.now(TZ).date().isoformat()
    rows = read_csv(concerts_path)
    extra = [to_row(s, today) for s in load(added_path) if not any(same_show(s, r) for r in rows)]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADERS + ["ID"], extrasaction="ignore")
        w.writeheader()
        w.writerows(rows + extra)
    return len(extra)


def prune(concerts_path, added_path):
    rows, shows = read_csv(concerts_path), load(added_path)
    keep = [s for s in shows if not any(same_show(s, r) for r in rows)]
    if len(keep) == len(shows):
        return []
    gone = [s for s in shows if s not in keep]
    with open(added_path, encoding="utf-8") as f:
        data = json.load(f)
    data["shows"] = keep
    with open(added_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.write("\n")
    return gone


if __name__ == "__main__":
    cmd, *args = sys.argv[1:] or ["help"]
    if cmd == "merge" and len(args) == 3:
        print(f"added shows: {merge(*args)} merged in")
    elif cmd == "prune" and len(args) == 2:
        for s in prune(*args):
            print(f"now on Concert Archives, removed from added.json: {s['date']} {' / '.join(s.get('bands', []))}")
    else:
        sys.exit(__doc__)
