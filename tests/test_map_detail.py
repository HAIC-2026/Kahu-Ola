"""Interactive map: nearest usable sites, area panel numbers, deep links for all 20 views,
tsunami overlay, no outside requests, offline after one visit, bundle size."""
import csv
import functools
import html
import http.server
import json
import re
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_playbooks as bp  # noqa: E402
from geo import haversine_km, nearest  # noqa: E402

APP = ROOT / "app"
BUNDLE = json.loads((APP / "data" / "bundle.json").read_text(encoding="utf-8"))
JS = (APP / "app.js").read_text(encoding="utf-8")
CSS = (APP / "styles.css").read_text(encoding="utf-8")
BROWSER = bp.find_browser()
TRACTS = {t["f"]: t for t in BUNDLE["tracts"]}


def usable_sites(county: str, hazard: str) -> list:
    """Sites usable for this hazard, numbered like the app (status order, then name)."""
    order = ["ok", "check", "check (tract-level)", "undetermined", "exclude", "unlocated"]
    rows = []
    for s in BUNDLE["sites"]:
        if s["county"] != county:
            continue
        st = s["status"][hazard][0] if hazard in s["status"] else "unlocated"
        rows.append({**s, "st": st})
    rows.sort(key=lambda s: (order.index(s["st"]), s["name"]))
    for i, s in enumerate(rows, 1):
        s["n"] = i
    return [s for s in rows if s["st"] == "ok" and s["lon"] is not None]


def expected_nearest(county: str, hazard: str, fips: str) -> list:
    """Same island only; never a site on another island. By drive time when the ArcGIS
    matrix covers the area, else straight-line distance."""
    island = TRACTS[fips]["i"]
    same = [s for s in usable_sites(county, hazard) if s["island"] == island]
    if TRACTS[fips].get("a"):
        by_id = {s["id"]: s for s in same}
        rows = sorted((r for r in TRACTS[fips]["a"] if r[0] in by_id and r[1] is not None),
                      key=lambda r: (r[1], by_id[r[0]]["name"]))
        return [by_id[r[0]]["name"] for r in rows[:3]]
    return [s["name"] for _km, s in nearest(TRACTS[fips]["p"], same)]


def distance_words(fips: str) -> str:
    return "min drive" if TRACTS[fips].get("a") else "km straight-line, same island"


def nearest_section(dom: str) -> str:
    """The panel part that lists nearest sites (up to the partners line)."""
    p = panel(dom)
    m = re.search(r"<h4>Nearest sites usable.*?(?=<p><strong>Proposed partners)", p, re.S)
    return m.group(0) if m else ""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Serve:
    """Static server for app/ on a fixed port (same origin across runs)."""
    def __init__(self, port: int):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(APP))
        handler.log_message = lambda *a: None
        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def chrome(url: str, profile: str, budget: int = 10000, netlog: str = "") -> str:
    args = [BROWSER, "--headless=new", "--disable-gpu", "--no-first-run",
            f"--user-data-dir={profile}", f"--virtual-time-budget={budget}", "--dump-dom", url]
    if netlog:
        args.insert(-2, f"--log-net-log={netlog}")
    return subprocess.run(args, capture_output=True, text=True, timeout=180).stdout


def panel(dom: str) -> str:
    m = re.search(r'<section id="area-panel".*?</section>', dom, re.S)
    return m.group(0) if m else ""


def text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


class Nearest(unittest.TestCase):
    def test_haversine(self):
        self.assertAlmostEqual(haversine_km(-157.0, 21.0, -157.0, 22.0), 111.2, delta=0.1)
        self.assertEqual(haversine_km(-155.1, 19.7, -155.1, 19.7), 0.0)

    def test_nearest_order_and_ties(self):
        sites = [{"name": "B", "lon": -157.0, "lat": 21.02}, {"name": "A", "lon": -157.0, "lat": 21.02},
                 {"name": "Far", "lon": -156.0, "lat": 21.0}, {"name": "C", "lon": -157.0, "lat": 21.05}]
        got = [s["name"] for _km, s in nearest((-157.0, 21.0), sites)]
        self.assertEqual(got, ["A", "B", "C"])
        self.assertEqual(len(nearest((-157.0, 21.0), sites, k=10)), 4)

    def test_js_uses_same_rules(self):
        self.assertIn("const R = 6371.0088", JS)
        self.assertIn('s.st === "ok" && s.lon !== null && tr.i && s.island === tr.i', JS)
        self.assertIn("km straight-line, same island", JS)
        self.assertIn('s.st === "ok" && s.lon !== null', JS)
        self.assertIn("a.km - b.km || a.s.name.localeCompare(b.s.name)", JS)
        self.assertIn("km straight-line", JS)


class PanelNumbers(unittest.TestCase):
    def test_area_counts_match_model(self):
        with open(ROOT / "data" / "processed" / "needs_by_tract.csv", newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        fields = dict(zip(BUNDLE["area_fields"], range(1, 20)))
        model = {"lep": "C_lep_at_risk", "disability": "I_disability_at_risk",
                 "age65": "I_age65_at_risk", "no_car": "T_no_vehicle_persons_at_risk",
                 "hearing": "C_hearing_at_risk", "age65_alone": "S_age65_alone_at_risk"}
        for r in rows[::25]:
            t = TRACTS.get(r["tract_fips"])
            if not t or not t["n"][0]:
                continue
            share = float(r["at_risk_pop"]) / t["n"][0]
            for k, col in model.items():
                self.assertAlmostEqual(t["n"][fields[k]] * share, float(r[col]),
                                       delta=0.02 * float(r[col]) + 1, msg=(r["tract_fips"], k))


class Islands(unittest.TestCase):
    def test_every_area_and_site_has_an_island(self):
        main = {"Niʻihau", "Kauaʻi", "Oʻahu", "Molokaʻi", "Lānaʻi", "Maui", "Kahoʻolawe", "Hawaiʻi"}
        for t in BUNDLE["tracts"]:
            self.assertIn(t["i"], main, t["f"])
        for s in BUNDLE["sites"]:
            if s["lon"] is not None:
                self.assertIn(s["island"], main, s["name"])
        with open(ROOT / "data" / "sources" / "islands.csv", newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertTrue(all(r["island"] for r in rows))
        self.assertTrue(all(r["source_url"].startswith("https://geodata.hawaii.gov/") for r in rows))
        self.assertEqual(TRACTS["15005031900"]["i"], "Molokaʻi")              # Kalawao

    def test_build_fails_without_an_island(self):
        import build_islands as bi
        square = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
        coast = {"features": [{"properties": {"isle": "Maui"}, "geometry": square}]}
        afn = {"features": [{"properties": {"tract_fips": "1", "county": "Maui"}, "geometry": square}]}
        sites = {"features": [{"properties": {"name": "At sea", "county": "Maui"},
                               "geometry": {"type": "Point", "coordinates": [5.0, 5.0]}}]}
        rows, missing = bi.assign(afn, sites, coast)
        self.assertEqual(rows[0]["island"], "Maui")
        self.assertEqual(missing, ["site At sea"])


class Overlay(unittest.TestCase):
    def test_tsunami_zone_built_in_and_small(self):
        zone = BUNDLE["tsunami_zone"]
        self.assertEqual(set(zone), {"Honolulu", "Hawaii", "Maui", "Kauai"})
        size = len(json.dumps(zone, separators=(",", ":")))
        self.assertLess(size, 150_000)
        self.assertLess((APP / "data" / "bundle.json").stat().st_size, 782_422 + 150 * 1024)
        self.assertIn('hazard === "tsunami" ? (DATA.tsunami_zone[county] || []) : []', JS)

    def test_official_map_is_a_plain_link(self):
        om = BUNDLE["official_map"]
        self.assertTrue(om["url"].startswith("https://geoportal.hawaii.gov/"))
        self.assertIn('target: "_blank", rel: "noopener noreferrer"', JS)
        self.assertNotRegex(JS, r"https?://(?!www\.w3\.org/2000/svg)")   # URL lives in the data
        self.assertEqual(re.findall(r"fetch\(([^)]*)\)", JS),
                         ['VERSION_URL, { cache: "no-store" }', "BUNDLE_URL"])

    def test_panel_accessibility_rules(self):
        self.assertIn('role: "region", "aria-labelledby": "area-title"', JS)
        self.assertIn('document.getElementById("area-title").focus()', JS)
        self.assertIn("back.focus()", JS)
        self.assertIn('matchMedia("(prefers-reduced-motion: reduce)")', JS)
        self.assertIn("Need level: ${MAP.level(f)}", JS)                  # severity in words
        self.assertIn("button.linklike { min-height: 44px;", CSS)
        self.assertIn(".area-panel a, .map + p a, p > a.button { display: inline-flex; align-items: center; min-height: 44px; }", CSS)
        self.assertIn("body.print-area #area-panel", CSS)


@unittest.skipUnless(BROWSER, "Chrome/Chromium not installed")
class DeepLinks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        cls.server = Serve(cls.port)
        cls.base = f"http://127.0.0.1:{cls.port}/"
        cls.cases = []
        for key, sc in BUNDLE["scenarios"].items():
            county, hazard = key.split("|")
            fips = sc["priority_tracts"][0]["tract_fips"]
            cls.cases.append((county, hazard, fips))

        def run(case):
            county, hazard, fips = case
            with tempfile.TemporaryDirectory() as prof:
                return chrome(f"{cls.base}?county={county}&hazard={hazard}&area={fips}", prof)
        # Molokaʻi (Kalaupapa, Kalawao), Lānaʻi and Niʻihau areas
        cls.extra = [("Maui", "hurricane", "15005031900"), ("Maui", "tsunami", "15009031601"),
                     ("Kauai", "hurricane", "15007041200")]
        with ThreadPoolExecutor(max_workers=6) as pool:
            cls.doms = list(pool.map(run, cls.cases))
            cls.extra_doms = list(pool.map(run, cls.extra))

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def test_no_site_from_another_island(self):
        for (county, hazard, fips), dom in zip(self.cases + self.extra, self.doms + self.extra_doms):
            section = text(nearest_section(dom))
            self.assertTrue(section, (county, hazard, fips))
            island = TRACTS[fips]["i"]
            for s in BUNDLE["sites"]:
                if s["island"] != island:
                    self.assertNotIn(s["name"], section, (county, hazard, fips, s["name"]))
            want = expected_nearest(county, hazard, fips)
            if island == "Niʻihau":
                self.assertIn("privately owned", section.lower())
            elif not want:
                self.assertIn("No known usable site on this island for this hazard", section)
            else:
                self.assertIn(distance_words(fips), section)

    def test_molokai_lanai_niihau_cases(self):
        got = {TRACTS[f]["i"] for _c, _h, f in self.extra}
        self.assertEqual(got, {"Molokaʻi", "Lānaʻi", "Niʻihau"})
        for (county, hazard, fips), dom in zip(self.extra, self.extra_doms):
            section = text(nearest_section(dom))
            for name in expected_nearest(county, hazard, fips):
                self.assertIn(name, section)

    def test_all_20_views_open_the_area_panel(self):
        self.assertEqual(len(self.cases), 20)
        for (county, hazard, fips), dom in zip(self.cases, self.doms):
            p = text(panel(dom))
            main = TRACTS[fips]["l"].split(" · ")[0]
            self.assertIn(main, p, (county, hazard))
            self.assertIn("Need level:", p)
            for name in expected_nearest(county, hazard, fips):
                self.assertIn(name, p, (county, hazard, fips))
            if expected_nearest(county, hazard, fips):
                self.assertIn(distance_words(fips), p)

    def test_nearest_order_matches_python(self):
        for (county, hazard, fips), dom in zip(self.cases, self.doms):
            p = text(panel(dom))
            want = expected_nearest(county, hazard, fips)
            pos = [p.index(n) for n in want]
            self.assertEqual(pos, sorted(pos), (county, hazard, fips))

    def test_tsunami_overlay_only_for_tsunami(self):
        for (county, hazard, fips), dom in zip(self.cases, self.doms):
            self.assertEqual('class="tsunami-zone"' in dom, hazard == "tsunami", (county, hazard))

    def test_no_outside_requests(self):
        with tempfile.TemporaryDirectory() as prof:
            log = str(Path(prof) / "net.json")
            chrome(f"{self.base}?county=Maui&hazard=tsunami&area={self.cases[0][2]}", prof, netlog=log)
            events = json.loads(Path(log).read_text(encoding="utf-8"))["events"]
        origin = self.base.rstrip("/")
        page = {e["params"]["url"] for e in events
                if e.get("params", {}).get("initiator") == origin and "url" in e["params"]}
        self.assertTrue(page)
        self.assertEqual([u for u in page if not u.startswith(origin)], [])


@unittest.skipUnless(BROWSER, "Chrome/Chromium not installed")
class Offline(unittest.TestCase):
    def test_works_offline_after_one_visit(self):
        port = free_port()
        url = f"http://127.0.0.1:{port}/?county=Maui&hazard=wildfire"
        with tempfile.TemporaryDirectory() as prof:
            server = Serve(port)
            try:
                for _ in range(2):                      # install the service worker, fill the cache
                    chrome(url, prof, budget=30000)
            finally:
                server.stop()
            dom = chrome(url, prof)                     # server is down: offline
        t = text(re.sub(r"(?s)<(script|style|noscript)[^>]*>.*?</\1>", " ", dom))
        for word in ("Maui – Wildfire", "Data version", "Results", "Site key"):
            self.assertIn(word, t)


if __name__ == "__main__":
    unittest.main()
