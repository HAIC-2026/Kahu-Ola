"""Offline tests for the MODEL step."""
import copy
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
                  tsunami_extreme_exposed_pop_est=800, nri_wildfire_score=90.0),
            tract("15009000200", "Maui", nri_coastal_flood_score=0.0),
            tract("15001000100", "Hawaii", nri_inland_flood_score=95.0),
        ]
        self.shelters = [
            site("Lahaina Civic Center Gym", "Maui", in_tsunami_zone=True),
            site("Baldwin High School", "Maui", in_tsunami_zone=False),
            site("Flood Gym", "Hawaii", in_tsunami_zone=False, tract_fips="15001000100"),
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
        self.assertEqual(s["toilets_72h"], 1)
        self.assertEqual(s["toilets_2wk"], 2)
        self.assertEqual(s["at_risk_pop_extreme_zone"], 800)
        self.assertEqual(s["power_outlets"], 1)
        self.assertGreaterEqual(s["staff_per_shift"], 7)       # min 1 per role

    def test_flood_sites_flagged_and_rating_footprint(self):
        s = self.by[("Hawaii", "inland_flood")]
        self.assertEqual(s["tracts_at_risk"], 1)
        self.assertEqual(s["known_sites_check_flood"], 1)
        self.assertEqual(s["known_sites_usable"], 0)

    def test_top_share_is_hawaii_relative(self):
        cfg = copy.deepcopy(CFG)                               # old statewide rule stays available
        for hz in ("wildfire", "coastal_flood"):
            cfg["footprint"][hz] = {"rule": "nri_top_share", "share": 0.25}
        shares, rule = mn.footprint_shares(self.tracts, "wildfire", cfg)
        self.assertTrue(rule.startswith("top 25%"))
        self.assertEqual(list(shares), ["15009000100"])        # highest score only
        # zero scores never enter a footprint
        shares, _ = mn.footprint_shares(self.tracts, "coastal_flood", cfg)
        self.assertNotIn("15009000200", shares)

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
        obs = round(10000 * CFG["shelter_seeking_rate"]["wildfire"]["high"])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "e.csv"
            p.write_text("event,date,county,hazard,affected_population,affected_population_source,"
                         "observed_sheltered,observed_source,notes\n"
                         f"X,2023-08-11,Maui,wildfire,10000,s,{obs},s,Calibration event\n",
                         encoding="utf-8")
            b = mn.backtest(CFG, p)[0]
            self.assertEqual(b["model_high"], obs)
            self.assertEqual(b["error_high_pct"], 0.0)
            self.assertTrue(b["observed_within_band"])
            self.assertTrue(b["calibration_event"])

    def test_no_personal_fields(self):
        for r in self.tr:
            for banned in ("name", "address", "phone", "dob"):
                self.assertNotIn(banned, r)


class FinalFixes(unittest.TestCase):
    def test_wildfire_high_is_exact_lahaina_rate(self):
        self.assertEqual(CFG["shelter_seeking_rate"]["wildfire"]["high"], round(1418 / 12702, 3))

    def test_real_backtest_inside_band(self):
        b = mn.backtest(CFG)[0]
        self.assertEqual(b["observed"], 1418)
        self.assertTrue(b["observed_within_band"])
        self.assertEqual(b["model_high"], 1423)                # 12,702 * 0.112

    def test_by_county_rule_used_for_nri_hazards(self):
        for hz in ("wildfire", "inland_flood", "coastal_flood"):
            self.assertEqual(CFG["footprint"][hz]["rule"], "nri_top_share_by_county")

    def test_by_county_ranks_within_each_county(self):
        # Maui scores all beat Hawaii's; statewide top 25% would skip Hawaii entirely.
        ts = [tract(f"150090001{i:02d}", "Maui", nri_wildfire_score=90.0 + i) for i in range(4)]
        ts += [tract(f"150010001{i:02d}", "Hawaii", nri_wildfire_score=1.0 + i) for i in range(4)]
        ts.append(tract("15001000199", "Hawaii", nri_wildfire_score=0.0))
        shares, rule = mn.footprint_shares(ts, "wildfire", CFG)
        self.assertIn("each county", rule)
        # Maui 4 tracts -> ceil(1.0) = 1; Hawaii 5 tracts -> ceil(1.25) = 2
        self.assertEqual(sorted(shares), ["15001000102", "15001000103", "15009000103"])
        # the zero-score tract never enters
        self.assertNotIn("15001000199", shares)

    def test_statewide_rule_still_available(self):
        ts = [tract(f"150090001{i:02d}", "Maui", nri_wildfire_score=90.0 + i) for i in range(4)]
        ts += [tract(f"150010001{i:02d}", "Hawaii", nri_wildfire_score=1.0 + i) for i in range(4)]
        cfg = copy.deepcopy(CFG)
        cfg["footprint"]["wildfire"] = {"rule": "nri_top_share", "share": 0.25}
        shares, _ = mn.footprint_shares(ts, "wildfire", cfg)
        self.assertEqual(sorted(shares), ["15009000102", "15009000103"])

    def test_site_level_flood_check(self):
        fp = {"15001000100": 1.0}
        shelters = [
            site("In SFHA, tract out", "Hawaii", tract_fips="15001000999", in_sfha=True,
                 fld_zone="AE"),
            site("Zone X, tract in", "Hawaii", tract_fips="15001000100", in_sfha=False,
                 fld_zone="X"),
            site("No data, tract in", "Hawaii", tract_fips="15001000100"),
            site("No data, tract out", "Hawaii", tract_fips="15001000999", in_sfha=None),
        ]
        u = mn.usable_sites(shelters, [], "Hawaii", "inland_flood", fp)
        self.assertEqual(u["known_sites_usable"], 2)
        self.assertEqual(u["known_sites_check_flood"], 2)
        self.assertEqual(u["known_sites_check_tract_level"], 1)
        self.assertEqual(u["known_sites_flood_check"],
                         ["In SFHA, tract out [check]", "No data, tract in [check (tract-level)]"])
        # SFHA does not matter for non-flood hazards
        self.assertEqual(mn.usable_sites(shelters, [], "Hawaii", "hurricane", fp)
                         ["known_sites_usable"], 4)

    def test_candidate_schools_use_sfha(self):
        schools = [site("A", "Maui", in_sfha=True), site("B", "Maui", in_sfha=False),
                   site("C", "Maui", tract_fips="15009000100"),
                   site("D", "Maui", hazard_excluded=True, in_sfha=False)]
        fp = {"15009000100": 1.0}
        self.assertEqual(mn.usable_sites([], schools, "Maui", "coastal_flood", fp)
                         ["candidate_schools_usable"], 2)
        self.assertEqual(mn.usable_sites([], schools, "Maui", "tsunami", fp)
                         ["candidate_schools_usable"], 3)

    def test_avma_verified_second_url(self):
        for k in ("dog_owning_household_share", "cat_owning_household_share"):
            self.assertIn("avma.org", CFG["pets"][k]["url2"])


if __name__ == "__main__":
    unittest.main()
