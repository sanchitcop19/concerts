import os, sys, unittest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import sync_setlists as s

SETLIST = {"id": "abc", "eventDate": "12-05-2019", "artist": {"name": "Russian Circles"},
           "sets": {"set": [{"song": [{"name": "Intro", "tape": True}, {"name": "Harper Lewis"},
                                      {"name": "Mladek"}]},
                            {"encore": 1, "song": [{"name": "Wonderwall", "cover": {"name": "Oasis"}}]}]}}


class Helpers(unittest.TestCase):
    def test_split_bands(self):
        self.assertEqual(s.split_bands("Tyler, The Creator / Lil Yachty / Paris Texas"),
                         ["Tyler, The Creator", "Lil Yachty", "Paris Texas"])

    def test_songs_skip_tape_keep_order_and_cover(self):
        songs = s.songs_from_setlist(SETLIST)
        self.assertEqual([x["name"] for x in songs], ["Harper Lewis", "Mladek", "Wonderwall"])
        self.assertEqual(songs[2]["cover"], "Oasis")

    def test_pick_setlist_filters_by_date(self):
        other = dict(SETLIST, id="x", eventDate="13-05-2019")
        self.assertEqual(s.pick_setlist([other, SETLIST], "Russian Circles", [date(2019, 5, 12)])["id"], "abc")
        self.assertIsNone(s.pick_setlist([other], "Russian Circles", [date(2019, 5, 12)]))

    def test_playlist_names_sort_chronologically(self):
        a = {"start": date(2019, 5, 12), "bands": ["B"], "venue": "V", "name": ""}
        b = {"start": date(2021, 1, 3), "bands": ["A"], "venue": "V", "name": ""}
        self.assertLess(s.playlist_name(a), s.playlist_name(b))
        self.assertTrue(s.playlist_name(a).startswith("2019-05-12 · B @ V"))
        long = dict(a, bands=["X" * 200])
        self.assertLessEqual(len(s.playlist_name(long)), 100)

    def test_pick_track(self):
        items = [{"uri": "u1", "name": "Mladek - Live", "artists": [{"name": "Someone Else"}]},
                 {"uri": "u2", "name": "Mládek (Remastered)", "artists": [{"name": "Russian Circles"}]}]
        self.assertEqual(s.pick_track(items, "Mladek", "Russian Circles"), "u2")
        self.assertIsNone(s.pick_track(items[:1], "Mladek", "Russian Circles"))

    def test_needs_check(self):
        t = date(2026, 11, 18)
        self.assertTrue(s.needs_check(None, date(2018, 1, 1), t))
        found = {"checked": "2026-11-10", "sets": [{"songs": [1]}]}
        self.assertFalse(s.needs_check(found, date(2020, 1, 1), t))       # old show, done
        self.assertTrue(s.needs_check(found, date(2026, 11, 9), t))       # recent: may be corrected
        missing = {"checked": "2026-11-17", "sets": []}
        self.assertFalse(s.needs_check(missing, date(2026, 11, 1), t))    # checked yesterday
        self.assertTrue(s.needs_check(dict(missing, checked="2026-11-10"), date(2026, 10, 1), t))

    def test_show_uris_in_set_order(self):
        entry = {"sets": [{"songs": s.songs_from_setlist(SETLIST)}]}
        tracks = {s.track_key(x): f"t{i}" for i, x in enumerate(entry["sets"][0]["songs"])}
        tracks[s.track_key(entry["sets"][0]["songs"][1])] = None
        self.assertEqual(s.show_uris(entry, tracks), ["t0", "t2"])

    def test_load_shows_only_past_sorted_ascending(self):
        shows = s.load_shows(os.path.join(os.path.dirname(__file__), "..", "data", "concerts.csv"))
        self.assertTrue(shows)
        self.assertEqual([x["start"] for x in shows], sorted(x["start"] for x in shows))
        self.assertTrue(all(x["start"] <= date.today() for x in shows))


if __name__ == "__main__":
    unittest.main()
