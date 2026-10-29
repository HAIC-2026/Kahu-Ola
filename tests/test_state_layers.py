"""Three public State layers (build time only): centre-based childcare only, siren counts,
dam evacuation zone shares, shelter sites in a dam zone, tables and sources in the app and
every PDF, panel numbers in the browser, bundle size."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import build_playbooks as bp  # noqa: E402
import build_state_layers as bsl  # noqa: E402
from geo import ZoneIndex  # noqa: E402
from test_map_detail import Serve, chrome, free_port, panel, text  # noqa: E402

APP = ROOT / "app"
S = bsl.load()
BUNDLE = json.loads((APP / "data" / "bundle.json").read_text(encoding="utf-8"))
TRACTS = {t["f"]: t for t in BUNDLE["tracts"]}
RAW = bsl.RAW
PLAYBOOKS = [p for p in sorted((ROOT / "playbooks").glob("*_*.html"))]


class Childcare(unittest.TestCase):
    def test_home_based_never_kept(self):
        for name in ("Smith Family Child Care Home", "Aunty Lei FCC", "Keiki In-Home Care",
                     "Home-based Daycare"):
            self.assertFalse(bsl.is_centre({"name": name, "site_type": "EOEL"}), name)
        self.assertFalse(bsl.is_centre({"name": "Hale Keiki", "site_type": None}))
        self.assertTrue(bsl.is_centre({"name": "Holy Family Catholic Academy",
                                       "site_type": "Licensed Group Child Care (Preschools) - PATCH"}))

    def test_output_is_centre_based_only(self):
        self.assertGreater(len(S["childcare"]), 400)
        for c in S["childcare"]:
            self.assertIn(c["kind"], bsl.CENTRE_TYPES.values(), c["name"])
            self.assertNotRegex(c["name"], bsl.HOME_BASED, c["name"])
            self.assertEqual(c["type_label"], "Childcare centre")
        if (RAW / "childcare.geojson").exists():
            raw = json.loads((RAW / "childcare.geojson").read_text(encoding="utf-8"))["features"]
            kept = sum(1 for f in raw if bsl.is_centre(f["properties"]))
            self.assertEqual(kept, len(S["childcare"]))

    def test_no_contact_fields(self):
        keys = {k for c in S["childcare"] for k in c}
        self.assertFalse(keys & {"phone", "owner", "notes", "licensed_capacity"})

    def test_island_and_zones(self):
        tsunami = ZoneIndex(json.loads((ROOT / "data" / "raw" / "tsunami_zone.geojson").read_text(encoding="utf-8")))
        for c in S["childcare"]:
            self.assertTrue(c["island"] and c["county"], c["name"])
            self.assertEqual(bool(c["zones"]["tsunami"]), tsunami.contains(c["lon"], c["lat"]), c["name"])
            if c["zones"]["inland_flood"]:
                self.assertRegex(c["fld_zone"], r"^(A|V)", c["name"])
            if (c["fld_zone"] or "").upper() == "D":
                self.assertFalse(c["zones"]["inland_flood"], c["name"])   # zone D listed separately

    def test_in_care_table_app_and_pdfs(self):
        n = sum(1 for f in BUNDLE["facilities"] if f["t"] == "childcare")
        self.assertEqual(n, len(S["childcare"]))
        self.assertEqual(BUNDLE["access"]["types"]["childcare"], "Childcare centre")
        inp = bp.load_inputs()
        rows, _total = bp.facility_rows(inp["access"], "Honolulu", "tsunami", inp["state"])
        self.assertTrue(any(f["type"] == "childcare" for f in rows))
        t = text((ROOT / "playbooks" / "honolulu_tsunami.html").read_text(encoding="utf-8"))
        self.assertIn("Childcare centre", t)


class Sirens(unittest.TestCase):
    def test_counts_match_points(self):
        per = {}
        for s in S["sirens"]:
            per[s["tract"]] = per.get(s["tract"], 0) + 1
            self.assertTrue(s["county"] and s["tract"], s["id"])
        for f, a in S["areas"].items():
            self.assertEqual(a["sirens"], per.get(f, 0), f)
            if f in TRACTS:
                self.assertEqual(TRACTS[f].get("s"), a["sirens"], f)
        by = {}
        for s in S["sirens"]:
            by[s["county"]] = by.get(s["county"], 0) + 1
        self.assertEqual(by, S["sirens_by_county"])
        self.assertEqual({c: len(v) for c, v in BUNDLE["state"]["sirens"].items()}, by)

    def test_permanent_only_and_no_status(self):
        if (RAW / "sirens.geojson").exists():
            raw = json.loads((RAW / "sirens.geojson").read_text(encoding="utf-8"))["features"]
            perm = sum(1 for f in raw if f["properties"]["Permanent_Mobile"] == "Permanent")
            self.assertEqual(perm, len(S["sirens"]))
            for f in raw:
                self.assertFalse({"Dash_Stat", "Poll_Date"} & set(f["properties"]))
        self.assertFalse({"status", "Dash_Stat"} & {k for s in S["sirens"] for k in s})

    def test_zero_siren_areas(self):
        for f in S["zero_siren_areas"]:
            a = S["areas"][f]
            self.assertEqual(a["sirens"], 0)
            self.assertGreater(a["population"], 0)
        flat = sorted(f for v in BUNDLE["state"]["zero"].values() for f in v)
        self.assertEqual(flat, sorted(S["zero_siren_areas"]))

    def test_coverage_only_with_official_radius(self):
        r = S["meta"]["siren_radius"]
        self.assertEqual((r["feet"], r["metres"]), (3400, 1036))
        self.assertIn("dod.hawaii.gov/hiema", r["url"])
        self.assertEqual(BUNDLE["state"]["radius_m"], 1036)


class Dams(unittest.TestCase):
    def test_shares_between_0_and_1(self):
        for f, a in S["areas"].items():
            self.assertGreaterEqual(a["dam_share"], 0, f)
            self.assertLessEqual(a["dam_share"], 1, f)
            self.assertEqual(a["dam_people"], round(a["population"] * a["dam_share"]), f)
        tot = {}
        for a in S["areas"].values():
            tot[a["county"]] = tot.get(a["county"], 0) + a["dam_people"]
        self.assertEqual(tot, S["dam_people_by_county"])

    def test_same_method_as_tsunami(self):
        self.assertEqual(bsl.SAMPLES, 100)
        self.assertIn("same method as the tsunami share", S["meta"]["dam_method"])

    def test_sites_flagged(self):
        if (RAW / "dams.geojson").exists():
            dams = ZoneIndex(json.loads((RAW / "dams.geojson").read_text(encoding="utf-8")))
            sh = json.loads((ROOT / "data" / "processed" / "shelters_2026.geojson").read_text(encoding="utf-8"))
            for f in sh["features"]:
                if not f.get("geometry"):
                    continue
                key = f"{f['properties']['name']}|{f['properties']['county']}"
                self.assertEqual(dams.contains(*f["geometry"]["coordinates"][:2]),
                                 key in S["site_dam_zones"], key)
        for s in BUNDLE["sites"]:
            self.assertEqual(bool(s.get("dam")), f"{s['name']}|{s['county']}" in S["site_dam_zones"])
        for key in S["site_dam_zones"]:
            name, county = key.split("|")
            t = (ROOT / "playbooks" / f"{bp.slug(county, 'hurricane')}.html").read_text(encoding="utf-8")
            row = re.search(r"<tr>(?:(?!</tr>).)*" + re.escape(name) + r"(?:(?!</tr>).)*</tr>", t, re.S)
            self.assertIn("Check dam zone", row.group(0), key)

    def test_no_sixth_hazard(self):
        self.assertEqual(len(BUNDLE["hazards"]), 5)
        self.assertEqual(len(BUNDLE["scenarios"]), 20)

    def test_also_plan_for_line(self):
        rows = [r for r in BUNDLE["county_lines"] if r["line"] == "dam_zones"]
        self.assertEqual({r["county"]: r["value"] for r in rows}, S["dam_people_by_county"])
        for r in rows:
            self.assertEqual((r["label"], r["detail"]), ("People in dam evacuation zones",
                                                         "State dam evacuation zones"))


class SourcesAndPdfs(unittest.TestCase):
    def test_sources_plain_words_no_paths(self):
        for key in ("childcare", "sirens", "dams"):
            src = bp.SOURCE[key]
            self.assertNotRegex(src, r"data/|\.json|\.csv|\.geojson|scripts/", key)
            self.assertIn(src, BUNDLE["meta"]["sources"][key])
        for p in PLAYBOOKS:
            t = text(p.read_text(encoding="utf-8"))
            for word in ("Ready Keiki Locator", "Hawaiʻi Emergency Management Agency public siren map",
                         "State of Hawaiʻi dam evacuation zones", "People in dam evacuation zones",
                         "prioritise WEA, radio and trusted messengers"):
                self.assertIn(word, t, (p.name, word))

    def test_fetch_dates_recorded(self):
        for key in ("childcare", "sirens", "dams"):
            m = S["meta"]["sources"][key]
            self.assertRegex(m["fetched_at"], r"^2026-")
            self.assertTrue(m["layer_url"].startswith("https://"))
            self.assertTrue(m["item_id"])


class Size(unittest.TestCase):
    def test_bundle_growth_under_100_kb(self):
        before = 879_589                 # bundle.json at commit ceeecf8
        self.assertLess((APP / "data" / "bundle.json").stat().st_size, before + 100 * 1024)


@unittest.skipUnless(bp.find_browser(), "Chrome/Chromium not installed")
class Browser(unittest.TestCase):
    def test_panel_and_sections(self):
        port = free_port()
        server = Serve(port)
        try:
            f = next(f for f, a in S["areas"].items() if a["county"] == "Hawaii" and a["sirens"] >= 2)
            z = next(x for x in S["zero_siren_areas"] if S["areas"][x]["county"] == "Hawaii")
            with tempfile.TemporaryDirectory() as prof:
                dom = chrome(f"http://127.0.0.1:{port}/?county=Hawaii&hazard=tsunami&area={f}", prof)
            with tempfile.TemporaryDirectory() as prof:
                dom0 = chrome(f"http://127.0.0.1:{port}/?county=Hawaii&hazard=tsunami&area={z}", prof)
        finally:
            server.stop()
        self.assertIn(f"Outdoor sirens in this area: {S['areas'][f]['sirens']}", text(panel(dom)))
        self.assertIn("Outdoor sirens in this area: 0 – prioritise WEA, radio and trusted messengers",
                      text(panel(dom0)))
        t = text(dom)
        n0 = sum(1 for x in S["zero_siren_areas"] if S["areas"][x]["county"] == "Hawaii")
        self.assertIn(f"Populated Census areas with 0 outdoor sirens ({n0}): prioritise WEA", t)
        self.assertIn(f"People in dam evacuation zones {S['dam_people_by_county']['Hawaii']:,} State dam evacuation zones", t)
        self.assertIn("Check dam zone", t)
        self.assertIn('id="layer-sirens"', dom)


if __name__ == "__main__":
    unittest.main()
