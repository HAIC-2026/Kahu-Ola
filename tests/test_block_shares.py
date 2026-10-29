"""Population-weighted in-zone shares (2020 Census blocks): shares between 0 and 1, block
population adds up to tract population, shares recomputed from blocks, labels follow the
method (people vs share of the area), backtest still marked calibration."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import block_shares  # noqa: E402
import build_playbooks as bp  # noqa: E402
import build_state_layers as bsl  # noqa: E402
from build_tract_labels import read_blocks  # noqa: E402
from geo import ZoneIndex  # noqa: E402
from test_map_detail import text  # noqa: E402

AFN = json.loads((ROOT / "data" / "processed" / "afn_tracts.geojson").read_text(encoding="utf-8"))
TRACTS = {f["properties"]["tract_fips"]: f["properties"] for f in AFN["features"]}
BLOCKS = block_shares.load()
STATE = bsl.load()
BUNDLE = json.loads((ROOT / "app" / "data" / "bundle.json").read_text(encoding="utf-8"))


@unittest.skipUnless(BLOCKS, "2020 block files not available")
class Blocks(unittest.TestCase):
    def test_block_population_adds_up_to_tract(self):
        official = read_blocks()["tract_pop"]                  # 2020 PL tract P1_001N
        for t, pop in BLOCKS["tract_pop"].items():
            self.assertEqual(pop, official[t], t)
        self.assertEqual(BLOCKS["missing_pop"], 0)
        self.assertTrue(all(p > 0 for rows in BLOCKS["blocks"].values() for _x, _y, p in rows))

    def test_shares_between_0_and_1(self):
        for f, p in TRACTS.items():
            for k in ("tsunami_zone_share", "tsunami_extreme_share"):
                self.assertTrue(0 <= p[k] <= 1, (f, k))
        for f, a in STATE["areas"].items():
            self.assertTrue(0 <= a["dam_share"] <= 1, f)
            self.assertTrue(0 <= a["siren_share"] <= 1, f)

    def test_tsunami_shares_recomputed_from_blocks(self):
        zone = ZoneIndex(json.loads((ROOT / "data" / "raw" / "tsunami_zone.geojson").read_text(encoding="utf-8")))
        checked = 0
        for f, rows in sorted(BLOCKS["blocks"].items())[::5]:
            if f not in TRACTS:
                continue
            total = sum(p for *_xy, p in rows)
            inside = sum(p for x, y, p in rows if zone.contains(x, y))
            self.assertAlmostEqual(TRACTS[f]["tsunami_zone_share"], inside / total, places=3, msg=f)
            self.assertEqual(TRACTS[f]["tsunami_exposed_pop_est"],
                             round((TRACTS[f]["population"] or 0) * TRACTS[f]["tsunami_zone_share"]), f)
            checked += 1
        self.assertGreater(checked, 50)

    def test_dam_shares_recomputed_from_blocks(self):
        dams = ZoneIndex(json.loads((bsl.RAW / "dams.geojson").read_text(encoding="utf-8")))
        for f, rows in sorted(BLOCKS["blocks"].items())[::7]:
            if f not in STATE["areas"]:
                continue
            total = sum(p for *_xy, p in rows)
            inside = sum(p for x, y, p in rows if dams.contains(x, y))
            self.assertAlmostEqual(STATE["areas"][f]["dam_share"], inside / total, places=3, msg=f)

    def test_share_unit(self):
        b = {"blocks": {"t": [(0.0, 0.0, 30), (5.0, 5.0, 70)]}}
        self.assertAlmostEqual(block_shares.share(b, "t", lambda x, y: x < 1), 0.3)
        self.assertIsNone(block_shares.share(b, "none", lambda x, y: True))
        self.assertIsNone(block_shares.share(None, "t", lambda x, y: True))

    def test_tigerweb_points_match_pl_population(self):
        if not block_shares.CACHE.exists():
            self.skipTest("TIGERweb cache not fetched")
        c = json.loads(block_shares.CACHE.read_text(encoding="utf-8"))["blocks"]
        pops = {g: p for g, p in read_blocks()["pop"].items() if p > 0}
        self.assertEqual(set(c), set(pops))
        self.assertTrue(all(c[g][2] == pops[g] for g in c))


class Labels(unittest.TestCase):
    def test_method_recorded_and_labels_say_people(self):
        method = AFN["metadata"]["method"]["share_method"]
        self.assertEqual(method, "population" if BLOCKS else "area")
        self.assertEqual(STATE["meta"]["share_method"], method)
        self.assertEqual(bp.SHARE_METHOD, method)
        self.assertEqual(BUNDLE["state"]["share_word"], block_shares.WORD[method])
        for p in sorted((ROOT / "playbooks").glob("*_*.html")):
            t = text(p.read_text(encoding="utf-8"))
            self.assertIn(bp.SHARE_SENTENCE, t, p.name)
            if method == "population":
                self.assertNotIn("grid points", t, p.name)
                self.assertNotIn("share of the area", t.lower(), p.name)

    def test_area_fallback_never_says_people(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "afn.geojson"
            path.write_text(json.dumps({"metadata": {"method": {"share_method": "area"}}}))
            self.assertEqual(bp.share_method(path), "area")
        self.assertNotIn("people", block_shares.WORD["area"])
        self.assertNotIn("people", bsl.LOW_RANGE_AREA)
        self.assertIn("share of the area", block_shares.METHOD["area"])
        self.assertNotIn("people", block_shares.METHOD["area"].replace("where people live", ""))

    def test_app_panel_uses_share_word(self):
        js = (ROOT / "app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("Share ${DATA.state.share_word} within rated siren range", js)


class Backtest(unittest.TestCase):
    def test_lahaina_still_calibration(self):
        rows = list(csv.DictReader(open(ROOT / "data" / "processed" / "backtest.csv", encoding="utf-8")))
        lah = next(r for r in rows if r["event"].startswith("Lahaina"))
        self.assertEqual(lah["calibration_event"], "True")
        t = text((ROOT / "playbooks" / "maui_wildfire.html").read_text(encoding="utf-8"))
        self.assertIn("calibration event, not validation", t)


if __name__ == "__main__":
    unittest.main()
