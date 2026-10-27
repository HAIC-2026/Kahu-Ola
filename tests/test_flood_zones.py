"""Offline tests for site-level FEMA flood zones: python3 -m unittest discover tests"""
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_shelters as bs  # noqa: E402
import fetch_data as fd  # noqa: E402
import fetch_flood_zones as ff  # noqa: E402

CACHE_CSV = (
    "site_key,lon,lat,fld_zone,in_sfha,source_url,queried_at\n"
    "shelter:Maui:Lahaina,-156.682052,20.884315,AE,True,u,t\n"
    "candidate:Maui:Upland,-156.500000,20.890000,X,False,u,t\n"
    "candidate:Hawaii:Offshore,-155.000000,19.000000,,,u,t\n"
)


def cache_file(d):
    p = Path(d) / "site_flood_zones.csv"
    p.write_text(CACHE_CSV, encoding="utf-8")
    return p


class Sfha(unittest.TestCase):
    def test_zone_rule(self):
        for z in ("A", "AE", "AO", "AH", "A99", "V", "VE", " ae "):
            self.assertTrue(ff.is_sfha(z), z)
        for z in ("X", "D", "OPEN WATER", "AREA NOT INCLUDED"):
            self.assertFalse(ff.is_sfha(z), z)
        self.assertIsNone(ff.is_sfha(""))
        self.assertIsNone(ff.is_sfha(None))

    def test_pick_most_hazardous(self):
        self.assertEqual(ff.pick_zone(["X", "AE", "VE"]), "VE")
        self.assertEqual(ff.pick_zone(["X", "AE"]), "AE")
        self.assertEqual(ff.pick_zone(["X", None, " "]), "X")
        self.assertEqual(ff.pick_zone([]), "")

    def test_layer_is_official_dfirm(self):
        self.assertTrue(ff.LAYER_URL.startswith("https://geodata.hawaii.gov/"))
        self.assertIn("Hazards/MapServer/6", ff.LAYER_URL)


class Query(unittest.TestCase):
    def test_point_query_and_retry_on_arcgis_error(self):
        answers = [{"error": {"code": 500}},
                   {"features": [{"attributes": {"fld_zone": "X"}},
                                 {"attributes": {"fld_zone": "AE"}}]}]
        calls = []

        def fake(url):
            calls.append(url)
            return answers[len(calls) - 1]

        zone, url = ff.query_point(-156.5, 20.9, fetch=fake, pause=0)
        self.assertEqual(zone, "AE")
        self.assertEqual(len(calls), 2)
        self.assertIn("geometryType=esriGeometryPoint", url)
        self.assertIn("-156.500000%2C20.900000", url)

    def test_gives_up_after_retries(self):
        with self.assertRaises(RuntimeError):
            ff.query_point(0, 0, fetch=lambda u: {"error": {}}, retries=2, pause=0)


class Cache(unittest.TestCase):
    def test_load_and_lookup(self):
        with tempfile.TemporaryDirectory() as d:
            c = ff.load_cache(cache_file(d))
        self.assertEqual(ff.lookup(c, -156.682052, 20.884315), {"fld_zone": "AE", "in_sfha": True})
        self.assertEqual(ff.lookup(c, -156.5, 20.89), {"fld_zone": "X", "in_sfha": False})
        # queried, no flood polygon -> unknown, not "safe"
        self.assertEqual(ff.lookup(c, -155.0, 19.0), {"fld_zone": None, "in_sfha": None})
        # never queried
        self.assertEqual(ff.lookup(c, -157.0, 21.0), {"fld_zone": None, "in_sfha": None})

    def test_missing_cache_is_empty(self):
        self.assertEqual(ff.load_cache(Path("/nonexistent/x.csv")), {})


class Builders(unittest.TestCase):
    def setUp(self):
        with tempfile.TemporaryDirectory() as d:
            self.cache = ff.load_cache(cache_file(d))

    def test_shelters_get_flood_fields(self):
        rows = [{"county": "Maui", "name": "Lahaina Civic Center Gym", "address": "1840 Hwy",
                 "site_type": "county_shelter", "event": "Lala", "source_date": "2026-08-15",
                 "pets": "unknown", "notes": "", "source_url": "https://www.mauicounty.gov/x"},
                {"county": "Maui", "name": "Unlocated Hall", "address": "9 Nowhere",
                 "site_type": "county_shelter", "event": "Lala", "source_date": "2026-08-15",
                 "pets": "unknown", "notes": "", "source_url": "https://www.mauicounty.gov/x"}]
        geocodes = {"1840 Hwy": (-156.682052, 20.884315, "manual")}
        fc = bs.build(rows, [], geocodes=geocodes, flood=self.cache)
        by = {f["properties"]["name"]: f["properties"] for f in fc["features"]}
        self.assertEqual(by["Lahaina Civic Center Gym"]["fld_zone"], "AE")
        self.assertTrue(by["Lahaina Civic Center Gym"]["in_sfha"])
        self.assertIsNone(by["Unlocated Hall"]["in_sfha"])
        self.assertEqual(bs.summary(fc)["Maui"]["in_sfha"], 1)

    def test_candidates_get_flood_fields(self):
        layers = {"schools": {"type": "FeatureCollection", "metadata": {"source": "s"},
                              "features": [{"type": "Feature",
                                            "properties": {"sch_name": "Upland"},
                                            "geometry": {"type": "Point",
                                                         "coordinates": [-156.5, 20.89]}}]},
                  "tsunami_zone": None, "tsunami_extreme": None, "fema_open_shelters": None}
        p = fd.build_candidates(layers, None, self.cache)["features"][0]["properties"]
        self.assertEqual(p["fld_zone"], "X")
        self.assertFalse(p["in_sfha"])
        # no cache -> unknown
        p = fd.build_candidates(layers)["features"][0]["properties"]
        self.assertIsNone(p["in_sfha"])

    def test_builds_never_call_the_network(self):
        with mock.patch.object(urllib.request, "urlopen",
                               side_effect=AssertionError("network call during build")):
            bs.build([], [], flood=self.cache)
            fd.build_candidates({"schools": None}, None, self.cache)
            ff.load_cache(Path("/nonexistent/x.csv"))


if __name__ == "__main__":
    unittest.main()
