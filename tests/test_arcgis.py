"""Build-time ArcGIS work: budget guard, token handling, same-island pairs, site comparison
rules, care-facility zone flags, panel numbers vs. data files, layer toggles by keyboard,
fallback without ArcGIS files, care-facility table in the app and every PDF, bundle size."""
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import build_access as ba  # noqa: E402
import build_app_data as bad  # noqa: E402
import build_playbooks as bp  # noqa: E402
import fetch_arcgis as fa  # noqa: E402
from geo import ZoneIndex, haversine_km  # noqa: E402
from test_map_detail import Serve, chrome, free_port, panel, text  # noqa: E402

APP = ROOT / "app"
SUMMARY = ba.load()
BUNDLE = json.loads((APP / "data" / "bundle.json").read_text(encoding="utf-8"))
BROWSER = bp.find_browser()
TRACTS = {t["f"]: t for t in BUNDLE["tracts"]}
with open(fa.ISLANDS, newline="", encoding="utf-8") as fh:
    ISLE = {(r["kind"], r["id"]): r["island"] for r in csv.DictReader(fh)}


class Budget(unittest.TestCase):
    def test_guard_prints_estimate_and_stops_over_budget(self):
        led = {"steps": {"a": {"credits_actual": 21.5}}}
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(fa.guard(led, "x", 10, 0.04, "geocodes"), 0.4)
        self.assertIn("[estimate] x: 10 geocodes x 0.04 = 0.4 credits", buf.getvalue())
        with redirect_stdout(io.StringIO()), self.assertRaises(fa.OverBudget):
            fa.guard(led, "y", 1, 0.5, "service areas")          # 21.5 + 0.5 = 22.0 is fine
            fa.guard({"steps": {"a": {"credits_actual": 21.6}}}, "y", 1, 0.5, "service areas")

    def test_budget_and_reserve(self):
        self.assertEqual(fa.BUDGET, 22.0)
        self.assertEqual(fa.ledger()["reserve"], 3)

    def test_ledger_logged_and_within_budget(self):
        led = json.loads(fa.CREDITS.read_text(encoding="utf-8"))
        for step in ("geocode_sites", "geocode_facilities", "od_drive", "od_walk_near",
                     "od_schools", "service_areas"):
            self.assertIn(step, led["steps"])
            self.assertIn("credits_actual", led["steps"][step])
        self.assertLessEqual(fa.spent(led), fa.BUDGET)
        self.assertEqual(led["steps"]["service_areas"]["credits_actual"], 0)   # skipped
        self.assertIn("skipped", led["steps"]["service_areas"]["note"])


class Token(unittest.TestCase):
    def test_token_sent_in_body_never_in_url(self):
        seen = {}

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake(req, timeout=0):
            seen["url"], seen["body"] = req.full_url, req.data.decode()
            return Resp(b'{"ok": true}')
        with mock.patch("urllib.request.urlopen", fake):
            fa.post("https://example.invalid/x", {"a": "1"}, "SECRET-TOKEN-123")
        self.assertNotIn("SECRET", seen["url"])
        self.assertIn("token=SECRET-TOKEN-123", seen["body"])

    def test_scrub_removes_token(self):
        self.assertEqual(fa.scrub({"u": "a?token=abc123xyz"}, "abc123xyz"), {"u": "a?token=[removed]"})

    def test_expired_token_detected(self):
        self.assertTrue(fa.token_error({"error": {"code": 498, "message": "Invalid token."}}))
        self.assertTrue(fa.token_error({"error": {"code": 400, "message": "x",
                                                  "details": ["Token Required"]}}))
        self.assertFalse(fa.token_error({"error": {"code": 400, "message": "Unable to complete"}}))

    def test_missing_token_exits_clearly_without_calls(self):
        env = {k: v for k, v in os.environ.items() if k != "ARCGIS_TOKEN"}
        with mock.patch.dict(os.environ, env, clear=True), \
                mock.patch.object(fa, "post", side_effect=AssertionError("no calls")), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            self.assertEqual(fa.main([]), 2)
        self.assertIn("ARCGIS_TOKEN is not set", err.getvalue())

    def test_expired_token_saves_progress_and_exits_3(self):
        with mock.patch.dict(os.environ, {"ARCGIS_TOKEN": "t"}), \
                mock.patch.object(fa, "run_geocodes", side_effect=fa.TokenExpired("498")), \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as err:
            self.assertEqual(fa.main(["--steps", "geocode_sites"]), 3)
        self.assertIn("TOKEN EXPIRED", err.getvalue())

    def test_token_never_in_any_file(self):
        token = os.environ.get("ARCGIS_TOKEN", "").strip()
        files = subprocess.run(["git", "ls-files", "-co", "--exclude-standard"], cwd=ROOT,
                               capture_output=True, text=True, check=True).stdout.split()
        files += [str(p.relative_to(ROOT)) for p in (ROOT / "data" / "raw" / "arcgis").glob("*")]
        for rel in files:
            p = ROOT / rel
            if not p.is_file() or p.stat().st_size > 50_000_000:
                continue
            data = p.read_bytes()
            if token:
                self.assertNotIn(token.encode(), data, rel)
            self.assertNotRegex(data.decode("utf-8", "ignore"), r"token=[A-Za-z0-9_\-.]{20,}", rel)

    def test_raw_answers_are_gitignored(self):
        r = subprocess.run(["git", "check-ignore", "data/raw/arcgis/od_drive.json"], cwd=ROOT,
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)


class SameIsland(unittest.TestCase):
    def test_od_pairs_same_island_only(self):
        origins = [{"id": "a", "island": "Maui"}, {"id": "b", "island": "Lānaʻi"}]
        dests = {"Maui": [{"id": "s1"}], "Oʻahu": [{"id": "s2"}]}
        jobs = fa.od_pairs(origins, dests)
        self.assertEqual([(i, [o["id"] for o in os_], [d["id"] for d in ds]) for i, os_, ds in jobs],
                         [("Maui", ["a"], ["s1"])])

    def test_walk_jobs_within_12_km_and_50_origins(self):
        origins = [{"id": str(i), "island": "Maui", "lon": -156.47 + i * 0.0005, "lat": 20.88}
                   for i in range(120)] + [{"id": "far", "island": "Maui", "lon": -156.0, "lat": 20.7}]
        dests = {"Maui": [{"id": "s", "lon": -156.47, "lat": 20.88}]}
        jobs = fa.walk_jobs(origins, dests)
        self.assertTrue(all(len(o) <= 50 for _s, o, _d in jobs))
        ids = [o["id"] for _s, os_, _d in jobs for o in os_]
        self.assertNotIn("far", ids)
        self.assertEqual(len(ids), 120)

    def test_summary_pairs_same_island(self):
        self.assertTrue(SUMMARY)
        for fips, a in SUMMARY["areas"].items():
            self.assertEqual(a["island"], ISLE[("area", fips)])
            for site in a["sites"]:
                self.assertEqual(ISLE[("site", site)], a["island"], (fips, site))

    def test_failed_solve_is_not_saved(self):
        self.assertTrue(fa.od_failure({"odCostMatrix": {"1": {}}, "messages": [
            {"type": 100, "description": "exceeded the maximum of 50"}]}))
        self.assertEqual(fa.od_failure({"odCostMatrix": {"1": {"1": [3.0, 2.0]}}}), "")
        self.assertEqual(fa.OD_CHUNK, 50)


class SchoolScenario(unittest.TestCase):
    def test_school_jobs_same_island_5_per_hazard(self):
        o = [{"id": "a", "island": "Maui", "lon": -156.47, "lat": 20.88}]
        schools = [{"id": f"s{i}", "island": "Maui", "lon": -156.47 + i * 0.01, "lat": 20.88,
                    "usable": ["tsunami"] if i % 2 else ["hurricane"]} for i in range(20)]
        schools.append({"id": "lanai", "island": "Lānaʻi", "lon": -156.471, "lat": 20.88,
                        "usable": ["tsunami", "hurricane"]})
        (_k, os_, ds), = fa.school_jobs(o, schools)
        ids = [d["id"] for d in ds]
        self.assertNotIn("lanai", ids)
        self.assertEqual(sorted(ids), sorted(["s1", "s3", "s5", "s7", "s9", "s0", "s2", "s4", "s6", "s8"]))
        self.assertLessEqual(len(os_), 50)

    def test_candidate_usable_rule_matches_model(self):
        from geo import ZoneIndex as Z
        from build_islands import island_of
        coast = Z(fa.load_json(fa.COAST, None))
        schools = fa.candidate_schools(lambda x, y: island_of(coast, x, y))
        self.assertEqual(len(schools), 292)
        by = {f["properties"]["id"]: f["properties"] for f in
              fa.load_json(fa.CANDIDATES, {})["features"]}
        for s in schools:
            self.assertEqual("tsunami" in s["usable"], not by[s["id"]]["hazard_excluded"], s["id"])
            self.assertTrue(s["island"], s["id"])

    def test_wording_never_implies_no_shelters(self):
        js = (APP / "app.js").read_text(encoding="utf-8")
        self.assertIn("DATA.access.no_activated", js)
        self.assertEqual(ba.NO_ACTIVATED, "No 2026 activated site within a 15-minute drive (normal traffic)")
        for p in sorted((ROOT / "playbooks").glob("*_*.html")):
            t = text(p.read_text(encoding="utf-8"))
            self.assertIn(ba.NO_ACTIVATED, t, p.name)
            self.assertIn("With DOE candidate schools usable for this hazard:", t, p.name)
            self.assertIn("not a statement that the area has no shelter", t, p.name)
            rest = t.replace(ba.NOT_NO_SHELTER, "").lower()     # the disclaimer itself
            rest = rest.replace("privately owned island, no public shelter", "")   # Niʻihau fact
            self.assertNotRegex(rest, r"\bno (public )?shelters?\b", p.name)


class SiteRules(unittest.TestCase):
    site = {"key": "X|Maui", "name": "X", "county": "Maui", "point": [-156.47, 20.88]}

    def esri(self, dlon=0.0, score=100, kind="PointAddress", sub="Maui County"):
        return {"status": "match", "lon": -156.47 + dlon, "lat": 20.88, "score": score,
                "addr_type": kind, "subregion": sub}

    def test_confirmed_within_300_m(self):
        c = fa.classify_site(self.site, self.esri(0.002), lambda x, y: "Maui")   # ~210 m
        self.assertEqual(c["status"], "confirmed")

    def test_needs_review_over_300_m_keeps_census_point(self):
        c = fa.classify_site(self.site, self.esri(0.004), lambda x, y: "Maui")   # ~420 m
        self.assertEqual(c["status"], "needs_review")
        self.assertEqual([c["lon"], c["lat"]], self.site["point"])

    def test_located_only_with_score_type_county_island(self):
        s = {**self.site, "point": None}
        isl = lambda x, y: "Maui"  # noqa: E731
        self.assertEqual(fa.classify_site(s, self.esri(), isl)["status"], "located_arcgis")
        for bad in (self.esri(score=85), self.esri(kind="Locality"), self.esri(sub="Honolulu County")):
            self.assertEqual(fa.classify_site(s, bad, isl)["status"], "not_located")
        self.assertEqual(fa.classify_site(s, self.esri(), lambda x, y: "Oʻahu")["status"],
                         "not_located")

    def test_doe_third_source(self):
        site = {"address": "", "name": "S", "county": "Honolulu"}
        doe = {"doe_school": "S", "doe_address": "1 A St", "doe_lon": "-158.0", "doe_lat": "21.5",
               "census_status": "match", "census_lon": "-158.0", "census_lat": "21.5018"}   # ~200 m
        self.assertEqual(ba.doe_status(site, {"distance_m": 26000}, doe)["status"], "confirmed_doe_census")
        self.assertFalse(ba.doe_status(site, {"distance_m": 26000}, doe)["arcgis_query_valid"])
        far = {**doe, "census_lat": "21.51"}                                                 # ~1.1 km
        self.assertNotIn("status", ba.doe_status(site, {"distance_m": 26000}, far))
        with_addr = {**site, "address": "1 A St"}
        self.assertEqual(ba.doe_status(with_addr, {"distance_m": 120}, far)["status"], "confirmed_doe_arcgis")

    def test_needs_review_resolution(self):
        st = {k: v["status"] for k, v in SUMMARY["sites"].items()}
        self.assertEqual(st["Kahuku Elementary School|Honolulu"], "confirmed_doe_census")
        self.assertEqual(st["Nānākuli High and Intermediate School|Honolulu"], "confirmed_doe_census")
        review = {k for k, v in st.items() if v == "needs_review"}
        self.assertEqual(review, set(SUMMARY["site_reviews"]))
        self.assertEqual(review, {"Keaʻau Armory|Hawaii", "Puʻuʻeo Community Center|Hawaii",
                                  "Pāpaʻaloa Park Annex|Hawaii", "Lahaina Civic Center Gym|Maui",
                                  "South Maui Community Park Gym|Maui"})

    def test_review_keeps_current_point_and_lists_changes(self):
        sh = {f["properties"]["name"] + "|" + f["properties"]["county"]: f
              for f in fa.load_json(fa.SHELTERS, {})["features"]}
        for k, r in SUMMARY["site_reviews"].items():
            self.assertEqual([round(c, 6) for c in sh[k]["geometry"]["coordinates"][:2]],
                             [r["current"]["lon"], r["current"]["lat"]], k)
        lah = SUMMARY["site_reviews"]["Lahaina Civic Center Gym|Maui"]
        self.assertTrue(lah["current"]["in_tsunami_zone"])
        self.assertEqual(lah["status_changes"].get("tsunami"), ["exclude", "ok"])
        doc = ba.REVIEW_DOC.read_text(encoding="utf-8")
        for k in SUMMARY["site_reviews"]:
            self.assertIn(f"## {k.split('|')[0]}", doc)
        self.assertIn("tsunami: excluded (tsunami zone) → usable", doc)
        self.assertIn("The current point is kept", doc)

    def test_summary_rules_hold(self):
        for key, v in SUMMARY["sites"].items():
            if v["status"] == "confirmed":
                self.assertLessEqual(v["distance_m"], 300, key)
            if v["status"] == "needs_review":
                self.assertGreater(v["distance_m"], 300, key)
        located = [k for k, v in SUMMARY["sites"].items() if v["status"] == "located_arcgis"]
        self.assertEqual(located, ["Mayor Hannibal Tavares Community Center (Social Hall)|Maui"])

    def test_located_site_is_on_the_map(self):
        s = next(x for x in BUNDLE["sites"] if x["name"].startswith("Mayor Hannibal Tavares"))
        self.assertIsNotNone(s["lon"])
        self.assertEqual(s["island"], "Maui")
        self.assertEqual(s["loc"], "Located (ArcGIS)")


class FacilityZones(unittest.TestCase):
    def test_zone_rules(self):
        z = ba.hazard_zones({"in_tsunami_zone": True, "fld_zone": "AE", "in_sfha": True})
        self.assertEqual(z["tsunami"], "Tsunami evacuation zone")
        self.assertEqual(z["inland_flood"], "FEMA flood zone AE")
        self.assertEqual(z["coastal_flood"], "FEMA flood zone AE")
        self.assertEqual(z["hurricane"], "")
        self.assertEqual(z["wildfire"], "")
        z = ba.hazard_zones({"in_tsunami_zone": False, "fld_zone": "X", "in_sfha": False})
        self.assertFalse(any(z.values()))
        z = ba.hazard_zones({"in_tsunami_zone": False, "fld_zone": "VE", "in_sfha": True})
        self.assertEqual(z["coastal_flood"], "FEMA flood zone VE")
        z = ba.hazard_zones({"in_tsunami_zone": False, "fld_zone": "D", "in_sfha": False})
        self.assertFalse(any(z.values()))                  # zone D: not mapped, not a zone

    def test_flags_match_tsunami_zone_layer(self):
        idx = ZoneIndex(json.loads(ba.TSUNAMI.read_text(encoding="utf-8")))
        fac = SUMMARY["facilities"]
        self.assertGreaterEqual(len(fac), 100)
        for f in fac:
            self.assertEqual(bool(f["zones"]["tsunami"]), idx.contains(f["lon"], f["lat"]), f["name"])
            if f["zones"]["inland_flood"].startswith("FEMA flood zone "):
                self.assertTrue(f["fld_zone"][0] in "AV", f["name"])

    def test_every_facility_has_island_county_type(self):
        for f in SUMMARY["facilities"]:
            self.assertIn(f["island"], fa.ISLE_COUNTY, f["name"])
            self.assertEqual(f["county"], fa.ISLE_COUNTY[f["island"]], f["name"])
            self.assertIn(f["type"], ba.TYPE_LABEL)

    def test_no_patient_data(self):
        keys = {k for f in SUMMARY["facilities"] for k in f}
        self.assertLessEqual(keys, {"id", "type", "type_label", "name", "address", "lon", "lat",
                                    "island", "county", "tract", "in_tsunami_zone", "fld_zone",
                                    "zones", "source", "source_url"})


class PanelData(unittest.TestCase):
    def test_bundle_times_match_summary(self):
        ids = {f"{s['name']}|{s['county']}": s["id"] for s in BUNDLE["sites"]}
        n = 0
        for fips, a in SUMMARY["areas"].items():
            if fips not in TRACTS:
                continue
            got = {r[0]: r[1:] for r in TRACTS[fips].get("a", [])}
            want = {ids[k]: v for k, v in a["sites"].items()}
            self.assertEqual(got, want, fips)
            want_o = {h: ba.outside(d1) + ba.outside(d2)
                      for h, (d1, d2) in a["drive_by_hazard"].items() if ba.outside(d1)}
            self.assertEqual(TRACTS[fips].get("o", {}), want_o, fips)
            n += 1
        self.assertGreater(n, 400)

    def test_scenario_1_uses_usable_activated_sites_only(self):
        usable = ba.site_usable()
        for fips, a in SUMMARY["areas"].items():
            for h, (d1, d2) in a["drive_by_hazard"].items():
                drives = [v[0] for k, v in a["sites"].items() if v[0] is not None and h in usable[k]]
                self.assertEqual(d1, min(drives) if drives else None, (fips, h))
                if d1 is not None:
                    self.assertLessEqual(d2, d1, (fips, h))      # schools can only add options

    def test_scenario_2_never_worse_and_counts_in_bundle(self):
        counts = ba.outside_counts(SUMMARY)
        self.assertEqual(len(counts), 20)
        for (c, h), (n1, n2, total) in counts.items():
            self.assertLessEqual(n2, n1, (c, h))
            self.assertEqual(BUNDLE["access"]["outside_counts"][f"{c}|{h}"], [n1, n2, total])

    def test_facilities_in_bundle_match_summary(self):
        self.assertEqual(len(BUNDLE["facilities"]), len(SUMMARY["facilities"]))
        for b, s in zip(BUNDLE["facilities"], SUMMARY["facilities"]):
            self.assertEqual((b["n"], b["x"], b["y"], b["f"]), (s["name"], s["lon"], s["lat"], s["tract"]))
            self.assertEqual(b["z"], {h: z for h, z in s["zones"].items() if z})
            self.assertEqual(b.get("d"), 1 if s["fld_zone"] == "D" else None)


class Playbooks(unittest.TestCase):
    def test_every_pdf_html_has_table_and_sources(self):
        pages = sorted((ROOT / "playbooks").glob("*.html"))
        pages = [p for p in pages if p.name != "index.html"]
        self.assertEqual(len(pages), 20)
        for p in pages:
            t = text(p.read_text(encoding="utf-8"))
            self.assertIn("Care facilities in hazard zones", t, p.name)
            self.assertIn(ba.SOURCE_TEXT, t, p.name)
            self.assertIn("Powered by Esri", t, p.name)

    def test_table_rows_match_data(self):
        inp = bp.load_inputs()
        for county in ("Honolulu", "Maui"):
            rows, total = bp.facility_rows(inp["access"], county, "tsunami")
            h = bp.facilities_html(inp, county, "tsunami")
            self.assertIn(f"({len(rows)} of {total})", h)
            for f in rows:
                self.assertIn(bp.escape(f["name"]), h)


class Fallback(unittest.TestCase):
    def test_summarize_without_raw_files(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ba, "RAW", Path(d)):
            self.assertIsNone(ba.summarize(offline=True))

    def test_bundle_parts_without_summary(self):
        self.assertEqual(bad.area_access("15001020100", {"x": 1}, None), {})
        self.assertEqual(bad.facilities_bundle(None), [])
        self.assertEqual(bad.access_meta(None), {})
        inp = bp.load_inputs()
        self.assertEqual(bp.facilities_html({**inp, "access": None}, "Maui", "tsunami"), "")


@unittest.skipUnless(BROWSER, "Chrome/Chromium not installed")
class Browser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = Serve(cls.port)
        cls.base = f"http://127.0.0.1:{cls.port}/"

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def test_layers_toggle_by_keyboard(self):
        out = subprocess.run(["node", str(ROOT / "tests" / "keyboard_layers.mjs"), BROWSER,
                              f"{self.base}?county=Maui&hazard=tsunami"],
                             capture_output=True, text=True, timeout=120).stdout
        r = json.loads(out.strip().splitlines()[-1])
        for name in ("outside", "care"):
            self.assertTrue(r[name]["reached"], name)               # reachable with Tab
            self.assertEqual(r[name]["before"], [True, None], name)
            self.assertEqual(r[name]["after"], [False, "none"], name)   # Space hides the layer
        self.assertIn("No 2026 activated site within a 15-minute drive (normal traffic)", r["outside"]["label"])
        self.assertIn("Care facilities", r["care"]["label"])

    def test_panel_minutes_and_facilities_match_data(self):
        fips = next(f["f"] for f in BUNDLE["facilities"] if f["c"] == "Honolulu" and f["z"].get("tsunami"))
        with tempfile.TemporaryDirectory() as prof:
            dom = chrome(f"{self.base}?county=Honolulu&hazard=tsunami&area={fips}", prof)
        p = text(panel(dom))
        rows = [r for r in TRACTS[fips]["a"] if r[1] is not None]
        ok = {s["id"]: s for s in BUNDLE["sites"]
              if s["county"] == "Honolulu" and s["status"]["tsunami"][0] == "ok" and s["island"] == "Oʻahu"}
        first = sorted((r for r in rows if r[0] in ok), key=lambda r: (r[1], ok[r[0]]["name"]))[0]
        self.assertIn(f"{ok[first[0]]['name']} {round(first[1])} min drive", p)
        self.assertIn("normal traffic, not disaster conditions", p)
        self.assertIn("Care facilities in this area", p)
        for f in BUNDLE["facilities"]:
            if f["f"] == fips:
                self.assertIn(f["n"], p)
        self.assertIn("⚠ Yes – Tsunami evacuation zone", p)
        self.assertIn("Care facilities in hazard zones", text(dom))
        self.assertIn("Powered by Esri", text(dom))

    def test_fallback_without_arcgis_data(self):
        """A bundle with no ArcGIS parts: straight-line distances, no new layers."""
        with tempfile.TemporaryDirectory() as d:
            app = Path(d) / "app"
            shutil.copytree(APP, app, ignore=shutil.ignore_patterns("playbooks"))
            b = json.loads((app / "data" / "bundle.json").read_text(encoding="utf-8"))
            b["access"], b["facilities"] = {}, []
            for t in b["tracts"]:
                t.pop("a", None)
                t.pop("o", None)
            (app / "data" / "bundle.json").write_text(json.dumps(b), encoding="utf-8")
            port = free_port()
            with mock.patch("test_map_detail.APP", app):
                server = Serve(port)
            try:
                fips = b["scenarios"]["Maui|wildfire"]["priority_tracts"][0]["tract_fips"]
                with tempfile.TemporaryDirectory() as prof:
                    dom = chrome(f"http://127.0.0.1:{port}/?county=Maui&hazard=wildfire&area={fips}", prof)
            finally:
                server.stop()
        p = text(panel(dom))
        self.assertIn("km straight-line, same island", p)
        self.assertNotIn("min drive", p)
        self.assertNotIn('id="layer-outside"', dom)
        self.assertNotIn("Care facilities in hazard zones", text(dom))
        self.assertIn("Site key", text(dom))


class Size(unittest.TestCase):
    def test_bundle_growth_under_150_kb(self):
        before_arcgis = 782_422            # bundle.json at commit a1ccb82
        self.assertLess((APP / "data" / "bundle.json").stat().st_size, before_arcgis + 150 * 1024)

    def test_app_makes_no_arcgis_requests(self):
        js = (APP / "app.js").read_text(encoding="utf-8")
        self.assertNotRegex(js, r"arcgis\.com|https?://(?!www\.w3\.org)")
        self.assertIn("connect-src 'self'", (APP / "_headers").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
