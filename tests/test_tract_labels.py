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
        self.assertEqual(tl.tract_label("15009030800", "Kīhei"), "Kīhei · Census area 308")
        self.assertEqual(tl.tract_label("15009030903", "near Wailuku"),
                         "near Wailuku · Census area 309.03")
        self.assertEqual(tl.census_area("15009030903"), "Census area 309.03")

    def test_committed_labels_match_format(self):
        for fips, r in LABELS.items():
            self.assertEqual(r["tract_label"], f"{r['community']} · Census area {tl.tract_number(fips)}")
            self.assertEqual((r["label_main"], r["label_sub"]),
                             (r["community"], f"Census area {tl.tract_number(fips)}"))


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
        self.assertEqual(rows["15009000100"]["method"], "area")
        self.assertEqual(rows["15009000200"]["community"], "near Alpha")
        self.assertEqual(rows["15009000300"]["community"], "rural Maui")
        self.assertEqual(rows["15009000300"]["tract_label"], "rural Maui · Census area 3")

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
        self.assertEqual(r["method"], "area_2")
        r = tl.build({"features": [self.tract_box("15009000600", 0.09, 0.8)]}, cdps, isl)[0]
        self.assertEqual(r["community"], "near Gamma")                    # Gamma 14%, Alpha 1%
        self.assertEqual(r["method"], "near")

    def test_remote_islands(self):
        self.assertEqual(tl.remote_island("Kauai", -160.15, 21.9), "Niʻihau")
        self.assertEqual(tl.remote_island("Maui", -156.6, 20.55), "Kahoʻolawe")
        self.assertEqual(tl.remote_island("Honolulu", -171.7, 25.8), "Northwestern Hawaiian Islands")
        self.assertEqual(tl.remote_island("Kauai", -159.5, 22.0), "")


class PopulationRule(unittest.TestCase):
    NAMES = {"00001": "Alpha", "00002": "Beta"}

    def label(self, alpha, beta, outside):
        return tl.population_label({"00001": alpha, "00002": beta, tl.OUTSIDE: outside},
                                   self.NAMES)

    def test_largest_cdp(self):
        self.assertEqual(self.label(80, 20, 0)[:2], ("Alpha", "pop"))

    def test_second_cdp_at_exactly_25_percent(self):
        self.assertEqual(self.label(75, 25, 0)[:2], ("Alpha / Beta", "pop_2"))
        self.assertEqual(self.label(7501, 2499, 0)[:2], ("Alpha", "pop"))

    def test_outside_majority_edge(self):
        self.assertEqual(self.label(50, 0, 50)[:2], ("Alpha", "pop"))         # exactly 50%: not rural
        self.assertEqual(self.label(4999, 0, 5001)[:2], ("rural near Alpha", "pop_rural"))
        self.assertEqual(self.label(0, 0, 10)[:2], ("rural", "pop_rural"))      # island added later

    def test_zero_population_falls_back(self):
        self.assertIsNone(self.label(0, 0, 0)[0])


POP = list(csv.DictReader(open(tl.OUT_POP, encoding="utf-8")))


class PopulationTable(unittest.TestCase):
    def test_shares_sum_to_one_per_tract(self):
        by = {}
        for r in POP:
            by.setdefault(r["tract_fips"], []).append(r)
        for tract, rows in by.items():
            total = int(rows[0]["tract_pop_2020"])
            self.assertEqual(sum(int(r["pop_2020"]) for r in rows), total, tract)
            if total:
                self.assertAlmostEqual(sum(float(r["share"]) for r in rows), 1.0, delta=0.002)

    def test_labels_use_the_same_totals(self):
        totals = {r["tract_fips"]: int(r["tract_pop_2020"]) for r in POP}
        for fips, r in LABELS.items():
            self.assertEqual(int(r["pop_2020"]), totals.get(fips, 0), fips)
            if int(r["pop_2020"]):
                s = float(r["pop_share_top"]) + float(r["pop_outside_cdp"])
                self.assertLessEqual(s, 1.0001)

    @unittest.skipUnless((tl.BLOCKS / "hi2020.pl.zip").exists(), "raw Census files not cached")
    def test_block_population_sums_to_pl_tract_total(self):
        b = tl.read_blocks()
        self.assertEqual(b["pop"], b["pop100"])                 # P1_001N == POP100 per block
        sums = {}
        for block, pop in b["pop"].items():
            sums[block[:11]] = sums.get(block[:11], 0) + pop
        self.assertEqual(sums, {k: v for k, v in b["tract_pop"].items()})
        self.assertEqual(sum(b["pop"].values()), 1455271)       # 2020 PL state total
        self.assertTrue(set(b["place"]) <= set(b["pop"]))       # every assigned block exists


class Committed(unittest.TestCase):
    def test_every_tract_has_community_and_island(self):
        fips = {f["properties"]["tract_fips"] for f in AFN["features"]}
        self.assertEqual(set(LABELS), fips)
        for r in LABELS.values():
            self.assertTrue(r["community"], r)
            self.assertIn(r["island"], ISLANDS, r)
            self.assertIn(r["method"], ("pop", "pop_2", "pop_near", "pop_rural",
                                        "area", "area_2", "near", "area_rural"))
            if r["method"] in ("pop_2", "area_2"):
                self.assertEqual(r["community"].count(" / "), 1)
            if r["method"] in ("near", "pop_near"):
                self.assertTrue(r["community"].startswith("near "))
            if r["method"] == "near":
                self.assertLessEqual(float(r["distance_km"]), tl.NEAR_KM)
                self.assertTrue(r["community"].startswith("near "))
            if r["method"] in ("pop_rural", "area_rural"):
                self.assertTrue(r["community"].startswith("rural "))
            if r["method"].startswith("pop"):
                self.assertGreater(int(r["pop_2020"]), 0)
                self.assertIn("BlockAssign_ST15_HI.zip", r["source_url"])
            else:                                        # area fallback only for 0 people
                self.assertEqual(int(r["pop_2020"]), 0, r["tract_label"])
                self.assertTrue(r["source_url"].startswith("https://tigerweb.geo.census.gov/"))

    def test_populated_tract_without_cdp_blocks_is_near_nearest_cdp(self):
        r = LABELS["15003007400"]
        self.assertEqual(r["tract_label"], "near Hālawa · Census area 74")
        self.assertEqual(r["method"], "pop_near")
        self.assertEqual(float(r["pop_outside_cdp"]), 1.0)
        for x in LABELS.values():
            if x["method"] == "pop_rural" and not x["community"].startswith("rural near "):
                self.assertTrue(x["area_label"].startswith("rural "), x["tract_label"])

    def test_no_guessed_reasons(self):
        for path in (tl.OUT, ROOT / "PLAN.md", ROOT / "README.md"):
            self.assertNotIn("military", path.read_text(encoding="utf-8").lower(), path.name)

    def test_pinned_maui_tracts(self):
        # 2020 block population by CDP (Block Assignment File + PL 94-171), reported 2026-10-27.
        self.assertEqual(LABELS["15009030800"]["tract_label"], "Waikapū / Waiheʻe-Waiehu · Census area 308")
        self.assertEqual(LABELS["15009030903"]["tract_label"], "Waiheʻe-Waiehu · Census area 309.03")
        self.assertEqual(LABELS["15009031001"]["tract_label"], "Wailuku · Census area 310.01")
        self.assertEqual(LABELS["15009030800"]["pop_2020"], "7413")
        self.assertEqual(LABELS["15009030800"]["pop_share_top"], "0.4636")
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
        note = "Hurricanes affect the whole county, so these are simply the most populous at-risk Census areas."
        for path in (ROOT / "playbooks").glob("*.html"):
            if path.name == "index.html":
                continue
            html = path.read_text(encoding="utf-8")
            self.assertIn("<small>Census area ", html)         # community first, ID second
            self.assertRegex(html, r"<title>[^<]+ · Census area [\d.]+</title>")   # map tooltips
            self.assertNotIn(">Tract ", html)
            self.assertEqual(note in html, path.stem.endswith("_hurricane"), path.name)

    def test_app_bundle_has_labels(self):
        b = json.loads((ROOT / "app" / "data" / "bundle.json").read_text(encoding="utf-8"))
        self.assertTrue(all(" · Census area " in t["l"] for t in b["tracts"]))
        sc = next(iter(b["scenarios"].values()))
        for row in (sc["largest"][0], sc["priority_tracts"][0]):
            self.assertTrue(row["label_sub"].startswith("Census area "))
            self.assertNotIn("Census area", row["label_main"])
        self.assertIn("Hurricanes affect the whole county", b["meta"]["hurricane_scope_note"])


if __name__ == "__main__":
    unittest.main()
