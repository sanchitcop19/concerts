"""Tests for the event database builder (scripts/build_events.py) and added shows (scripts/added_shows.py)."""
import json, os, sys, tempfile, unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import added_shows  # noqa: E402
import build_events as be  # noqa: E402


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def tm(id, name, day, venue="The Showbox", city="Seattle", acts=None, status="onsale", time="20:00"):
    return {"id": id, "name": name, "url": f"https://www.ticketmaster.com/event/{id}",
            "dates": {"start": {"localDate": day, "localTime": time + ":00"}, "status": {"code": status}},
            "_embedded": {"venues": [{"name": venue, "city": {"name": city}, "state": {"name": "Washington", "stateCode": "WA"},
                                      "country": {"countryCode": "US", "name": "United States Of America"}}],
                          "attractions": [{"name": a} for a in (acts or [])]}}


def setlist(artist, day, venue="The Showbox", vid="v1", tour=None):
    s = {"eventDate": day, "artist": {"name": artist}, "url": "https://www.setlist.fm/x",
         "venue": {"id": vid, "name": venue, "city": {"name": "Seattle", "state": "Washington", "country": {"code": "US", "name": "United States"}}}}
    if tour:
        s["tour"] = {"name": tour}
    return s


class TicketmasterEvents(unittest.TestCase):
    def test_compact_event(self):
        ev = be.tm_event(tm("A1", "Insomnium & Amorphis", "2026-12-02", acts=["Insomnium", "Amorphis"]))
        self.assertEqual(ev, {"id": "tm:A1", "d": "2026-12-02", "t": "20:00", "n": "Insomnium & Amorphis",
                              "a": ["Insomnium", "Amorphis"], "v": "The Showbox", "c": "Seattle", "s": "Washington",
                              "u": "https://www.ticketmaster.com/event/A1"})

    def test_single_act_named_like_the_event_is_left_out(self):
        self.assertNotIn("a", be.tm_event(tm("A2", "Yung Gravy", "2026-12-01", acts=["Yung Gravy"])))

    def test_age_note_is_not_an_act(self):
        self.assertEqual(be.tm_event(tm("A3", "Gwar (21 and Over)", "2026-12-01"))["a"], ["Gwar"])

    def test_disambiguation_suffix_is_dropped(self):
        ev = be.tm_event(tm("A5", "GWAR", "2026-12-01", acts=["GWAR", "Midnight - Band"]))
        self.assertEqual(ev["a"], ["GWAR", "Midnight"])

    def test_junk_and_cancelled_listings_are_skipped(self):
        self.assertIsNone(be.tm_event(tm("P", "Parking Pass - Not a Concert Ticket", "2026-12-01")))
        self.assertIsNone(be.tm_event(tm("V", "Artist VIP Upgrade", "2026-12-01")))
        self.assertIsNone(be.tm_event(tm("C", "Real Show", "2026-12-01", status="cancelled")))

    def test_country_outside_us(self):
        e = tm("T1", "Show", "2026-12-01")
        e["_embedded"]["venues"][0]["country"] = {"countryCode": "CA", "name": "Canada"}
        self.assertEqual(be.tm_event(e)["co"], "Canada")


class SetlistEvents(unittest.TestCase):
    def test_acts_at_one_venue_on_one_day_are_one_event(self):
        evs = be.sl_events([setlist("Russian Circles", "21-11-2025"), setlist("Primitive Man", "21-11-2025"),
                            setlist("Other", "22-11-2025")])
        self.assertEqual(len(evs), 2)
        rc = next(e for e in evs if e["d"] == "2025-11-21")
        self.assertEqual(rc["a"], ["Russian Circles", "Primitive Man"])
        self.assertEqual(rc["n"], "Russian Circles / Primitive Man")

    def test_festival_uses_its_name(self):
        evs = be.sl_events([setlist(a, "20-07-2025", venue="Seattle Center", vid="f", tour="Bumbershoot") for a in "ABCDE"])
        self.assertEqual(evs[0]["n"], "Bumbershoot")
        self.assertEqual(len(evs[0]["a"]), 5)

    def test_bad_dates_are_skipped(self):
        self.assertEqual(be.sl_events([setlist("X", "2025-11-21")]), [])

    def test_backfill_resumes_where_it_ran_out(self):
        class Fake(be.SetlistFM):
            def __init__(self, budget):
                super().__init__("k", budget)
                self.asked = []

            def page(self, **q):
                if self.calls >= self.budget:
                    raise be.OutOfBudget
                self.calls += 1
                self.asked.append((q.get("cityName"), q.get("year"), q.get("p"), q.get("lastUpdated")))
                return {"setlist": [setlist("A", "01-01-2025")], "total": 50, "itemsPerPage": 20}

        markets, today, state = [{"cities": ["Seattle"]}], date(2026, 1, 15), {}
        sfm = Fake(budget=2)
        be.sl_update(sfm, markets, state, today, log=lambda *_: None)
        self.assertEqual(state["cursor"], {"Seattle|2024": 3})  # 2 of 3 pages of the first year done
        self.assertNotIn("lastUpdated", state)
        sfm = Fake(budget=100)
        be.sl_update(sfm, markets, state, today, log=lambda *_: None)
        self.assertEqual(sfm.asked[0], ("Seattle", 2024, 3, None))
        self.assertEqual(state["done"], ["Seattle|2024", "Seattle|2025", "Seattle|2026"])
        self.assertIn("lastUpdated", state)
        sfm = Fake(budget=100)  # after the backfill, only changes are fetched
        be.sl_update(sfm, markets, state, today, log=lambda *_: None)
        self.assertTrue(all(a[3] for a in sfm.asked))


class Database(unittest.TestCase):
    def test_setlist_merges_into_ticketmaster_listing(self):
        t = be.tm_event(tm("T1", "Russian Circles", "2025-11-21", acts=["Russian Circles"]))
        s = be.sl_events([setlist("Russian Circles", "21-11-2025"), setlist("Primitive Man", "21-11-2025")])[0]
        out = be.dedupe({t["id"]: t, s["id"]: s})
        self.assertEqual(list(out), ["tm:T1"])
        self.assertEqual(out["tm:T1"]["a"], ["Russian Circles", "Primitive Man"])

    def test_two_different_shows_at_one_venue_stay_apart(self):
        a = be.tm_event(tm("E", "Early Show", "2026-12-01", acts=["Early Band"], time="18:00"))
        b = be.tm_event(tm("L", "Late Show", "2026-12-01", acts=["Late Band"], time="22:00"))
        self.assertEqual(len(be.dedupe({a["id"]: a, b["id"]: b})), 2)

    def test_duplicate_listings_collapse(self):
        a = be.tm_event(tm("A", "Gwar", "2026-12-01", acts=["Gwar"]))
        b = be.tm_event(tm("B", "Gwar (21 and Over)", "2026-12-01", venue="Showbox", acts=["Gwar"]))
        self.assertEqual(len(be.dedupe({a["id"]: a, b["id"]: b})), 1)

    def test_write_and_load_round_trip_by_month(self):
        evs = {e["id"]: e for e in [be.tm_event(tm("A", "One", "2026-12-01")), be.tm_event(tm("B", "Two", "2027-01-05"))]}
        with tempfile.TemporaryDirectory() as d:
            write(os.path.join(d, "2020-01.json"), '{"events":[]}')  # stale month is removed
            be.write_db(evs, {"x": 1}, out=d)
            self.assertEqual(sorted(os.listdir(d)), ["2026-12.json", "2027-01.json", "index.json"])
            got, index = be.load_db(out=d)
            self.assertEqual(got, evs)
            self.assertEqual(index["months"], {"2026-12": 1, "2027-01": 1})
            self.assertEqual(index["count"], 2)
            self.assertEqual(index["x"], 1)

    def test_window(self):
        self.assertEqual(be.window(date(2026, 11, 23)), (date(2024, 11, 1), date(2027, 11, 30)))


class Markets(unittest.TestCase):
    def test_nearby_cities_join_the_busiest_one(self):
        cities = [("Seattle", "Washington", "United States", 100), ("Chicago", "Illinois", "United States", 12),
                  ("Tacoma", "Washington", "United States", 9), ("Auburn", "Washington", "United States", 4),
                  ("Savannah", "Georgia", "United States", 2)]
        geo = {"Seattle": (47.61, -122.33), "Tacoma": (47.25, -122.44), "Auburn": (47.31, -122.23),
               "Chicago": (41.88, -87.63), "Savannah": (32.08, -81.09)}
        m = be.build_markets(cities, geo)
        self.assertEqual([x["name"] for x in m], ["Seattle", "Chicago"])  # Savannah has too few shows
        self.assertEqual(m[0]["cities"], ["Seattle", "Tacoma", "Auburn"])
        self.assertEqual(m[0]["shows"], 113)

    def test_history_cities_counts_recent_shows(self):
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as f:
            f.write("Start Date,Status,Bands Seen,Venue,Location,URL\n"
                    '11/21/2026,Past,A,V,"Seattle, Washington, United States",\n'
                    '01/01/2010,Past,B,V,"Chicago, Illinois, United States",\n')
        try:
            self.assertEqual(be.history_cities(f.name, today=date(2026, 11, 23)), [("Seattle", "Washington", "United States", 1)])
        finally:
            os.remove(f.name)

    def test_geohash(self):
        self.assertEqual(be.geohash(47.6062, -122.3321, 5), "c23nb")


class AddedShows(unittest.TestCase):
    CSV = ("Start Date,End Date,Nonstandard Concert Type,Status,Concert Name,Bands Seen,Bands Not Seen,Venue,Location,URL\n"
           '11/21/2026,,,Past,,Russian Circles / Primitive Man,,The Showbox,"Seattle, Washington, United States",https://ca/x/rc-1\n')

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.csv = os.path.join(self.dir.name, "concerts.csv")
        self.json = os.path.join(self.dir.name, "added.json")
        write(self.csv, self.CSV)
        write(self.json, json.dumps({"shows": [
            {"id": "a-dupe", "date": "2026-11-21", "bands": ["Primitive Man"], "venue": "Neumos"},
            {"id": "a-dupe-venue", "date": "2026-11-21", "bands": ["Someone Else"], "venue": "Showbox"},
            {"id": "a-new", "date": "2026-12-24", "bands": ["New Band", "Opener"], "venue": "Tractor Tavern",
             "city": "Seattle", "state": "Washington", "country": "United States", "start": "20:00"},
            {"id": "a-other-day", "date": "2026-11-22", "bands": ["Russian Circles"], "venue": "The Showbox"},
        ]}))

    def tearDown(self):
        self.dir.cleanup()

    def test_merge_adds_only_shows_not_already_on_concert_archives(self):
        out = os.path.join(self.dir.name, "all.csv")
        self.assertEqual(added_shows.merge(self.csv, self.json, out, today="2026-11-23"), 2)
        rows = added_shows.read_csv(out)
        self.assertEqual([r["ID"] for r in rows], ["", "a-new", "a-other-day"])
        new = rows[1]
        self.assertEqual((new["Start Date"], new["Status"], new["Bands Seen"], new["Location"]),
                         ("12/24/2026", "Upcoming", "New Band / Opener", "Seattle, Washington, United States"))
        self.assertEqual(rows[2]["Status"], "Past")

    def test_merged_csv_works_with_the_widget(self):
        import build_widget_json
        out, widget = os.path.join(self.dir.name, "all.csv"), os.path.join(self.dir.name, "w.json")
        added_shows.merge(self.csv, self.json, out, today="2026-11-23")
        build_widget_json.main(out, widget)
        with open(widget) as f:
            ids = [s["id"] for s in json.load(f)["upcoming"]]
        self.assertIn("a-new", ids)

    def test_prune_removes_shows_that_reached_concert_archives(self):
        gone = added_shows.prune(self.csv, self.json)
        self.assertEqual(sorted(s["id"] for s in gone), ["a-dupe", "a-dupe-venue"])
        self.assertEqual([s["id"] for s in added_shows.load(self.json)], ["a-new", "a-other-day"])
        self.assertEqual(added_shows.prune(self.csv, self.json), [])  # nothing more to do

    def test_missing_file_is_empty(self):
        self.assertEqual(added_shows.load(os.path.join(self.dir.name, "nope.json")), [])


if __name__ == "__main__":
    unittest.main()
