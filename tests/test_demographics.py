"""Tests for scripts/build_demographics.py and its committed outputs (offline)."""
import csv
import json
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_demographics as bd  # noqa: E402

PLACES = list(csv.DictReader(open(bd.OUT_PLACES, encoding="utf-8")))
RACE = list(csv.DictReader(open(bd.OUT_RACE, encoding="utf-8")))
POP = list(csv.DictReader(open(bd.OUT_POP, encoding="utf-8")))
PL_2020 = {"Honolulu": 1016508, "Hawaii": 200629, "Maui": 164754, "Kauai": 73298,
           "Kalawao": 82}


class Names(unittest.TestCase):
    def test_norm_name(self):
        self.assertEqual(bd.norm_name("Kailua CDP (Hawaii County), Hawaii"), "kailua")
        self.assertEqual(bd.norm_name("Kapaʻa"), "kapaa")
        self.assertEqual(bd.norm_name("Haiku-Pauwela CDP, Hawaii"), "haiku pauwela")
        self.assertEqual(bd.name_county("Waimea CDP (Kauai County), Hawaii"), "Kauai")

    def test_duplicate_names_use_county(self):
        dbedt = [("Hawaii", "", 1), ("Hawaii", "Kailua", 1), ("Hawaii", "Waimea", 1),
                 ("Oahu", "", 1), ("Oahu", "Kailua", 1), ("Kauai", "", 1), ("Kauai", "Waimea", 1)]
        places = [{"geoid": "a", "name": "Kailua CDP (Hawaii County), Hawaii"},
                  {"geoid": "b", "name": "Kailua CDP (Honolulu County), Hawaii"},
                  {"geoid": "c", "name": "Waimea CDP (Kauai County), Hawaii"},
                  {"geoid": "d", "name": "Nowhere CDP, Hawaii"}]
        got, unassigned, unused = bd.assign_islands(places, dbedt)
        self.assertEqual(got["a"][0], "Hawaii")
        self.assertEqual(got["b"][0], "Oahu")
        self.assertEqual(got["c"][0], "Kauai")
        self.assertEqual(unassigned, ["Nowhere CDP, Hawaii"])
        self.assertEqual(unused, ["Hawaii: Waimea"])


class Communities(unittest.TestCase):
    def test_every_place_once_on_one_island(self):
        places = [r for r in PLACES if r["row_type"] == "place"]
        self.assertGreater(len(places), 150)
        self.assertEqual(len({r["geoid"] for r in places}), len(places))
        labels = {bd.ISLAND_LABEL[i]: c for i, c in bd.ISLAND_COUNTY.items()}
        for r in places:
            self.assertIn(r["island"], labels, r["place"])
            self.assertEqual(labels[r["island"]], r["county"], r["place"])
            self.assertTrue(r["dbedt_name"], r["place"])

    def test_sorted_largest_first(self):
        for island in {r["island"] for r in PLACES if r["row_type"] == "place"}:
            pops = [int(r["acs_2020_2024"]) for r in PLACES
                    if r["row_type"] == "place" and r["island"] == island]
            self.assertEqual(pops, sorted(pops, reverse=True), island)

    def test_outside_cdp_is_county_minus_places(self):
        for r in PLACES:
            if not r["row_type"].startswith("outside_cdp"):
                continue
            county = r["county"]
            places = [p for p in PLACES if p["row_type"] == "place" and p["county"] == county]
            pl_sum = sum(int(p["pl_2020"]) for p in places)
            self.assertEqual(int(r["pl_2020"]), PL_2020[county] - pl_sum, county)
            single = county in bd.SINGLE_ISLAND_COUNTIES
            self.assertEqual(r["row_type"], "outside_cdp" if single else "outside_cdp_county_level")
            if not single:
                self.assertIn("multi-island", r["note"])

    def test_every_island_has_a_total_row(self):
        totals = {r["island"] for r in PLACES if r["row_type"] == "island_total"}
        self.assertEqual(totals, set(bd.ISLAND_LABEL.values()))


class CountyTotals(unittest.TestCase):
    def test_2020_counts_match_pl(self):
        got = {r["county"]: int(r["pop_2020_census"]) for r in POP}
        for county, n in PL_2020.items():
            self.assertEqual(got[county], n, county)
        self.assertEqual(got["State"], sum(PL_2020.values()))

    def test_change_is_2025_minus_2020(self):
        for r in POP:
            self.assertEqual(int(r["change_2020_2025"]),
                             int(r["pop_2025_v2025"]) - int(r["pop_2020_census"]))

    def test_v2025_counties_sum_to_state(self):
        got = {r["county"]: int(r["pop_2025_v2025"]) for r in POP}
        self.assertEqual(sum(got[c] for c in bd.COUNTY_ORDER), got["State"])


class Race(unittest.TestCase):
    def test_broad_alone_groups_sum_to_total(self):
        for source in (bd.ACS_VINTAGE, bd.PEP_VINTAGE):
            for county in ("State",) + bd.COUNTY_ORDER:
                rows = [r for r in RACE if r["source"] == source and r["county"] == county
                        and r["group_type"] == "broad" and r["measure"] == "alone"]
                self.assertTrue(rows, (source, county))
                self.assertEqual(sum(int(r["count"]) for r in rows), int(rows[0]["county_total"]),
                                 (source, county))

    def test_every_group_has_alone_and_combination(self):
        for source in (bd.ACS_VINTAGE, "2020 Census"):
            for county in ("State",) + bd.COUNTY_ORDER:
                got = {(r["group"], r["measure"]) for r in RACE
                       if r["source"] == source and r["county"] == county}
                for g in bd.DETAILED:
                    self.assertIn((g, "alone"), got)
                    self.assertIn((g, "alone_or_in_combination"), got)

    def test_suppressed_cells_never_filled(self):
        supp = [r for r in RACE if r["status"] != "published"]
        self.assertTrue(supp)
        for r in supp:
            self.assertEqual((r["count"], r["moe_90"], r["pct_of_county"]), ("", "", ""), r)
        for r in RACE:
            if r["status"] == "published":
                self.assertNotEqual(r["count"], "", r)

    def test_native_hawaiian_2020_statewide(self):
        r = next(r for r in RACE if r["source"] == "2020 Census" and r["county"] == "State"
                 and r["group"] == "Native Hawaiian" and r["measure"] == "alone_or_in_combination")
        self.assertEqual(int(r["count"]), 317497)
        self.assertTrue(250000 < int(r["count"]) < 350000)

    def test_acs_rows_carry_moe(self):
        for r in RACE:
            if r["source"] == bd.ACS_VINTAGE and r["group_type"] == "detailed":
                self.assertNotEqual(r["moe_90"], "", r)

    def test_dhca_ids_and_labels(self):
        for r in RACE:
            if r["source"] == "2020 Census":
                self.assertEqual(r["table_id"], "DECENNIALDDHCA2020.T01001")
                self.assertRegex(r["variable"], r"POPGROUP=\d{4}")
                self.assertIn("&t=", r["source_url"])

    def test_multi_island_labels(self):
        for r in RACE:
            if r["county"] in ("Maui", "Kauai"):
                self.assertIn("multi-island", r["area_label"])


class Provenance(unittest.TestCase):
    def test_every_row_has_table_url_vintage(self):
        for path, rows, tid, url in ((bd.OUT_RACE, RACE, "table_id", "source_url"),
                                     (bd.OUT_PLACES, PLACES, "table_ids", "source_urls"),
                                     (bd.OUT_POP, POP, "table_ids", "source_urls")):
            for r in rows:
                self.assertTrue(r[tid], (path.name, r))
                self.assertTrue(r["vintage"], (path.name, r))
                urls = [u.strip() for u in r[url].split(" ; ")]
                self.assertTrue(urls and all(u.startswith("https://") for u in urls),
                                (path.name, r))

    def test_no_microdata_sources(self):
        for rows in (RACE, PLACES, POP):
            for r in rows:
                blob = " ".join(str(v) for v in r.values()).lower()
                self.assertNotIn("pums", blob)


class EmptyTable(unittest.TestCase):
    def test_no_content_response_means_no_rows(self):
        with tempfile.TemporaryDirectory() as d:
            old = bd.RAW
            bd.RAW = Path(d)
            try:
                (bd.RAW / "x.json").write_text(json.dumps(
                    {"response": {"data": [], "dataAPIURI": "", "no_content": True}}))
                self.assertEqual(bd.dc_rows("x.json"), ([], ""))
            finally:
                bd.RAW = old

    def test_negative_sentinels_are_missing(self):
        self.assertIsNone(bd.num("-555555555"))
        self.assertIsNone(bd.num(None))
        self.assertEqual(bd.num("12"), 12.0)


if __name__ == "__main__":
    unittest.main()
