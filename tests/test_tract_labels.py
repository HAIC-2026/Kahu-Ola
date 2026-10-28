"""Tests for readable tract labels (scripts/build_tract_labels.py) and where they are used."""
import csv
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_tract_labels as tl  # noqa: E402

LABELS = tl.load_labels()
AFN = json.loads((ROOT / "data" / "processed" / "afn_tracts.geojson").read_text(encoding="utf-8"))
ISLANDS = {"Oʻahu", "Hawaiʻi Island", "Maui", "Molokaʻi", "Lānaʻi", "Kauaʻi", "Niʻihau",
           "Kahoʻolawe", "Northwestern Hawaiian Islands"}


def square(x0, y0, x1, y1):
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


class Format(unittest.TestCase):
    def test_tract_number(self):
        self.assertEqual(tl.tract_number("15009030800"), "308")
        self.assertEqual(tl.tract_number("15009030903"), "309.03")
        self.assertEqual(tl.tract_number("15003000106"), "1.06")
        self.assertEqual(tl.tract_number("15003981200"), "9812")

    def test_label(self):
        self.assertEqual(tl.tract_label("15009030800", "Kihei"), "Tract 308 · Kihei")
        self.assertEqual(tl.tract_label("15009030903", "near Wailuku"), "Tract 309.03 · near Wailuku")

    def test_committed_labels_match_format(self):
        for fips, r in LABELS.items():
            self.assertEqual(r["tract_label"], f"Tract {tl.tract_number(fips)} · {r['community']}")


class Join(unittest.TestCase):
    """Synthetic CDPs ~1.1 km apart per 0.01 degree."""
    CDPS = {"features": [
        {"properties": {"GEOID": "1500001", "BASENAME": "Alpha"}, "geometry": square(0, 0, 0.1, 0.1)},
        {"properties": {"GEOID": "1500002", "BASENAME": "Beta"}, "geometry": square(1, 0, 1.1, 0.1)}]}
    ISL = {"1500001": ("Maui", "Maui"), "1500002": ("Maui", "Maui")}

    def tract(self, fips, x, y):
        return {"properties": {"tract_fips": fips, "county": "Maui"},
                "geometry": square(x - 0.001, y - 0.001, x + 0.001, y + 0.001)}

    def test_overlap_near_rural(self):
        afn = {"features": [self.tract("15009000100", 0.05, 0.05),     # inside Alpha
                            self.tract("15009000200", 0.13, 0.05),     # ~3.3 km east of Alpha
                            self.tract("15009000300", 0.5, 0.05)]}     # ~44 km from both
        rows = {r["tract_fips"]: r for r in tl.build(afn, self.CDPS, self.ISL)}
        self.assertEqual(rows["15009000100"]["community"], "Alpha")
        self.assertEqual(rows["15009000100"]["method"], "overlap")
        self.assertEqual(rows["15009000200"]["community"], "near Alpha")
        self.assertEqual(rows["15009000300"]["community"], "rural Maui")
        self.assertEqual(rows["15009000300"]["tract_label"], "Tract 3 · rural Maui")

    def tract_box(self, fips, x0, x1):
        return {"properties": {"tract_fips": fips, "county": "Maui"},
                "geometry": square(x0, 0.0, x1, 0.1)}

    def test_two_cdps_largest_first(self):
        afn = {"features": [self.tract_box("15009000400", 0.04, 0.19)]}   # Alpha 0.06/0.15 = 40%
        r = tl.build(afn, self.CDPS, self.ISL)[0]
        self.assertEqual(r["community"], "Alpha")                         # one CDP >= 20%
        cdps = {"features": self.CDPS["features"] + [
            {"properties": {"GEOID": "1500003", "BASENAME": "Gamma"},
             "geometry": square(0.1, 0, 0.2, 0.1)}]}
        isl = {**self.ISL, "1500003": ("Maui", "Maui")}
        r = tl.build({"features": [self.tract_box("15009000500", 0.04, 0.2)]}, cdps, isl)[0]
        self.assertEqual(r["community"], "Gamma / Alpha")                 # 62% / 38%
        self.assertEqual(r["method"], "overlap_2")
        r = tl.build({"features": [self.tract_box("15009000600", 0.09, 0.8)]}, cdps, isl)[0]
        self.assertEqual(r["community"], "near Gamma")                    # Gamma 14%, Alpha 1%
        self.assertEqual(r["method"], "near")

    def test_remote_islands(self):
        self.assertEqual(tl.remote_island("Kauai", -160.15, 21.9), "Niʻihau")
        self.assertEqual(tl.remote_island("Maui", -156.6, 20.55), "Kahoʻolawe")
        self.assertEqual(tl.remote_island("Honolulu", -171.7, 25.8), "Northwestern Hawaiian Islands")
        self.assertEqual(tl.remote_island("Kauai", -159.5, 22.0), "")


class Committed(unittest.TestCase):
    def test_every_tract_has_community_and_island(self):
        fips = {f["properties"]["tract_fips"] for f in AFN["features"]}
        self.assertEqual(set(LABELS), fips)
        for r in LABELS.values():
            self.assertTrue(r["community"], r)
            self.assertIn(r["island"], ISLANDS, r)
            self.assertIn(r["method"], ("overlap", "overlap_2", "near", "rural"))
            if r["method"] == "overlap_2":
                self.assertEqual(r["community"].count(" / "), 1)
            if r["method"] == "near":
                self.assertLessEqual(float(r["distance_km"]), tl.NEAR_KM)
                self.assertTrue(r["community"].startswith("near "))
            if r["method"] == "rural":
                self.assertTrue(r["community"].startswith("rural "))
            self.assertTrue(r["source_url"].startswith("https://tigerweb.geo.census.gov/"))

    def test_spot_checks_against_tigerweb(self):
        # Checked 2026-10-27: TIGERweb tigerWMS_Census2020 layer 28 CDPs intersecting each
        # tract's TIGERweb polygon (layer 6) include every CDP named here.
        self.assertEqual(LABELS["15009030903"]["tract_label"], "Tract 309.03 · Waihee-Waiehu / Wailuku")
        self.assertEqual(LABELS["15009031001"]["tract_label"], "Tract 310.01 · Wailuku")
        self.assertEqual(LABELS["15009030800"]["tract_label"], "Tract 308 · Waikapu")
        self.assertEqual(LABELS["15009980000"]["island"], "Kahoʻolawe")


class Used(unittest.TestCase):
    def test_needs_by_tract_keeps_fips_and_adds_label(self):
        with open(ROOT / "data" / "processed" / "needs_by_tract.csv", newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertIn("tract_fips", rows[0])
        for r in rows:
            self.assertEqual(r["tract_label"], LABELS[r["tract_fips"]]["tract_label"])
            self.assertTrue(r["island"])

    def test_playbooks_show_labels_and_hurricane_note(self):
        note = "Hurricanes affect the whole county, so these are simply the most populous at-risk tracts."
        for path in (ROOT / "playbooks").glob("*.html"):
            if path.name == "index.html":
                continue
            html = path.read_text(encoding="utf-8")
            self.assertIn("Tract ", html)
            self.assertIn("<title>Tract ", html)               # map tooltips
            self.assertEqual(note in html, path.stem.endswith("_hurricane"), path.name)

    def test_app_bundle_has_labels(self):
        b = json.loads((ROOT / "app" / "data" / "bundle.json").read_text(encoding="utf-8"))
        self.assertTrue(all(t["l"].startswith("Tract ") for t in b["tracts"]))
        sc = next(iter(b["scenarios"].values()))
        self.assertTrue(sc["largest"][0]["tract_label"].startswith("Tract "))
        self.assertTrue(sc["priority_tracts"][0]["tract_label"].startswith("Tract "))
        self.assertIn("Hurricanes affect the whole county", b["meta"]["hurricane_scope_note"])


if __name__ == "__main__":
    unittest.main()
