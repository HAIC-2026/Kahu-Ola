"""Offline tests for the MAP step: python3 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_map as bm  # noqa: E402


def box(x0, y0, x1, y1):
    return {"type": "Polygon",
            "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def fc(features, label="t"):
    return {"type": "FeatureCollection", "features": features,
            "metadata": {"source": label, "source_url": "https://example", "fetched_at": "x"}}


def tract(fips, geom, **over):
    p = {"FIPS": fips, "LOCATION": f"Tract {fips}", "E_TOTPOP": 1000, "E_HH": 400,
         "RPL_THEMES": 0.5, "E_LIMENG": 50, "E_UNINSUR": 30, "E_DISABL": 120,
         "E_AGE65": 200, "E_AGE17": 220, "E_GROUPQ": 0, "E_NOVEH": 20,
         "E_MUNIT": 10, "E_MOBILE": 0}
    p.update(over)
    return {"type": "Feature", "properties": p, "geometry": geom}


class BuildMap(unittest.TestCase):
    def setUp(self):
        # Two Maui tracts (coastal + upland), one Honolulu tract
        self.svi = fc([
            tract("15009031400", box(-156.70, 20.80, -156.60, 20.90),
                  E_LIMENG=300, E_AGE65=300),
            tract("15009030100", box(-156.50, 20.80, -156.40, 20.90), E_DISABL=-999),
            tract("15003000100", box(-157.90, 21.30, -157.80, 21.40)),
        ])
        # NRI v1.20 per-hazard layers (uppercase fields, 2020 tracts)
        self.nri = {
            "wildfire": fc([{"type": "Feature",
                             "properties": {"TRACTFIPS": "15009031400", "WFIR_RISKR": "Very High",
                                            "WFIR_RISKS": 99.1, "NRI_VER": "December 2025"},
                             "geometry": box(-156.70, 20.80, -156.60, 20.90)},
                            # tract id not in SVI: Honolulu tract must match spatially
                            {"type": "Feature",
                             "properties": {"TRACTFIPS": "15003999999", "WFIR_RISKR": "Low"},
                             "geometry": box(-158.0, 21.2, -157.7, 21.5)}]),
            "tsunami": fc([{"type": "Feature",
                            "properties": {"TRACTFIPS": "15009031400", "TSUN_RISKR": "High"},
                            "geometry": box(-156.70, 20.80, -156.60, 20.90)}]),
            "hurricane": fc([{"type": "Feature",
                              "properties": {"TRACTFIPS": "15003999999",
                                             "HRCN_RISKR": "Moderate"},
                              "geometry": box(-158.0, 21.2, -157.7, 21.5)}]),
            "inland_flood": None,
        }
        # tsunami zone covers the western half of the coastal tract
        self.tsunami = fc([{"type": "Feature", "properties": {},
                            "geometry": box(-156.75, 20.75, -156.65, 20.95)}])
        self.empower = fc([{"type": "Feature", "geometry": None,
                            "properties": {"FIPS_Code": "15009", "State_FIPS_Code": "15",
                                           "Medicare_Benes": 30000,
                                           "Power_Dependent_Devices_DME": 500,
                                           "Any_Healthcare_Srvc_Any_DME": 9999}}])

    def test_layer(self):
        out = bm.build(self.svi, self.nri, self.tsunami, None, self.empower, samples=100)
        p = {f["properties"]["tract_fips"]: f["properties"] for f in out["features"]}
        self.assertEqual(len(p), 3)

        coastal = p["15009031400"]
        self.assertEqual(coastal["county"], "Maui")
        self.assertEqual(coastal["nri_wildfire_rating"], "Very High")
        self.assertEqual(coastal["nri_match"], "fips")
        self.assertEqual(coastal["nri_tsunami_rating"], "High")
        self.assertEqual(coastal["nri_version"], "December 2025")
        self.assertEqual(coastal["nri_inland_flood_rating"], "")
        self.assertAlmostEqual(coastal["tsunami_zone_share"], 0.5, delta=0.06)
        self.assertAlmostEqual(coastal["tsunami_exposed_pop_est"], 500, delta=60)
        self.assertGreaterEqual(coastal["tsunami_extreme_exposed_pop_est"],
                                coastal["tsunami_exposed_pop_est"])

        # emPOWER 500 split by 65+ share: 300 / (300 + 200)
        self.assertEqual(out["metadata"]["method"]["empower_field_used"],
                         "Power_Dependent_Devices_DME")
        self.assertAlmostEqual(coastal["M_power_dependent_est"], 300.0)
        self.assertAlmostEqual(p["15009030100"]["M_power_dependent_est"], 200.0)
        self.assertIsNone(p["15003000100"]["M_power_dependent_est"])

        # SVI -999 becomes missing, not a negative count
        self.assertIsNone(p["15009030100"]["I_disability"])

        # Honolulu tract joins NRI spatially
        self.assertEqual(p["15003000100"]["nri_match"], "spatial")
        self.assertEqual(p["15003000100"]["nri_hurricane_rating"], "Moderate")

        # AFN index in [0, 1]; coastal tract (high LEP) ranks highest on C
        self.assertEqual(coastal["pctl_C"], 1.0)
        for v in p.values():
            self.assertTrue(0 <= v["afn_index"] <= 1)

    def test_coverage(self):
        out = bm.build(self.svi, self.nri, self.tsunami, None, self.empower, samples=64)
        cov = bm.coverage(out)
        self.assertEqual(cov["Maui"]["tracts"], 2)
        self.assertEqual(cov["Maui"]["coverage_pct"], 50.0)   # one tract missing E_DISABL
        self.assertEqual(cov["Honolulu"]["with_nri"], 1)
        self.assertEqual(cov["Kauai"]["tracts"], 0)

    def test_no_personal_fields(self):
        out = bm.build(self.svi, None, None, None, None, samples=16)
        keys = set(out["features"][0]["properties"])
        for banned in ("name", "address", "phone", "dob", "ssn"):
            self.assertNotIn(banned, keys)


if __name__ == "__main__":
    unittest.main()
