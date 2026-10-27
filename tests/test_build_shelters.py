"""Offline tests for the shelter layer: python3 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_shelters as bs  # noqa: E402

GOV = "https://www.mauicounty.gov/CivicAlerts.aspx?AID=1"
NEWS = "https://www.hawaiinewsnow.com/x"


def school(name, lon, lat):
    return {"type": "Feature", "properties": {"sch_name": name},
            "geometry": {"type": "Point", "coordinates": [lon, lat]}}


SCHOOLS = [
    school("Baldwin High", -156.49, 20.89),            # Maui
    school("Kapaa Middle", -159.34, 22.08),            # Kauai
    school("Nanakuli Elementary", -158.15, 21.38),     # Oahu
    school("Nanakuli High & Intermediate", -158.16, 21.39),
    school("Kauai High", -156.50, 20.88),              # wrong county on purpose
]


def row(county, name, event, date, url, site_type="county_shelter", pets="unknown"):
    return {"county": county, "name": name, "address": "", "site_type": site_type,
            "event": event, "source_date": date, "pets": pets, "notes": "",
            "source_url": url}


class Shelters(unittest.TestCase):
    def setUp(self):
        self.rows = [
            row("Maui", "Baldwin High School", "Lala", "2026-08-15", GOV, pets="crated only"),
            row("Maui", "Lahaina Civic Center Gym", "Lala", "2026-08-15", GOV),
            row("Maui", "Lahaina Civic Center Gym", "Nolo", "2026-09-25", NEWS,
                site_type="temporary_evacuation_point"),
            row("Kauai", "Kapaʻa Middle School", "Lowell", "2026-09-07", NEWS,
                site_type="refuge_area"),
            row("Kauai", "Kauaʻi High School Gym", "Lowell", "2026-09-07", NEWS,
                site_type="refuge_area"),
            row("Honolulu", "Nānākuli Elementary School", "Lowell", "2026-09-07", NEWS),
            row("Honolulu", "Nānākuli High and Intermediate School", "April", "2026-04-09",
                "https://www.honolulu.gov/mayor/x"),
        ]
        self.fc = bs.build(self.rows, SCHOOLS)
        self.by = {f["properties"]["name"]: f["properties"] for f in self.fc["features"]}

    def test_grouping_counts_events(self):
        self.assertEqual(len(self.fc["features"]), 6)
        lahaina = self.by["Lahaina Civic Center Gym"]
        self.assertEqual(lahaina["times_opened_2026"], 2)
        self.assertEqual(lahaina["last_opened"], "2026-09-25")
        self.assertEqual(lahaina["site_type"], "county_shelter/temporary_evacuation_point")

    def test_school_matching_with_okina_and_county_check(self):
        self.assertEqual(self.by["Baldwin High School"]["location_method"], "doe_school_match")
        self.assertFalse(self.by["Kapaʻa Middle School"]["needs_geocode"])
        # "Kauai High" sits on Maui in the fixture -> must NOT match
        self.assertTrue(self.by["Kauaʻi High School Gym"]["needs_geocode"])
        # park/civic sites are not schools
        self.assertTrue(self.by["Lahaina Civic Center Gym"]["needs_geocode"])

    def test_longest_match_wins(self):
        f = next(f for f in self.fc["features"]
                 if f["properties"]["name"] == "Nānākuli High and Intermediate School")
        self.assertEqual(f["geometry"]["coordinates"], [-158.16, 21.39])
        g = next(f for f in self.fc["features"]
                 if f["properties"]["name"] == "Nānākuli Elementary School")
        self.assertEqual(g["geometry"]["coordinates"], [-158.15, 21.38])

    def test_source_flags(self):
        self.assertTrue(self.by["Baldwin High School"]["official_source"])
        self.assertFalse(self.by["Kapaʻa Middle School"]["official_source"])
        self.assertTrue(self.by["Nānākuli High and Intermediate School"]["official_source"])
        for p in self.by.values():
            self.assertTrue(p["sources"])
            self.assertIsNone(p["capacity"])   # never invented

    def test_summary(self):
        s = bs.summary(self.fc)
        self.assertEqual(s["Maui"]["sites"], 2)
        self.assertEqual(s["Kauai"]["needs_geocode"], 1)
        self.assertEqual(s["Kauai"]["media_only"], 2)

    def test_real_source_table_parses(self):
        rows = bs.load_activations()
        self.assertGreater(len(rows), 20)
        for r in rows:
            self.assertIn(r["county"], ("Maui", "Kauai", "Honolulu", "Hawaii"))
            self.assertTrue(r["source_url"].startswith("https://"))
            self.assertRegex(r["source_date"], r"^2026-\d\d-\d\d$")


if __name__ == "__main__":
    unittest.main()
