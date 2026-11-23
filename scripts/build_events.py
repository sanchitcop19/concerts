#!/usr/bin/env python3
"""Build the event database that the site's "Add a show" search reads.

    TICKETMASTER_API_KEY=... SETLISTFM_API_KEY=... python3 scripts/build_events.py

Writes data/events/index.json and one data/events/YYYY-MM.json per month, covering
PAST_MONTHS back and FUTURE_MONTHS ahead, for the cities you go to shows in most
(worked out from data/concerts.csv, cities within MERGE_MILES of each other count as one).

  * Upcoming: Ticketmaster Discovery API (music + comedy). Shows that pass stay in the
    database, so it fills up with past Ticketmaster shows over time.
  * Past: setlist.fm (every show someone logged a setlist for). The first runs backfill
    year by year within SETLISTFM_MAX_CALLS per run; after that only new/updated setlists
    are fetched. Setlists from the same venue and date become one event with every act.

Each event is compact: {"id","d":"YYYY-MM-DD","t":"20:00","n":name,"a":[acts],"v":venue,
"c":city,"s":state,"co":country,"u":url,"m":market}; "a" is left out when it's just [name] and "co" when
it's the United States. Without API keys it keeps what's already there.
Standard library only.
"""
import csv, json, math, os, re, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "events")
CONCERTS = os.path.join(ROOT, "data", "concerts.csv")
TZ = ZoneInfo("America/Los_Angeles")

PAST_MONTHS = 24
FUTURE_MONTHS = 12
MARKET_MIN_SHOWS = 4      # a city (or cluster of nearby cities) needs this many shows in LOOKBACK_YEARS
LOOKBACK_YEARS = 3
MAX_MARKETS = 8
MERGE_MILES = 40          # cities this close together are one market (Seattle + Tacoma + Bellevue)
RADIUS_MILES = 35         # Ticketmaster search radius around each market
TM_API = "https://app.ticketmaster.com/discovery/v2"
TM_CLASSES = "KZFzniwnSyZfZ7v7nJ,KnvZfZ7vAe1"  # Music segment, Comedy genre
SL_API = "https://api.setlist.fm/rest/1.0"
SL_MAX_CALLS = int(os.environ.get("SETLISTFM_MAX_CALLS", "400"))  # 1440/day shared with sync_setlists
JUNK = re.compile(r"\b(parking|vip|upgrade|package|voucher|gift card|shuttle|tailgate|camping|locker|"
                  r"merch|meet ?& ?greet|add-on|souvenir|lawn chair|premium seat)\b", re.I)
COUNTRY = {"US": "United States", "CA": "Canada", "GB": "United Kingdom", "MX": "Mexico"}


# ---------------------------------------------------------------- helpers
def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"^the\s+", "", s.strip())
    return re.sub(r"[^a-z0-9]+", "", s)


def same_venue(a, b):
    a, b = norm(re.sub(r"\b(theatre|theater|ballroom|club|hall|the)\b", "", a or "", flags=re.I)), \
        norm(re.sub(r"\b(theatre|theater|ballroom|club|hall|the)\b", "", b or "", flags=re.I))
    return bool(a and b) and (a in b or b in a)


def miles(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def geohash(lat, lon, precision=7):
    chars, bits, out = "0123456789bcdefghjkmnpqrstuvwxyz", [16, 8, 4, 2, 1], ""
    la, lo, even, bit, ch = [-90.0, 90.0], [-180.0, 180.0], True, 0, 0
    while len(out) < precision:
        rng, val = (lo, lon) if even else (la, lat)
        mid = (rng[0] + rng[1]) / 2
        if val > mid:
            ch |= bits[bit]
            rng[0] = mid
        else:
            rng[1] = mid
        even = not even
        if bit < 4:
            bit += 1
        else:
            out += chars[ch]
            bit, ch = 0, 0
    return out


def add_months(d, n):
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def window(today):
    return add_months(today, -PAST_MONTHS), add_months(today, FUTURE_MONTHS + 1) - timedelta(days=1)


def http_json(url, headers=None, tries=4):
    for i in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": "stubs-concerts", "Accept": "application/json",
                                                   **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None  # setlist.fm answers an empty search with 404
            if e.code == 429 or e.code >= 500:
                time.sleep(2 ** i * 2)
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            time.sleep(2 ** i * 2)
    raise RuntimeError(f"giving up on {url.split('?')[0]}")


# ---------------------------------------------------------------- your cities
def history_cities(path=CONCERTS, today=None):
    """[(city, state, country, shows)] for shows in the last LOOKBACK_YEARS, most first."""
    today = today or datetime.now(TZ).date()
    since = today.replace(year=today.year - LOOKBACK_YEARS)
    c = Counter()
    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                try:
                    d = datetime.strptime(row.get("Start Date", ""), "%m/%d/%Y").date()
                except ValueError:
                    continue
                parts = [p.strip() for p in (row.get("Location") or "").split(",")]
                if d >= since and parts[0]:
                    c[(parts[0], parts[1] if len(parts) > 2 else "", parts[-1] if len(parts) > 1 else "")] += 1
    except OSError:
        pass
    return [(*k, n) for k, n in c.most_common()]


def build_markets(cities, geo):
    """Group cities by distance. cities: [(city,state,country,n)], geo: {city: (lat,lon)}.
    Returns [{"name","lat","lon","cities":[...],"shows":n}] for markets with enough shows."""
    markets = []
    for city, state, country, n in cities:
        loc = geo.get(city)
        if not loc:
            continue
        home = next((m for m in markets if miles((m["lat"], m["lon"]), loc) <= MERGE_MILES), None)
        if home:
            home["cities"].append(city)
            home["shows"] += n
        else:  # the busiest city is the center, since cities arrive most-first
            markets.append({"name": city, "state": state, "country": country, "lat": loc[0], "lon": loc[1],
                            "cities": [city], "shows": n})
    keep = [m for m in markets if m["shows"] >= MARKET_MIN_SHOWS]
    return sorted(keep, key=lambda m: -m["shows"])[:MAX_MARKETS]


def tm_geocode(key, city, state, country):
    """Where a city is, from any Ticketmaster venue in it."""
    q = {"apikey": key, "keyword": city, "size": 20}
    data = http_json(f"{TM_API}/venues.json?{urllib.parse.urlencode(q)}") or {}
    time.sleep(0.25)
    for v in data.get("_embedded", {}).get("venues", []):
        loc = v.get("location") or {}
        right_state = not state or norm(state) in (norm(v.get("state", {}).get("name")), norm(v.get("state", {}).get("stateCode")))
        if norm(v.get("city", {}).get("name")) == norm(city) and right_state and loc.get("latitude"):
            return float(loc["latitude"]), float(loc["longitude"])
    return None


# ---------------------------------------------------------------- Ticketmaster
def tm_event(ev):
    """Ticketmaster event -> compact event, or None for junk / cancelled / undated listings."""
    name = (ev.get("name") or "").strip()
    start = ev.get("dates", {}).get("start", {})
    if not name or not start.get("localDate") or JUNK.search(name):
        return None
    if ev.get("dates", {}).get("status", {}).get("code") in ("cancelled", "canceled"):
        return None
    emb = ev.get("_embedded", {})
    v = (emb.get("venues") or [{}])[0]
    # Ticketmaster tells same-named acts apart with a suffix: "Midnight - Band", "Gallagher - Comedian"
    acts = [re.sub(r"\s+-\s+(band|artist|musician|comedian|dj|singer|rapper|group)$", "", a["name"].strip(), flags=re.I)
            for a in emb.get("attractions", []) if a.get("name") and not JUNK.search(a["name"])]
    cc = v.get("country", {}).get("countryCode", "")
    out = {
        "id": "tm:" + ev["id"], "d": start["localDate"],
        "t": (start.get("localTime") or "")[:5] if not start.get("timeTBA") and not start.get("noSpecificTime") else "",
        "n": name, "a": acts or [re.sub(r"\s*\((?:21|18|all ages)[^)]*\)\s*$", "", name, flags=re.I)],
        "v": v.get("name", ""), "c": v.get("city", {}).get("name", ""),
        "s": v.get("state", {}).get("name", ""), "co": COUNTRY.get(cc, v.get("country", {}).get("name", "")),
        "u": ev.get("url", ""),
    }
    return compact(out)


def compact(ev):
    """Leave out what the site can assume: acts = [name], country = United States."""
    if ev.get("a") == [ev.get("n")]:
        del ev["a"]
    if ev.get("co") == "United States":
        del ev["co"]
    return {k: val for k, val in ev.items() if val}


def tm_fetch(key, market, start, end, log=print):
    """Every event in [start, end] around the market. Splits the date range when it holds
    more than the API's 1000-result paging limit."""
    events, page = [], 0
    while True:
        q = {"apikey": key, "geoPoint": geohash(market["lat"], market["lon"]), "radius": RADIUS_MILES,
             "unit": "miles", "classificationId": TM_CLASSES, "size": 200, "page": page, "sort": "date,asc",
             "startDateTime": f"{start}T00:00:00Z", "endDateTime": f"{end + timedelta(days=1)}T08:00:00Z"}
        data = http_json(f"{TM_API}/events.json?{urllib.parse.urlencode(q)}") or {}
        time.sleep(0.22)  # 5 requests/second
        info = data.get("page", {})
        if page == 0 and info.get("totalElements", 0) > 1000 and end > start:
            mid = start + (end - start) // 2
            return tm_fetch(key, market, start, mid, log) + tm_fetch(key, market, mid + timedelta(days=1), end, log)
        events += data.get("_embedded", {}).get("events", [])
        page += 1
        if page >= info.get("totalPages", 0) or page * 200 >= 1000:
            return events


# ---------------------------------------------------------------- setlist.fm
def sl_events(setlists):
    """setlist.fm setlists -> compact events, one per venue per day, with every act that played."""
    groups = {}
    for s in setlists:
        try:
            d = datetime.strptime(s["eventDate"], "%d-%m-%Y").date().isoformat()
        except (KeyError, ValueError):
            continue
        v, artist = s.get("venue") or {}, (s.get("artist") or {}).get("name", "").strip()
        city = v.get("city") or {}
        key = (d, v.get("id") or norm(v.get("name")))
        ev = groups.get(key)
        if ev is None:
            cc = city.get("country", {}).get("code", "")
            ev = groups[key] = {"id": f"sl:{key[1]}:{d}", "d": d, "n": "", "a": [], "v": v.get("name", ""),
                                "c": city.get("name", ""), "s": city.get("state", ""),
                                "co": COUNTRY.get(cc, city.get("country", {}).get("name", "")), "u": s.get("url", "")}
        if artist and artist not in ev["a"]:
            ev["a"].append(artist)
        ev["n"] = ev["n"] or (s.get("tour") or {}).get("name", "")
    out = []
    for ev in groups.values():
        if not ev["a"]:
            continue
        # A festival's tour name ("Capitol Hill Block Party") beats a list of a dozen acts
        if not (ev["n"] and len(ev["a"]) > 3):
            ev["n"] = " / ".join(ev["a"][:3]) + (" …" if len(ev["a"]) > 3 else "")
        out.append(compact(ev))
    return out


class OutOfBudget(Exception):
    pass


class SetlistFM:
    def __init__(self, key, budget=SL_MAX_CALLS):
        self.h, self.budget, self.calls = {"x-api-key": key}, budget, 0

    def page(self, **q):
        if self.calls >= self.budget:
            raise OutOfBudget
        self.calls += 1
        time.sleep(0.6)  # 2 requests/second
        return http_json(f"{SL_API}/search/setlists?{urllib.parse.urlencode(q)}", self.h) or {}

    def all_pages(self, start_page=1, **q):
        """Yields (page_number, setlists) until the last page; OutOfBudget when out of calls."""
        p = start_page
        while True:
            data = self.page(p=p, **q)
            items = data.get("setlist", [])
            yield p, items
            total, per = data.get("total", 0), data.get("itemsPerPage", 20) or 20
            if not items or p * per >= total:
                return
            p += 1


def sl_update(sfm, markets, state, today, log=print):
    """Backfill year by year per city, then only fetch what changed since the last run.
    `state` is kept in index.json between runs. Returns the setlists fetched."""
    first, _ = window(today)
    got = []
    started = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    done, cursor = set(state.get("done", [])), state.get("cursor", {})
    try:
        for m in markets:
            for city in m["cities"][:6]:
                for year in range(first.year, today.year + 1):
                    k = f"{city}|{year}"
                    if k in done:
                        continue
                    for p, items in sfm.all_pages(start_page=cursor.get(k, 1), cityName=city, year=year):
                        got += items
                        cursor[k] = p + 1
                    done.add(k)
                    cursor.pop(k, None)
        # Backfill finished: from now on just ask for what's new since the last full pass.
        since = state.get("lastUpdated")
        if since:
            for m in markets:
                for city in m["cities"][:6]:
                    for _, items in sfm.all_pages(cityName=city, lastUpdated=since):
                        got += items
        state["lastUpdated"] = started
    except OutOfBudget:
        log(f"setlist.fm: used this run's {sfm.budget} calls; the backfill continues next run")
    state["done"], state["cursor"] = sorted(done), cursor
    return got


# ---------------------------------------------------------------- the database
def load_db(out=OUT):
    events = {}
    if os.path.isdir(out):
        for f in sorted(os.listdir(out)):
            if re.match(r"^\d{4}-\d\d\.json$", f):
                with open(os.path.join(out, f), encoding="utf-8") as fh:
                    for ev in json.load(fh).get("events", []):
                        events[ev["id"]] = ev
    try:
        with open(os.path.join(out, "index.json"), encoding="utf-8") as fh:
            index = json.load(fh)
    except (OSError, ValueError):
        index = {}
    return events, index


def acts(ev):
    return ev.get("a") or [ev["n"]]


def dedupe(events):
    """One event per show: the same venue and day from setlist.fm and Ticketmaster are merged
    (Ticketmaster's listing wins, setlist.fm adds acts), and duplicate Ticketmaster listings
    of the same show collapse."""
    by_day = defaultdict(list)
    for ev in sorted(events.values(), key=lambda e: (not e["id"].startswith("tm:"), e["id"])):
        by_day[ev["d"]].append(ev)
    out = {}
    for d, evs in by_day.items():
        kept = []
        for ev in evs:
            twin = None
            for k in kept:
                if not same_venue(k.get("v"), ev.get("v")):
                    continue
                acts_k, acts_e = {norm(a) for a in acts(k)}, {norm(a) for a in acts(ev)}
                tm_both = k["id"].startswith("tm:") and ev["id"].startswith("tm:")
                # Two Ticketmaster listings at one venue on one day are the same show only if they share an act
                if not tm_both or acts_k & acts_e or norm(k["n"]) == norm(ev["n"]):
                    twin = k
                    break
            if twin is None:
                kept.append(dict(ev))
                continue
            twin["a"] = acts(twin)
            for a in acts(ev):
                if norm(a) not in {norm(x) for x in twin["a"]}:
                    twin["a"].append(a)
            for f in ("t", "u", "s", "co", "c", "m"):
                if not twin.get(f) and ev.get(f):
                    twin[f] = ev[f]
        for k in kept:
            out[k["id"]] = compact(k)
    return out


def write_db(events, index, out=OUT):
    os.makedirs(out, exist_ok=True)
    by_month = defaultdict(list)
    for ev in events.values():
        by_month[ev["d"][:7]].append(ev)
    for f in os.listdir(out):
        if re.match(r"^\d{4}-\d\d\.json$", f) and f[:7] not in by_month:
            os.remove(os.path.join(out, f))
    for m, evs in by_month.items():
        evs.sort(key=lambda e: (e["d"], e.get("t", ""), e["n"].lower(), e["id"]))
        # One event per line keeps the daily git diffs small.
        body = ",\n".join(json.dumps(e, ensure_ascii=False, separators=(",", ":")) for e in evs)
        with open(os.path.join(out, f"{m}.json"), "w", encoding="utf-8") as fh:
            fh.write(f'{{"month":"{m}","events":[\n{body}\n]}}\n')
    index["months"] = {m: len(v) for m, v in sorted(by_month.items())}
    index["count"] = sum(index["months"].values())
    with open(os.path.join(out, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=1, ensure_ascii=False)
        fh.write("\n")


def main():
    today = datetime.now(TZ).date()
    first, last = window(today)
    tm_key = os.environ.get("TICKETMASTER_API_KEY") or os.environ.get("TICKETMASTER_KEY")
    sl_key = os.environ.get("SETLISTFM_API_KEY")
    events, index = load_db()
    print(f"database: {len(events)} events")

    # Markets: reuse known city locations, look up new ones once.
    geo = {k: tuple(v) for k, v in index.get("geo", {}).items()}
    cities = history_cities(today=today)
    if tm_key:
        for city, state, country, n in cities:
            if city not in geo and n >= 2:
                loc = tm_geocode(tm_key, city, state, country)
                if loc:
                    geo[city] = loc
    markets = build_markets(cities, geo)
    print("markets:", ", ".join(f"{m['name']} ({m['shows']} shows: {', '.join(m['cities'])})" for m in markets))

    if tm_key:
        seen, ok = set(), True
        for m in markets:
            try:
                raw = tm_fetch(tm_key, m, today - timedelta(days=1), last)
            except Exception as e:  # keep going; just don't treat missing events as removed
                print(f"  Ticketmaster failed for {m['name']}: {e}")
                ok = False
                continue
            n = 0
            for ev in filter(None, map(tm_event, raw)):
                ev["m"] = m["name"]
                events[ev["id"]] = ev
                seen.add(ev["id"])
                n += 1
            print(f"  Ticketmaster {m['name']}: {n} events")
        if ok:  # upcoming listings that disappeared were cancelled or removed
            gone = [k for k, e in events.items() if k.startswith("tm:") and e["d"] >= today.isoformat() and k not in seen]
            for k in gone:
                del events[k]
            print(f"  removed {len(gone)} upcoming Ticketmaster events that are no longer listed")
    else:
        print("TICKETMASTER_API_KEY not set: skipping upcoming events")

    if sl_key:
        sfm = SetlistFM(sl_key)
        state = index.get("setlistfm", {})
        sets = sl_update(sfm, markets, state, today)
        index["setlistfm"] = state
        market_of = {c: m["name"] for m in markets for c in m["cities"]}
        for ev in sl_events(sets):
            if ev.get("c") in market_of:
                ev["m"] = market_of[ev["c"]]
            events[ev["id"]] = ev
        print(f"  setlist.fm: {len(sets)} setlists in {sfm.calls} calls")
    else:
        print("SETLISTFM_API_KEY not set: skipping past events")

    events = {k: e for k, e in events.items() if first.isoformat() <= e["d"] <= last.isoformat()}
    events = dedupe(events)
    index.update({
        "generated": datetime.now(TZ).isoformat(timespec="seconds"),
        "from": first.isoformat(), "to": last.isoformat(),
        "markets": [{k: m[k] for k in ("name", "state", "cities", "shows")} for m in markets],
        "geo": {k: list(v) for k, v in sorted(geo.items())},
    })
    write_db(events, index)
    print(f"wrote {len(events)} events, {first} to {last}")


if __name__ == "__main__":
    sys.exit(main())
