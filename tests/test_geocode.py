"""Offline tests for geocoding (network is mocked)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_shelters as bs  # noqa: E402
import geocode_shelters as gs  # noqa: E402


def fake_census(table):
    def fetch(url):
        for key, resp in table.items():
            if key in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp
        return {"result": {"addressMatches": []}}
    return fetch


def match(x, y, addr="MATCHED"):
    return {"result": {"addressMatches": [{"coordinates": {"x": x, "y": y},
                                           "matchedAddress": addr}]}}


class Geocode(unittest.TestCase):
    def test_query_strips_okina_and_adds_state(self):
        self.assertEqual(gs.to_query("45-660 Keaʻahala Road, Kāneʻohe 96744"),
                         "45-660 Keaahala Road, Kaneohe 96744, HI")
        self.assertEqual(gs.to_query("1 Main St, Hilo, HI"), "1 Main St, Hilo, HI")

    def test_run_statuses_and_cache(self):
        rows = [{"address": a} for a in
                ("1840 Honoapiʻilani Highway, Lahaina", "9 Nowhere Rd", "5 Far Away St",
                 "7 Broken Ln", "")]
        fetch = fake_census({
            "Honoapiilani": match(-156.678, 20.902, "1840 HONOAPIILANI HWY, LAHAINA, HI"),
            "Far+Away": match(-118.2, 34.0),            # mainland -> rejected
            "Broken": TimeoutError(),
        })
        cache = {}
        n = gs.run(rows, cache, fetch=fetch)
        self.assertEqual(n, 4)                          # blank address skipped
        self.assertEqual(cache["1840 Honoapiʻilani Highway, Lahaina"]["status"], "match")
        self.assertEqual(cache["9 Nowhere Rd"]["status"], "no_match")
        self.assertEqual(cache["5 Far Away St"]["status"], "outside_hawaii")
        self.assertTrue(cache["7 Broken Ln"]["status"].startswith("error"))
        # second run: nothing new; --retry re-queries only the misses
        self.assertEqual(gs.run(rows, cache, fetch=fetch), 0)
        self.assertEqual(gs.run(rows, cache, retry=True, fetch=fetch), 3)

        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "geocodes.csv"
            gs.save_cache(cache, p)
            usable = bs.load_geocodes(p)
            self.assertEqual(list(usable), ["1840 Honoapiʻilani Highway, Lahaina"])
            self.assertEqual(usable["1840 Honoapiʻilani Highway, Lahaina"][:2],
                             (-156.678, 20.902))


class BuildUsesGeocodes(unittest.TestCase):
    def test_geocode_fills_gap_school_match_wins(self):
        rows = [
            {"county": "Maui", "name": "Lahaina Civic Center Gym",
             "address": "1840 Honoapiʻilani Highway, Lahaina", "site_type": "county_shelter",
             "event": "Lala", "source_date": "2026-08-15", "pets": "", "notes": "",
             "source_url": "https://www.mauicounty.gov/x"},
            {"county": "Maui", "name": "Baldwin High School", "address": "1650 Kaahumanu Ave.",
             "site_type": "county_shelter", "event": "Lala", "source_date": "2026-08-15",
             "pets": "", "notes": "", "source_url": "https://www.mauicounty.gov/x"},
        ]
        schools = [{"type": "Feature", "properties": {"sch_name": "Baldwin High"},
                    "geometry": {"type": "Point", "coordinates": [-156.49, 20.89]}}]
        geocodes = {"1840 Honoapiʻilani Highway, Lahaina": (-156.678, 20.902, "census"),
                    "1650 Kaahumanu Ave.": (-156.0, 20.0, "census")}
        fc = bs.build(rows, schools, geocodes=geocodes)
        by = {f["properties"]["name"]: f for f in fc["features"]}
        lah = by["Lahaina Civic Center Gym"]
        self.assertEqual(lah["geometry"]["coordinates"], [-156.678, 20.902])
        self.assertEqual(lah["properties"]["location_method"], "census")
        self.assertFalse(lah["properties"]["needs_geocode"])
        bald = by["Baldwin High School"]
        self.assertEqual(bald["properties"]["location_method"], "doe_school_match")
        self.assertEqual(bald["geometry"]["coordinates"], [-156.49, 20.89])


if __name__ == "__main__":
    unittest.main()
