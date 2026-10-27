"""Offline tests for the MODEL step."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import model_needs as mn  # noqa: E402

CFG = json.loads((ROOT / "config" / "planning_factors.json").read_text(encoding="utf-8"))


def tract(fips, county, **kw):
    t = {"tract_fips": fips, "county": county, "population": 1000, "households": 400,
         "C_limited_english": 100, "M_power_dependent_est": 20, "I_disability": 150,
         "I_age_65_plus": 200, "S_age_17_under": 250, "T_households_no_vehicle": 40,
         "multi_unit_10plus": 0, "tsunami_zone_share": 0.0}
    for hz in mn.HAZARDS:
        t[f"nri_{hz}_rating"] = "Relatively Low"
        t[f"nri_{hz}_score"] = 10.0
    t.update(kw)
    return t


def site(name, county, lon=-156.5, lat=20.9, **p):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"name": name, "county": county, **p}}


class Model(unittest.TestCase):
    def setUp(self):
        self.tracts = [
            tract("15009000100", "Maui", tsunami_zone_share=0.5,
                  nri_wildfire_rating="Very High"),
            tract("15009000200", "Maui"),
            tract("15001000100", "Hawaii", nri_inland_flood_rating="Relatively High"),
        ]
        self.shelters = [
            site("Lahaina Civic Center Gym", "Maui", in_tsunami_zone=True),
            site("Baldwin High School", "Maui", in_tsunami_zone=False),
            site("Flood Gym", "Hawaii", in_tsunami_zone=False,
                 nri_inland_flood_rating="Very High"),
        ]
        self.sc, self.tr = mn.run(self.tracts, self.shelters, [], CFG)
        self.by = {(s["county"], s["hazard"]): s for s in self.sc}

    def test_every_county_and_hazard(self):
        self.assertEqual(len(self.sc), 4 * 5)

    def test_hurricane_whole_county(self):
        s = self.by[("Maui", "hurricane")]
        self.assertEqual(s["tracts_at_risk"], 2)
        self.assertEqual(s["at_risk_pop"], 2000)
        self.assertEqual(s["shelter_demand_central"], 60)      # 3%
        self.assertEqual(s["shelter_demand_high"], 100)        # 5%

    def test_tsunami_uses_zone_share_and_excludes_sites(self):
        s = self.by[("Maui", "tsunami")]
        self.assertEqual(s["at_risk_pop"], 500)
        self.assertEqual(s["shelter_demand_central"], 25)      # 5% of 500
        self.assertEqual(s["known_sites_excluded"], "Lahaina Civic Center Gym")
        self.assertEqual(s["known_sites_usable"], 1)
        # hurricane keeps Lahaina usable
        self.assertEqual(self.by[("Maui", "hurricane")]["known_sites_usable"], 2)

    def test_cmist_and_resources(self):
        s = self.by[("Maui", "tsunami")]
        self.assertEqual(s["C_lep_at_risk"], 50)               # 10% of 500
        self.assertEqual(s["M_power_dependent_at_risk"], 10)
        self.assertEqual(s["T_no_vehicle_persons_at_risk"], 50)  # 40 hh * 0.5 * 2.5
        self.assertEqual(s["cots"], 25)
        self.assertEqual(s["floor_sqft_72h"], 500)
        self.assertEqual(s["water_gal_per_day"], 25)
        self.assertEqual(s["meals_per_day"], 50)
        self.assertEqual(s["toilets"], 2)
        self.assertEqual(s["power_outlets"], 1)
        self.assertGreaterEqual(s["staff_per_shift"], 7)       # min 1 per role

    def test_flood_sites_flagged_and_rating_footprint(self):
        s = self.by[("Hawaii", "inland_flood")]
        self.assertEqual(s["tracts_at_risk"], 1)
        self.assertEqual(s["known_sites_check_flood"], 1)
        self.assertEqual(s["known_sites_usable"], 0)

    def test_fallback_when_no_high_rating(self):
        shares, rule = mn.footprint_shares(self.tracts, "coastal_flood", CFG)
        self.assertTrue(rule.startswith("fallback"))
        self.assertEqual(len(shares), 1)                       # top 25% of 3 -> 1

    def test_no_demand_no_staff(self):
        s = self.by[("Kauai", "hurricane")]
        self.assertEqual(s["at_risk_pop"], 0)
        self.assertEqual(s["staff_per_shift"], 0)

    def test_every_factor_has_a_source(self):
        for hz, r in CFG["shelter_seeking_rate"].items():
            if hz.startswith("_"):
                continue
            self.assertTrue(r["source"])
            self.assertLessEqual(r["low"], r["central"])
            self.assertLessEqual(r["central"], r["high"])
        for k, v in CFG["per_person"].items():
            self.assertTrue(v["source"])

    def test_backtest(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "e.csv"
            p.write_text("event,date,county,hazard,affected_population,affected_population_source,"
                         "observed_sheltered,observed_source,notes\n"
                         "X,2023-08-11,Maui,wildfire,10000,s,1100,s,Calibration event\n",
                         encoding="utf-8")
            b = mn.backtest(CFG, p)[0]
            self.assertEqual(b["model_central"], 1100)
            self.assertEqual(b["error_central_pct"], 0.0)
            self.assertTrue(b["observed_within_band"])
            self.assertTrue(b["calibration_event"])

    def test_no_personal_fields(self):
        for r in self.tr:
            for banned in ("name", "address", "phone", "dob"):
                self.assertNotIn(banned, r)


if __name__ == "__main__":
    unittest.main()
