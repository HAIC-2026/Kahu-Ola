"""Stress tests, the what-if engine and the State Hub layers.

Every finding traces to data files and carries no number without data; ranks are stable;
combined footprints never double count; sites and routes stay on the same island; the
ArcGIS budget guard stops paid steps; the token is in no file; PDC contact fields are never
stored; the what-if JavaScript matches the Python reference (50 random input sets) and its
plan defaults reproduce the plan; inputs round-trip through the URL; in headless Chrome the
new views make no outside requests, work offline, render in light and dark mode and show
no "null", "undefined", "NaN" or "[object". Tests that need data/raw/, Node or Chrome skip."""
import csv
import functools
import http.server
import json
import math
import os
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_playbooks as bp  # noqa: E402
import fetch_arcgis as fa  # noqa: E402
import stress_text  # noqa: E402
import whatif  # noqa: E402
from fetch_data import COUNTIES  # noqa: E402
from model_needs import HAZARDS  # noqa: E402

APP = ROOT / "app"
PROC = ROOT / "data" / "processed"
SOURCES = ROOT / "data" / "sources"
ST = json.loads((PROC / "stress_tests.json").read_text(encoding="utf-8"))
F = ST["findings"]
BUNDLE = json.loads((APP / "data" / "bundle.json").read_text(encoding="utf-8"))
LAZY = json.loads((APP / "data" / "stress.json").read_text(encoding="utf-8"))   # stress, what-if, map layers
BUNDLE.update({k: LAZY[k] for k in ("stress", "whatif", "hub")})
HUB = json.loads((SOURCES / "hub_layers_summary.json").read_text(encoding="utf-8"))
ROADS = json.loads((SOURCES / "road_closures_summary.json").read_text(encoding="utf-8"))
NODE = shutil.which("node")
BROWSER = bp.find_browser()
RAW_READY = all((fa.RAW / n).exists() for n in ("od_drive.json", "od_schools.json", "od_closures_drive.json")) \
    and (ROOT / "data" / "raw" / "hub" / "fire_risk.geojson").exists()
BY_ID = {f["id"]: f for f in F}
ISLAND = {}
with open(SOURCES / "islands.csv", newline="", encoding="utf-8") as fh:
    for r in csv.DictReader(fh):
        ISLAND[(r["kind"], r["id"])] = r["island"]


def scen(county, hazard):
    return next(s for s in json.loads((PROC / "needs_by_scenario.json").read_text(encoding="utf-8"))["scenarios"]
                if s["county"] == county and s["hazard"] == hazard)


class Findings(unittest.TestCase):
    def test_definition_15_everywhere(self):
        d = ST["definition_15"]
        self.assertIn("15 minutes or less before the loss and is more than 15 minutes", d)
        self.assertEqual(LAZY["stress"]["definition_15"], d)
        self.assertIn("definition_15", (APP / "stress.js").read_text(encoding="utf-8"))
        import html as _html
        self.assertIn(_html.escape(d), (ROOT / "playbooks" / "maui_tsunami.html").read_text(encoding="utf-8"))
        self.assertIn(d, (ROOT / "PLAN.md").read_text(encoding="utf-8"))

    def test_incremental_15_minutes(self):
        """Every area counted was within 15 minutes before the loss and is beyond it after."""
        acc = json.loads((SOURCES / "arcgis_summary.json").read_text(encoding="utf-8"))["areas"]
        sites = {s["name"] + "|" + s["county"]: s for s in BUNDLE["sites"]}
        for fid in ("T01-hurricane-manoa_valley_district_park-honolulu", ):
            f = BY_ID[fid]
            k, h = f["sites"][0], f["hazard"]
            ok = {kk for kk, s in sites.items() if (s["status"].get(h) or [""])[0] == "ok"}
            n = 0
            for a, v in acc.items():
                if ISLAND[("area", a)] != f["evidence"]["island"]:
                    continue
                t = [m[0] for kk, m in v["sites"].items() if kk in ok and m[0] is not None]
                t2 = [m[0] for kk, m in v["sites"].items() if kk in ok and kk != k and m[0] is not None]
                before, after = min(t, default=None), min(t2, default=None)
                if before is not None and before <= 15 and (after is None or after > 15):
                    n += 1
            self.assertGreaterEqual(n, f["evidence"]["areas_pushed_outside"])   # risk-area subset of these

    def test_slr_label_and_cut_off_area(self):
        label = "Future sea-level-rise scenario (3.2 ft; State of Hawaiʻi SLR-XA), tested against 2026 sites"
        f = BY_ID["T24-flooded_maui-drive"]
        self.assertTrue(f["scenario"].startswith(label))
        self.assertEqual(f["evidence"]["areas_cut_off"], ["Launiupoko / Māʻalaea · Census area 320"])
        self.assertIn(label, LAZY["hub"]["sources"]["flooded"])
        self.assertIn(label, (APP / "app.js").read_text(encoding="utf-8"))
        self.assertIn(label, (ROOT / "PLAN.md").read_text(encoding="utf-8"))

    def test_factor_sources_next_to_numbers(self):
        bases = BUNDLE["meta"]["bases"]
        for sc in BUNDLE["scenarios"].values():
            got = {n[0]: bases[n[7]] for n in sc["needs"]}
            self.assertIn("Florida DEM (2010): 2 meals per person per day", got["Meals"])
            self.assertIn("Florida DEM (2010): 1 gal per person per day", got["Water"])
            self.assertIn("planning assumption", got["Cots / sleeping space"])
            self.assertIn("registration 1:165", got["Shelter staff"])
        html = (ROOT / "playbooks" / "maui_tsunami.html").read_text(encoding="utf-8")
        self.assertIn("Florida DEM (2010): 2 meals per person per day", html)
        self.assertIn("one cot per person in shelter** (planning assumption", (ROOT / "PLAN.md").read_text(encoding="utf-8").split("## 10.")[1])

    def test_pdc_source_wording(self):
        w = "via third-party ArcGIS Online copy; PDC catalogue confirms 2009 date"
        self.assertIn(w, (ROOT / "playbooks" / "maui_tsunami.html").read_text(encoding="utf-8"))
        self.assertIn(w, (ROOT / "PLAN.md").read_text(encoding="utf-8"))
        self.assertIn("third-party ArcGIS Online copy", LAZY["hub"]["pdc_note"])

    def test_every_test_ran(self):
        tests = {f["test"] for f in F}
        want = {str(i) for i in range(1, 23)} | {"23a", "23b", "24", "25"}
        self.assertEqual(tests, want)

    def test_every_finding_traces_to_sources_and_label(self):
        for f in F:
            self.assertTrue(f["sources"], f["id"])
            self.assertEqual(f["label"], "stress test, not a forecast")
            self.assertTrue(f["measure"], f["id"])
            for s in f["sources"]:                       # plain words, never a file name
                self.assertNotRegex(s, r"\w+\.(json|csv|py|geojson)\b|data/|scripts/", f["id"])
            for a in f["assumptions"]:
                self.assertEqual(a["kind"], "team assumption", f["id"])
                self.assertNotEqual(str(a["value"]), "", f["id"])

    def test_numbers_trace_to_data_files(self):
        lines = list(csv.DictReader(open(SOURCES / "county_lines.csv", encoding="utf-8")))
        for c in COUNTIES:
            self.assertEqual(BY_ID[f"T08-{c.lower()}"]["people_affected"], scen(c, "tsunami")["at_risk_pop_extreme_zone"])
            vis = next(int(r["value"]) for r in lines if r["county"] == c and r["line"] == "visitors")
            self.assertEqual(BY_ID[f"T20-{c.lower()}"]["people_affected"], vis)
            for h in HAZARDS:
                self.assertEqual(BY_ID[f"T12-{h}-{c.lower()}"]["people_affected"], scen(c, h)["M_power_dependent_at_risk"])
                self.assertEqual(BY_ID[f"T11-{h}-{c.lower()}"]["people_affected"], scen(c, h)["shelter_demand_central"])
                self.assertEqual(BY_ID[f"T17-{h}-{c.lower()}"]["people_affected"],
                                 scen(c, h)["dog_households"] + scen(c, h)["cat_households"])
            walk = HUB["safe_zone_walk"]
            over = sum(a["no_car"] for a in walk.values() if a["county"] == c and (a["walk_min"] or 0) > 15)
            self.assertEqual(BY_ID[f"T23a-walk-{c.lower()}"]["people_affected"], round(over))
        match = json.loads((PROC / "match_plan.json").read_text(encoding="utf-8"))["scenarios"]
        f = BY_ID["T09-hurricane-all"]
        self.assertEqual(f["people_affected"], sum(s["shelter_demand_central"] for s in match if s["hazard"] == "hurricane"))
        self.assertEqual(f["evidence"]["cots"], sum(n["quantity"] for s in match if s["hazard"] == "hurricane"
                                                    for n in s["needs"] if n["need"] == "Cots / sleeping space"))
        pop = {x["properties"]["tract_fips"]: x["properties"].get("population") or 0 for x in
               json.loads((PROC / "afn_tracts.geojson").read_text(encoding="utf-8"))["features"]}
        for key, s in ROADS["scenarios"].items():
            hit = {o for o, r in s["areas"].items() if r[4] > 0 or o in s["isolated"] or o in s["isolated_from_2026_sites"]
                   or (r[2] is not None and r[3] is not None and r[3] - r[2] >= 1)}
            self.assertEqual(s["people_affected"], round(sum(pop[o] for o in hit)), key)

    def test_no_finding_without_data(self):
        for f in F:
            if f["people_affected"] is None:
                self.assertTrue(f["unit"] == "needs county data" or "needs county data" in json.dumps(f["evidence"]), f["id"])
        for f in F:                                # values that have no data say so, never a number
            for k in ("visitors_in_tsunami_zone", "children_enrolled", "residents_or_patients",
                      "power_loss_area", "site_backup_power"):
                if k in f["evidence"]:
                    self.assertIn("needs county data", f["evidence"][k], f["id"])
        unreliable = [f for f in F if f["test"] == "16" and not f["evidence"]["reliable"]]
        self.assertTrue(unreliable)
        for f in unreliable:
            self.assertIsNone(f["people_affected"], f["id"])

    def test_ranks_total_and_ordered(self):
        ranks = [f["rank"] for f in F]
        self.assertEqual(sorted(ranks), list(range(1, len(F) + 1)))
        key = lambda f: (f["unit"] != "people" or f["people_affected"] is None, -(f["people_affected"] or 0), f["id"])  # noqa: E731
        self.assertEqual([f["id"] for f in sorted(F, key=key)], [f["id"] for f in sorted(F, key=lambda f: f["rank"])])
        ids = [f["id"] for f in F]
        self.assertEqual(len(ids), len(set(ids)))

    @unittest.skipUnless(RAW_READY, "needs data/raw/ (ArcGIS answers and State Hub layers)")
    def test_ranks_stable_across_rebuilds(self):
        import build_stress_tests as bst
        a = {f["id"]: f["rank"] for f in bst.build()["findings"]}
        b = {f["id"]: f["rank"] for f in bst.build()["findings"]}
        self.assertEqual(a, b)
        self.assertEqual(a, {f["id"]: f["rank"] for f in F})        # and the committed file

    def test_no_double_counting_in_unions(self):
        for t in ("4", "5", "6", "7"):
            for f in [x for x in F if x["test"] == t]:
                e = f["evidence"]
                self.assertLessEqual(e["people_in_union"], e["if_counted_separately"], f["id"])
                self.assertGreater(e["people_in_union"], 0, f["id"])
        for c in COUNTIES:                         # hurricane covers the county: the union adds no one
            e = BY_ID[f"T05-{c.lower()}"]["evidence"]
            self.assertEqual(e["people_in_union"], scen(c, "hurricane")["at_risk_pop"])

    @unittest.skipUnless(RAW_READY, "needs data/raw/ (2020 blocks, zones)")
    def test_union_shares_never_above_one(self):
        import build_stress_tests as bst
        from geo import ZoneIndex
        from raw_inputs import load_geojson
        import block_shares
        inp = bst.Inputs()
        u = bst.union(inp, ["tsunami", "coastal_flood"], {"tsunami": ZoneIndex(load_geojson(bst.ba.TSUNAMI, "tsunami"))},
                      block_shares.load())
        for f, (people, demand, share) in u.items():
            self.assertLessEqual(share, 1.0 + 1e-9, f)
            self.assertLessEqual(people, (inp.tracts[f].get("population") or 0) + 1e-6, f)
            parts = [inp.tracts[f].get("tsunami_zone_share") or 0] + [1.0 for h in ("coastal_flood",) if (f, h) in inp.needs]
            self.assertGreaterEqual(share + 0.0006, max(parts), f)          # never below either footprint
            self.assertLessEqual(share, sum(parts) + 0.0006, f)             # never above their sum

    def test_same_island_only(self):
        for f in F:
            if f["test"] in ("1", "2"):
                isl = {ISLAND.get(("site", k)) for k in f["sites"]}
                self.assertEqual(len(isl), 1, f["id"])
                self.assertEqual(isl, {f["evidence"]["island"]}, f["id"])
                for a in f["areas"]:
                    self.assertEqual(ISLAND[("area", a)], f["evidence"]["island"], f["id"])
        for s in ROADS["scenarios"].values():
            for o in s["areas"]:
                self.assertEqual(ISLAND[("area", o)], s["island"], s["id"])

    def test_wording_never_says_safe_or_no_shelter(self):
        bad = re.compile(r"\bsafe\b(?! zone)|\bno shelter\b(?! *:)", re.I)
        for f in F:
            text = " ".join([f["scenario"], f["measure"], stress_text.summary(f)] +
                            [v for _k, v in stress_text.evidence_lines(f)])
            self.assertNotRegex(text.replace("Tsunami Safe Zone", "").replace("safe zone", ""), bad, f["id"])

    def test_questions_have_no_numbers(self):
        for title, q in stress_text.QUESTIONS:
            self.assertNotRegex((title + q).replace("Survey123", "Survey"), r"\d", title)   # a product name
        self.assertEqual(len(stress_text.QUESTIONS), 5)


class ArcGIS(unittest.TestCase):
    def test_budget_guard_stops_before_any_paid_call(self):
        import fetch_stress_routes as fsr
        led = {"steps": {"x": {"credits_actual": 21.9}}}
        calls = []
        orig = fa.post
        fa.post = lambda *a, **k: calls.append(a) or {}
        try:
            with tempfile.TemporaryDirectory() as d, self.assertRaises(fa.OverBudget):
                old = fa.RAW
                fa.RAW = Path(d)
                try:
                    o = {"id": "a", "island": "Maui", "lon": -156.5, "lat": 20.8}
                    jobs = [(f"s|{i}", "s", o, [{"id": f"d{j}", "lon": -156.4, "lat": 20.8} for j in range(250)], {})
                            for i in range(2)]
                    fsr.run_jobs("test_step", "Driving Time", "TravelTime", jobs, "x", led)
                finally:
                    fa.RAW = old
        finally:
            fa.post = orig
        self.assertEqual(calls, [])

    def test_total_credits_within_budget(self):
        led = json.loads(fa.CREDITS.read_text(encoding="utf-8"))
        total = sum(s.get("credits_actual", 0) for s in led["steps"].values())
        self.assertLessEqual(total, 22.0)
        for step in ("walk_safe_zones", "od_closures_drive", "od_closures_walk", "od_flooded_drive"):
            self.assertIn(step, led["steps"])
            s = led["steps"][step]
            self.assertAlmostEqual(s["credits_actual"], s["units_billed"] * s["rate"], places=4)

    def test_scrub_removes_token(self):
        self.assertEqual(fa.scrub({"a": "x SECRETTOKEN y"}, "SECRETTOKEN"), {"a": "x [removed] y"})

    @unittest.skipUnless(os.environ.get("ARCGIS_TOKEN"), "ARCGIS_TOKEN not set")
    def test_token_in_no_file(self):
        token = os.environ["ARCGIS_TOKEN"].strip().encode()
        hits = [str(p) for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts
                and p.stat().st_size < 60_000_000 and token in p.read_bytes()]
        self.assertEqual(hits, [])

    def test_token_only_from_environment(self):
        for name in ("fetch_stress_routes.py", "fetch_arcgis.py", "fetch_hub_layers.py"):
            src = (ROOT / "scripts" / name).read_text(encoding="utf-8")
            self.assertNotRegex(src, r"token\s*=\s*['\"][A-Za-z0-9_\-]{20,}", name)
        self.assertIn('os.environ.get("ARCGIS_TOKEN"', (ROOT / "scripts" / "fetch_stress_routes.py").read_text(encoding="utf-8"))

    def test_only_per_area_summaries_committed(self):
        for s in ROADS["scenarios"].values():
            for row in s["areas"].values():
                self.assertEqual(len(row), 5)
        self.assertNotIn("matrix", json.dumps(ROADS))
        self.assertNotIn("matrix", json.dumps(HUB))


class Pdc(unittest.TestCase):
    def test_contact_fields_absent(self):
        import fetch_hub_layers as fhl
        self.assertFalse({"PHONE", "CONTACT"} & set(fhl.PDC_FIELDS))
        text = json.dumps(HUB["pdc"]) + json.dumps(BUNDLE["hub"])
        self.assertNotRegex(text, r'(?i)"(phone|contact)"\s*:')
        self.assertNotRegex(text, r"\b\d{7}\b|\(?808\)?[ -]?\d{3}-?\d{4}")       # no phone numbers
        raw = ROOT / "data" / "raw" / "hub" / "pdc_shelters.geojson"
        if raw.exists():
            for f in json.loads(raw.read_text(encoding="utf-8"))["features"]:
                self.assertFalse({"PHONE", "CONTACT"} & set(f["properties"]))

    def test_capacity_offered_only_as_outdated_reference(self):
        self.assertIn("may be outdated", BUNDLE["hub"]["pdc_note"])
        self.assertEqual(HUB["pdc"]["matched_with_capacity"], 26)
        for k, v in HUB["pdc"]["site_capacity"].items():
            self.assertGreater(v["capacity"], 0)
            self.assertLessEqual(v["distance_m"], 400)
        js = (APP / "stress.js").read_text(encoding="utf-8")
        self.assertIn("support: null, cap: {}", (APP / "whatif.js").read_text(encoding="utf-8"))   # default: unknown
        self.assertIn("Load 2009 reference capacity (may be outdated)", js)

    def test_maui_2013_limitation_shown(self):
        self.assertIn("2013", BUNDLE["hub"]["maui_2013"])
        self.assertIn("maui_2013", (APP / "app.js").read_text(encoding="utf-8"))


@unittest.skipUnless(shutil.which("pdftotext") and shutil.which("pdfinfo"), "poppler not installed")
class Annex(unittest.TestCase):
    ANNEX = sorted((ROOT / "playbooks" / "annex").glob("*_stress_annex.pdf"))

    @staticmethod
    def text(pdf, first=None, last=None):
        args = ["pdftotext"] + ([f"-f", str(first), "-l", str(last)] if first else []) + [str(pdf), "-"]
        return subprocess.run(args, capture_output=True, text=True, check=True).stdout

    @staticmethod
    def pages(pdf):
        return int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", str(pdf)], capture_output=True,
                                                                text=True, check=True).stdout).group(1))

    def test_one_annex_per_county(self):
        self.assertEqual([p.name for p in self.ANNEX], [f"{c.lower()}_stress_annex.pdf" for c in sorted(COUNTIES, key=str.lower)])
        for pdf in self.ANNEX:
            t = self.text(pdf)
            self.assertIn("stress-test annex", t)
            self.assertIn("Every result, ranked by people affected", t)
            self.assertIn("Planning aid. Supports, does not replace, county emergency plans.", t)
            self.assertNotRegex(t, r"(?<![A-Za-z])AI(?![A-Za-z])|Claude|\w+\.(json|csv|py|geojson)\b|\b(null|undefined|NaN)\b")

    def test_playbook_summary_is_one_last_page(self):
        for pdf in sorted((ROOT / "playbooks").glob("*.pdf")):
            n = self.pages(pdf)
            last = self.text(pdf, n, n)
            self.assertIn("10. Stress tests – summary", last, pdf.name)
            self.assertIn("Questions for counties", last, pdf.name)
            self.assertIn("Partner capacity", last, pdf.name)                      # the last question fits
            self.assertNotIn("10. Stress tests", self.text(pdf, n - 1, n - 1), pdf.name)

    def test_annexes_linked_and_precached(self):
        sw = (APP / "sw.js").read_text(encoding="utf-8")
        for c in COUNTIES:
            self.assertEqual(BUNDLE["meta"]["annex"][c], f"playbooks/annex/{c.lower()}_stress_annex.pdf")
            self.assertIn(f'"playbooks/annex/{c.lower()}_stress_annex.pdf"', sw)
        for f in ("data/stress.json", "data/messages.json", "stress.js", "whatif.js"):
            self.assertIn(f'"{f}"', sw)
        self.assertNotIn("stress", json.loads((APP / "data" / "bundle.json").read_text(encoding="utf-8")))


W = BUNDLE["whatif"]


def random_inputs(rng: random.Random, key: str, sites: list) -> dict:
    L = W["limits"]
    cap = {s["id"]: rng.randint(0, 3000) for s in sites if s["usable"] and rng.random() < 0.5}
    return {"rate": round(rng.uniform(*L["rate"]) * 200) / 200, "stay": rng.randint(*L["stay"]),
            "outage": rng.randint(*L["outage"]), "trip": rng.randint(*L["trip"]),
            "support": None if rng.random() < 0.3 else round(rng.uniform(*L["support"]) * 200) / 200,
            "cap": cap}


def run_js(cases: list) -> list:
    script = """
const W = require(process.argv[2]); const B = JSON.parse(require('fs').readFileSync(process.argv[3], 'utf8'));
const cases = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const out = cases.map((c) => ({ r: W.compute(B.whatif, c.key, c.inp),
  a: W.allocate(c.areas, c.sites, c.inp, B.whatif.scenarios[c.key].rate),
  q: W.toQuery(c.inp, W.defaults(B.whatif, c.key)) }));
out.forEach((o, i) => { const q = o.q; o.back = W.fromQuery((k) => (k in q ? q[k] : null), W.defaults(B.whatif, cases[i].key), B.whatif.limits); });
process.stdout.write(JSON.stringify(out));"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(script)
    try:
        res = subprocess.run([NODE, fh.name, str(APP / "whatif.js"), str(APP / "data" / "stress.json")],
                             input=json.dumps(cases), capture_output=True, text=True, timeout=120, check=True)
    finally:
        os.unlink(fh.name)
    return json.loads(res.stdout)


def py_allocate_for_compare(a):
    a = dict(a)
    a["sites"] = [{**s, "cap": s["cap"]} for s in a["sites"]]
    return a


class WhatIf(unittest.TestCase):
    def test_defaults_reproduce_plan_numbers_python(self):
        for key, sc in BUNDLE["scenarios"].items():
            r = whatif.compute(W, key, {"rate": W["scenarios"][key]["rate"], "stay": 3, "outage": 0,
                                        "trip": W["defaults"]["people_per_trip"], "support": None, "cap": {}})
            need = {n[0]: n[1] for n in sc["needs"]}
            self.assertEqual(r["people_in_shelter"], sc["summary"]["shelter_demand_central"], key)
            got = {"Cots / sleeping space": r["cots"], "Floor space (≤72 h)": r["floor_sqft"], "Water": r["water_per_day"],
                   "Meals": r["meals_per_day"], "Toilets (≤72 h)": r["toilets"], "Shelter staff": r["staff_total"],
                   "Power outlets for power-dependent residents": r["outlets_per_day"],
                   "Accessible transport": r["transport_people"], "Pet space – dog households": r["dog_households"],
                   "Pet space – cat households": r["cat_households"], "Children's area": r["children"],
                   **{f"Interpreters – {l}": n for l, n in r["interpreters"]}}
            for k, v in got.items():
                self.assertEqual(need[k], v, (key, k))
            self.assertEqual(len([k for k in need if k.startswith("Interpreters")]), len(r["interpreters"]), key)
            long = whatif.compute(W, key, {"rate": W["scenarios"][key]["rate"], "stay": 14, "outage": 0,
                                           "trip": 20, "support": None, "cap": {}})
            self.assertEqual(long["floor_sqft"], need["Floor space (≤2 weeks)"], key)
            self.assertEqual(long["toilets"], need["Toilets (≤2 weeks)"], key)

    @unittest.skipUnless(NODE, "Node.js not installed")
    def test_js_matches_python_for_50_random_input_sets(self):
        rng = random.Random(20261103)
        keys = sorted(W["scenarios"])
        cases = []
        for i in range(50):
            key = keys[i % len(keys)] if i < 20 else rng.choice(keys)
            c, h = key.split("|")
            areas, sites = whatif.areas_for(BUNDLE, c, h)
            cases.append({"key": key, "inp": random_inputs(rng, key, sites), "areas": areas, "sites": sites})
        js = run_js(cases)
        for c, j in zip(cases, js):
            inp = {**c["inp"], "cap": {int(k): v for k, v in c["inp"]["cap"].items()}}
            py = whatif.compute(W, c["key"], inp)
            self.assertEqual(json.loads(json.dumps(py)), j["r"], (c["key"], c["inp"]))
            pa = whatif.allocate(c["areas"], c["sites"], inp, W["scenarios"][c["key"]]["rate"])
            self.assertEqual([(x["f"], x["site"]) for x in pa["areas"]], [(x["f"], x["site"]) for x in j["a"]["areas"]])
            for x, y in zip(pa["areas"], j["a"]["areas"]):
                self.assertAlmostEqual(x["people"], y["people"], places=9)
            self.assertEqual([(s["id"], s["cap"], s["over"]) for s in pa["sites"]],
                             [(s["id"], s["cap"], s["over"]) for s in j["a"]["sites"]], c["key"])
            self.assertEqual((pa["over_sites"], pa["shortfall"]), (j["a"]["over_sites"], j["a"]["shortfall"]))
            self.assertAlmostEqual(pa["unassigned"], j["a"]["unassigned"], places=6)

    @unittest.skipUnless(NODE, "Node.js not installed")
    def test_defaults_reproduce_plan_numbers_js(self):
        cases = []
        for key in sorted(W["scenarios"]):
            c, h = key.split("|")
            areas, sites = whatif.areas_for(BUNDLE, c, h)
            cases.append({"key": key, "inp": {"rate": W["scenarios"][key]["rate"], "stay": 3, "outage": 0,
                                              "trip": W["defaults"]["people_per_trip"], "support": None, "cap": {}},
                          "areas": areas, "sites": sites})
        for c, j in zip(cases, run_js(cases)):
            need = {n[0]: n[1] for n in BUNDLE["scenarios"][c["key"]]["needs"]}
            self.assertEqual(j["r"]["cots"], need["Cots / sleeping space"], c["key"])
            self.assertEqual(j["r"]["staff_total"], need["Shelter staff"], c["key"])
            self.assertEqual(j["r"]["people_in_shelter"], BUNDLE["scenarios"][c["key"]]["summary"]["shelter_demand_central"])
            self.assertEqual(j["q"], {}, c["key"])                    # defaults: nothing in the URL

    @unittest.skipUnless(NODE, "Node.js not installed")
    def test_url_round_trip(self):
        rng = random.Random(7)
        cases = []
        for key in sorted(W["scenarios"])[:10]:
            c, h = key.split("|")
            areas, sites = whatif.areas_for(BUNDLE, c, h)
            cases.append({"key": key, "inp": random_inputs(rng, key, sites), "areas": [], "sites": sites})
        for c, j in zip(cases, run_js(cases)):
            back = j["back"]
            for k in ("rate", "stay", "outage", "trip", "support"):
                self.assertEqual(back[k], c["inp"][k], (c["key"], k))
            self.assertEqual({int(k): v for k, v in back["cap"].items()}, c["inp"]["cap"])

    def test_same_island_allocation(self):
        sites = {s["id"]: s for s in BUNDLE["sites"]}
        for key in W["scenarios"]:
            c, h = key.split("|")
            areas, s = whatif.areas_for(BUNDLE, c, h)
            a = whatif.allocate(areas, s, {"rate": 0.05, "cap": {}}, W["scenarios"][key]["rate"])
            isl = {t["f"]: t["island"] for t in areas}
            for x in a["areas"]:
                if x["site"] is not None:
                    self.assertEqual(sites[x["site"]]["island"], isl[x["f"]], (key, x["f"]))
                    self.assertEqual(sites[x["site"]]["status"][h][0], "ok")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Serve:
    def __init__(self, port: int):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(APP))
        handler.log_message = lambda *a: None
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def views(port: int, opt: dict) -> dict:
    out = subprocess.run([NODE, str(ROOT / "tests" / "views_check.mjs"), BROWSER, json.dumps(opt)],
                         capture_output=True, text=True, timeout=600)
    return json.loads(out.stdout)


@unittest.skipUnless(BROWSER and NODE, "Chrome/Chromium or Node.js not installed")
class Browser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = Serve(cls.port)
        b = f"http://127.0.0.1:{cls.port}/"
        cls.urls = ([f"{b}?county={c}&hazard=tsunami#stress" for c in COUNTIES] +
                    [f"{b}?county={c}&hazard={h}#whatif" for c, h in
                     (("Maui", "wildfire"), ("Honolulu", "hurricane"), ("Kauai", "coastal_flood"), ("Hawaii", "tsunami"))] +
                    [f"{b}?county=Honolulu&hazard=tsunami#plan", f"{b}?county=Maui&hazard=wildfire#plan",
                     f"{b}?county=Honolulu&hazard=coastal_flood#plan"])
        cls.light = views(cls.port, {"urls": cls.urls, "width": 390, "scheme": "light"})["online"]
        cls.dark = views(cls.port, {"urls": cls.urls[:6], "width": 1280, "scheme": "dark"})["online"]

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def test_no_errors_no_outside_requests(self):
        for v in self.light + self.dark:
            self.assertEqual(v["errors"], [], v["url"])
            self.assertEqual(v["outside"], [], v["url"])

    def test_no_bad_values_in_any_view(self):
        for v in self.light + self.dark:
            self.assertEqual(v["bad"], [], v["url"])
            self.assertIn("Planning aid. Supports, does not replace, county emergency plans. Not an official shelter list.",
                          v["disclaimer"], v["url"])

    def test_works_at_390_px(self):
        for v in self.light:
            self.assertFalse(v["overflow"], v["url"])

    def test_light_and_dark_render(self):
        self.assertEqual(self.light[0]["bg"], "rgb(253, 251, 246)")           # --color-bg, light
        self.assertEqual(self.dark[0]["bg"], "rgb(27, 25, 21)")               # --color-bg, dark
        for v in self.light[:8] + self.dark:
            self.assertTrue(any("Stress tests" in h or "What-if" in h for h in v["h2"]), v["url"])

    def test_labels_and_layers(self):
        text = {v["url"]: v["text"] for v in self.light}
        for u, t in text.items():
            if u.endswith("#stress"):
                self.assertIn("Stress test, not a forecast", t)
                self.assertIn("Questions for counties", t)
                self.assertIn("Show on the map", t)
            if u.endswith("#whatif"):
                self.assertIn("What-if, not a forecast", t)
                self.assertIn("How this is calculated", t)
                self.assertIn("Reset to plan defaults", t)
        self.assertIn("Tsunami Safe Zones", text[self.urls[8]])
        self.assertIn("State Fire Risk Areas", text[self.urls[9]])
        self.assertIn("sea-level-rise scenario (3.2 ft; State of Hawaiʻi SLR-XA)", text[self.urls[10]])

    def test_whatif_url_restores_inputs(self):
        b = f"http://127.0.0.1:{self.port}/"
        after = ("[document.getElementById('wi-rate').value, document.getElementById('wi-stay').value,"
                 " document.getElementById('wi-outage').value, document.getElementById('cap-13').value,"
                 " document.getElementById('wi-shortfall').textContent, location.search].join('|')")
        v = views(self.port, {"urls": [f"{b}?county=Maui&hazard=hurricane&rate=0.08&stay=7&outage=3&cap=13-2078#whatif"],
                              "after": after})["online"][0]
        rate, stay, outage, cap, short, search = v["after"].split("|")
        self.assertEqual((rate, stay, outage, cap), ("8", "7", "3", "2078"))
        self.assertIn("shortfall", short)
        self.assertIn("rate=0.08", search)

    def test_offline_after_one_visit(self):
        port = free_port()
        b = f"http://127.0.0.1:{port}/"
        urls = [f"{b}?county=Maui&hazard=tsunami#stress", f"{b}?county=Maui&hazard=tsunami#whatif"]
        with tempfile.TemporaryDirectory() as prof:
            server = Serve(port)
            try:
                for _ in range(2):                      # install the service worker, fill the cache
                    subprocess.run([BROWSER, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={prof}",
                                    "--virtual-time-budget=30000", "--dump-dom", urls[0]], capture_output=True, timeout=180)
            finally:
                server.stop()
            doms = [subprocess.run([BROWSER, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={prof}",
                                    "--virtual-time-budget=10000", "--dump-dom", u], capture_output=True, text=True,
                                   timeout=180).stdout for u in urls]
        self.assertIn("Stress tests – what could break: Maui", doms[0])
        self.assertIn("What-if: change the planning numbers", doms[1])
        self.assertIn("People who may need a public shelter", doms[1])


if __name__ == "__main__":
    unittest.main()
