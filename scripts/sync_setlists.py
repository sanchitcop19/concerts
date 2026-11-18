#!/usr/bin/env python3
"""Turn every past show in data/concerts.csv into a Spotify playlist of what was actually played.

For each show:
  1. setlist.fm: find the setlist of each band seen, on the show's date(s).
  2. Spotify: match each song to a track, then create/refresh a private playlist named
         "2019-05-12 · Artist / Opener @ Venue"
     The ISO date prefix means "Sort by: Alphabetical" in Your Library lists them oldest first.
  3. One extra playlist, "Concert Setlists · All Shows (oldest first)", holds every show's
     setlist back to back in chronological order.

Everything learnt is cached in data/setlists.json (setlists, song->track matches, playlist ids),
so a daily run only makes API calls for new shows or shows whose setlist hasn't appeared yet.

Env (GitHub secrets): SETLISTFM_API_KEY, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET,
SPOTIFY_REFRESH_TOKEN (get it once with scripts/spotify_auth.py).
Usage:  python3 scripts/sync_setlists.py [--dry-run]     Standard library only.
"""
import base64, csv, hashlib, json, os, re, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(ROOT, "data", "concerts.csv")
STATE_PATH = os.path.join(ROOT, "data", "setlists.json")
MASTER_NAME = "Concert Setlists · All Shows (oldest first)"
MAX_SETLIST_CALLS = int(os.environ.get("SETLISTFM_MAX_CALLS", "500"))  # setlist.fm allows 1440/day
RECHECK_FOUND_DAYS = 14    # setlists get corrected for a while after the show
RECHECK_MISSING_DAYS = 90  # keep looking this long for a setlist nobody has posted yet
RECHECK_EVERY_DAYS = 3
MAX_SPOTIFY_SEARCHES = int(os.environ.get("SPOTIFY_MAX_SEARCHES", "1500"))  # first run spreads over a few days
TODAY = date.today()


# ---------- pure helpers (unit tested) ----------
def parse_us_date(s):
    return datetime.strptime(s.strip(), "%m/%d/%Y").date() if s and s.strip() else None

def split_bands(s):
    return [b.strip() for b in (s or "").split(" / ") if b.strip()]

def show_dates(start, end):
    end = end if end and end >= start else start
    return [start + timedelta(days=i) for i in range((end - start).days + 1)][:7]

def load_shows(path=CSV_PATH):
    shows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            start = parse_us_date(r.get("Start Date"))
            if not start or r.get("Status") != "Past" or start > TODAY:
                continue
            bands = split_bands(r.get("Bands Seen"))
            if not bands:
                continue
            key = r.get("URL") or f"{start}|{r.get('Bands Seen')}|{r.get('Venue')}"
            shows.append({"key": key, "start": start, "end": parse_us_date(r.get("End Date")),
                          "bands": bands, "venue": (r.get("Venue") or "").strip(),
                          "name": (r.get("Concert Name") or "").strip()})
    shows.sort(key=lambda s: (s["start"], s["key"]))
    return shows

def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\(.*?\)|\[.*?\]", " ", s)
    s = re.sub(r"\s-\s.*$", " ", s)  # "Song - Remastered 2011"
    s = s.replace("&", "and")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

def playlist_name(show):
    title = show["name"] or " / ".join(show["bands"])
    name = f"{show['start'].isoformat()} · {title}"
    if show["venue"]:
        name += f" @ {show['venue']}"
    return name if len(name) <= 100 else name[:99] + "…"

def songs_from_setlist(sl):
    """setlist.fm setlist JSON -> [{'name','artist'}] in played order, skipping tape/intro music."""
    out, artist = [], sl.get("artist", {}).get("name", "")
    for st in (sl.get("sets") or {}).get("set", []) or []:
        for song in st.get("song", []) or []:
            name = (song.get("name") or "").strip()
            if not name or song.get("tape"):
                continue
            cover = (song.get("cover") or {}).get("name")
            out.append({"name": name, "artist": artist, **({"cover": cover} if cover else {})})
    return out

def pick_setlist(results, band, dates):
    """Best setlist.fm result for this band on one of these dates (prefers exact name, most songs)."""
    want = {d.strftime("%d-%m-%Y") for d in dates}
    cands = [s for s in results if s.get("eventDate") in want]
    exact = [s for s in cands if norm(s.get("artist", {}).get("name")) == norm(band)]
    cands = exact or cands
    return max(cands, key=lambda s: len(songs_from_setlist(s)), default=None)

def pick_track(items, song, artist):
    """First Spotify result whose title and artist both match; else first with a matching artist."""
    ns, na = norm(song), norm(artist)
    def artists(t): return [norm(a.get("name")) for a in t.get("artists", [])]
    for t in items:
        if norm(t.get("name")) == ns and na in artists(t):
            return t["uri"]
    for t in items:
        if na in artists(t) and (ns in norm(t.get("name")) or norm(t.get("name")) in ns):
            return t["uri"]
    return None

def needs_check(entry, show_start, today=TODAY):
    if not entry or "checked" not in entry:
        return True
    age = (today - show_start).days
    since = (today - date.fromisoformat(entry["checked"])).days
    found = any(s.get("songs") for s in entry.get("sets", []))
    limit = RECHECK_FOUND_DAYS if found else RECHECK_MISSING_DAYS
    return age <= limit and since >= RECHECK_EVERY_DAYS

def track_key(song):
    return f"{norm(song['artist'])}|{norm(song['name'])}"

def show_uris(entry, tracks):
    return [tracks[track_key(s)] for st in entry.get("sets", []) for s in st.get("songs", [])
            if tracks.get(track_key(s))]

def digest(name, uris):
    return hashlib.sha1((name + "\n" + "\n".join(uris)).encode()).hexdigest()[:16]


# ---------- HTTP ----------
def http(method, url, headers=None, body=None, form=None, tries=5):
    data = None
    headers = dict(headers or {})
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                wait = int(e.headers.get("Retry-After") or 0) or 2 ** attempt
                time.sleep(min(wait, 60))
                continue
            if e.code == 404:
                return 404, {}
            raise RuntimeError(f"{method} {url.split('?')[0]} -> {e.code}: {e.read()[:300]!r}")
    raise RuntimeError(f"{method} {url.split('?')[0]} kept failing")


class SetlistFM:
    def __init__(self, key):
        self.h = {"x-api-key": key, "Accept": "application/json", "User-Agent": "concerts-setlist-sync"}
        self.calls = 0

    def search(self, band, d):
        self.calls += 1
        time.sleep(0.6)  # API limit: 2 requests/second
        q = urllib.parse.urlencode({"artistName": band, "date": d.strftime("%d-%m-%Y")})
        _, j = http("GET", f"https://api.setlist.fm/rest/1.0/search/setlists?{q}", self.h)
        return j.get("setlist", []) or []


class Spotify:
    API = "https://api.spotify.com/v1"

    def __init__(self, cid, secret, refresh):
        auth = base64.b64encode(f"{cid}:{secret}".encode()).decode()
        _, j = http("POST", "https://accounts.spotify.com/api/token", {"Authorization": f"Basic {auth}"},
                    form={"grant_type": "refresh_token", "refresh_token": refresh})
        self.h = {"Authorization": f"Bearer {j['access_token']}"}

    def call(self, method, path, body=None):
        return http(method, self.API + path, self.h, body=body)

    def search_track(self, song, artist):
        for q in (f'track:"{song}" artist:"{artist}"', f"{song} {artist}"):
            _, j = self.call("GET", "/search?" + urllib.parse.urlencode({"q": q, "type": "track", "limit": 10}))
            uri = pick_track(j.get("tracks", {}).get("items", []), song, artist)
            if uri:
                return uri
        return None

    def create_playlist(self, name, desc):
        _, j = self.call("POST", "/me/playlists", {"name": name, "public": False, "description": desc})
        return j["id"]

    def update_details(self, pid, name, desc):
        return self.call("PUT", f"/playlists/{pid}", {"name": name, "description": desc})[0] != 404

    def replace_items(self, pid, uris):
        for kind in ("items", "tracks"):  # /items is current; /tracks is the older name
            status, _ = self.call("PUT", f"/playlists/{pid}/{kind}", {"uris": uris[:100]})
            if status == 404:
                continue
            for i in range(100, len(uris), 100):
                self.call("POST", f"/playlists/{pid}/{kind}", {"uris": uris[i:i + 100]})
            return True
        return False


# ---------- sync ----------
def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"shows": {}, "tracks": {}, "playlists": {}}

def save_state(st):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1, ensure_ascii=False, sort_keys=True)
        f.write("\n")

def fetch_setlists(shows, state, sfm):
    for show in shows:
        entry = state["shows"].get(show["key"])
        if not needs_check(entry, show["start"]):
            continue
        dates = show_dates(show["start"], show["end"])
        if sfm.calls + len(show["bands"]) * len(dates) > MAX_SETLIST_CALLS:
            print(f"setlist.fm budget reached ({sfm.calls} calls); the rest continue next run.")
            return
        sets = []
        for band in show["bands"]:
            best = None
            for d in dates:
                best = pick_setlist(sfm.search(band, d), band, dates)
                if best:
                    break
            if best:
                sets.append({"artist": band, "setlist_id": best["id"], "url": best.get("url"),
                             "songs": songs_from_setlist(best)})
        state["shows"][show["key"]] = {"date": show["start"].isoformat(), "sets": sets,
                                      "checked": TODAY.isoformat()}
        print(f"{show['start']} {' / '.join(show['bands'])}: {sum(len(s['songs']) for s in sets)} songs")

def match_tracks(state, sp):
    searched = 0
    for entry in state["shows"].values():
        for st in entry.get("sets", []):
            for song in st.get("songs", []):
                k = track_key(song)
                if k in state["tracks"]:
                    continue
                if searched >= MAX_SPOTIFY_SEARCHES:
                    print("Spotify search budget reached; the rest continue next run.")
                    return
                searched += 1
                uri = sp.search_track(song["name"], song["artist"])
                if not uri and song.get("cover"):
                    uri = sp.search_track(song["name"], song["cover"])
                state["tracks"][k] = uri

def sync_playlist(sp, state, key, name, desc, uris):
    pl = state["playlists"].get(key, {})
    h = digest(name + desc, uris)
    if pl.get("hash") == h:
        return
    pid = pl.get("id")
    if not pid or not sp.update_details(pid, name, desc):
        pid = sp.create_playlist(name, desc)
    sp.replace_items(pid, uris)
    state["playlists"][key] = {"id": pid, "hash": h}
    print(f"playlist ✓ {name} ({len(uris)} tracks)")

def build_playlists(shows, state, sp):
    master = []
    for show in shows:  # oldest first, so creation order is chronological too
        entry = state["shows"].get(show["key"])
        if not entry:
            continue
        uris = show_uris(entry, state["tracks"])
        if not uris:
            continue
        links = " ".join(s["url"] for s in entry["sets"] if s.get("url"))
        sync_playlist(sp, state, show["key"], playlist_name(show), f"Setlist via setlist.fm. {links}"[:300], uris)
        master += uris
    if master:
        sync_playlist(sp, state, "__master__", MASTER_NAME,
                      "Every show's setlist, oldest first. Auto-updated daily.", master[:10000])

def main():
    dry = "--dry-run" in sys.argv
    need = ["SETLISTFM_API_KEY", "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REFRESH_TOKEN"]
    missing = [n for n in need if not os.environ.get(n)]
    if missing:
        print(f"::warning::Missing secrets: {', '.join(missing)}. Skipping setlist sync.")
        return 0
    shows, state = load_shows(), load_state()
    try:
        fetch_setlists(shows, state, SetlistFM(os.environ["SETLISTFM_API_KEY"]))
        if dry:
            return 0
        sp = Spotify(os.environ["SPOTIFY_CLIENT_ID"], os.environ["SPOTIFY_CLIENT_SECRET"],
                     os.environ["SPOTIFY_REFRESH_TOKEN"])
        match_tracks(state, sp)
        build_playlists(shows, state, sp)
    finally:
        if not dry:
            save_state(state)  # keep partial progress even if a later step fails
    return 0

if __name__ == "__main__":
    sys.exit(main())
