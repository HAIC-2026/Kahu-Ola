"""Small-number suppression, per-area citations and margins of error.

No per-area count from 1 to 9 is shown anywhere a reader can see it: the rendered app (plan
views, area panels, stress tests, what-if), the playbook HTML and PDFs and the stress-test
annexes. Census areas under 100 residents show the population only. Every per-area table
names its ACS table and years; margins of error come from the source (none invented).
Python (scripts/privacy.py) and JavaScript (app/app.js cnt) apply the same rule."""
import functools
import html
import http.server
import json
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
import privacy  # noqa: E402
import stress_text  # noqa: E402
from fetch_data import COUNTIES  # noqa: E402
from model_needs import HAZARDS  # noqa: E402

APP = ROOT / "app"
PLAY = ROOT / "playbooks"
BUNDLE = json.loads((APP / "data" / "bundle.json").read_text(encoding="utf-8"))
JS = (APP / "app.js").read_text(encoding="utf-8")
SMALL_SHOWN = re.compile(r"^[1-9](?: ± [\d,]+)?$")          # a count 1-9, with or without ±
AC = re.compile(r'<span class="ac">([^<]*)</span>')
NODE = shutil.which("node")
BROWSER = bp.find_browser()
HTMLS = sorted(PLAY.glob("*_*.html")) + sorted((PLAY / "annex").glob("*.html"))


class Rule(unittest.TestCase):
    CASES = [(0, None, "0"), (0.4, None, "fewer than 10"), (1, None, "fewer than 10"), (9.4, None, "fewer than 10"),
             (9.5, None, "10"), (10, None, "10"), (1234.4, None, "1,234"), (None, None, "–"),
             (500, 99, "suppressed (small area)"), (0, 50, "suppressed (small area)"), (12, 100, "12")]

    def test_python_rule(self):
        for v, pop, want in self.CASES:
            self.assertEqual(privacy.count_text(v, pop), want, (v, pop))
        self.assertEqual(privacy.with_moe(96, 41.2), "96 ± 41")
        self.assertEqual(privacy.with_moe(5, 41), "fewer than 10")          # MOE hidden with its count
        self.assertEqual(privacy.with_moe(96, None), "96")                  # none invented

    @unittest.skipUnless(NODE, "Node.js not installed")
    def test_javascript_rule_matches(self):
        src = re.search(r"function cnt\(v, pop\) \{.*?\n\}", JS, re.S).group(0)
        meta = json.dumps({"suppress": BUNDLE["meta"]["suppress"]})
        cases = json.dumps([[v, pop] for v, pop, _w in self.CASES])
        prog = f"const DATA = {{meta: {meta}}};\n{src}\nconsole.log(JSON.stringify({cases}.map(([v, p]) => cnt(v, p === null ? undefined : p))));"
        out = json.loads(subprocess.run([NODE, "-e", prog], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out, [w for _v, _p, w in self.CASES])


class Generated(unittest.TestCase):
    def test_no_small_count_in_playbook_and_annex_html(self):
        self.assertEqual(len(HTMLS), 24)
        for p in HTMLS:
            cells = AC.findall(p.read_text(encoding="utf-8"))
            bad = [c for c in map(html.unescape, cells) if SMALL_SHOWN.match(c)]
            self.assertEqual(bad, [], p.name)
        for p in sorted(PLAY.glob("*_*.html")):     # every per-area cell goes through the rule
            self.assertGreaterEqual(len(AC.findall(p.read_text(encoding="utf-8"))), 40, p.name)

    def test_legend_bounds_never_small(self):
        for p in sorted(PLAY.glob("*_*.html")):
            t = html.unescape(re.sub(r"<[^>]+>", "", p.read_text(encoding="utf-8")))
            self.assertNotRegex(t, r"\((?:\d+|fewer than 10) to [1-9] people\)|\([1-9] to ", p.name)

    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext not installed")
    def test_pdfs_match_html(self):
        for pdf in sorted(PLAY.glob("*.pdf")) + sorted((PLAY / "annex").glob("*.pdf")):
            text = " ".join(subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True,
                                           check=True).stdout.split())
            src = pdf.with_suffix(".html").read_text(encoding="utf-8")
            want = sum(1 for c in AC.findall(src) if html.unescape(c) == privacy.FEWER) + \
                len(re.findall(r"(?<!>)fewer than 10(?! are)", re.sub(r'<span class="ac">[^<]*</span>', "", src)))
            self.assertGreaterEqual(text.count("fewer than 10"), want, pdf.name)
            self.assertNotRegex(text, r"\([1-9] to |to [1-9] people\)", pdf.name)
            if not pdf.parent.name == "annex":
                self.assertIn("Counts under 10 are not shown so no one can be identified", text, pdf.name)

    def test_stress_text_never_shows_small_people_counts(self):
        st = json.loads((ROOT / "data" / "processed" / "stress_tests.json").read_text(encoding="utf-8"))
        for f in st["findings"]:
            for k, v in f["evidence"].items():
                if stress_text.is_people(k) and isinstance(v, (int, float)) and not isinstance(v, bool):
                    self.assertNotRegex(stress_text.value(k, v), r"^[1-9]$", (f["id"], k))
            if f["unit"] == "people" and f["people_affected"] and f["people_affected"] < 10:
                self.assertTrue(stress_text.headline(f).startswith("fewer than 10"), f["id"])

    def test_small_areas_listed(self):
        small = [t for t in BUNDLE["tracts"] if t["n"][0] < privacy.SMALL_AREA]
        self.assertTrue(small)
        self.assertIn("15005031900", [t["f"] for t in small])              # Kalawao (Kalaupapa)


class Citations(unittest.TestCase):
    def test_table_ids_and_years(self):
        cite = BUNDLE["meta"]["cite"]
        for k, table in (("lep", "B16005"), ("disability", "DP02"), ("age65", "S0101"), ("no_car", "DP04"),
                         ("hearing", "B18102"), ("vision", "B18103"), ("cognitive", "B18104"), ("age65_alone", "B09020")):
            self.assertIn(table, cite[k])
            self.assertRegex(cite[k], r"ACS 20(18–2022|20–2024)")
        self.assertIn("no margin of error", cite["power"])
        for p in sorted(PLAY.glob("*_*.html")):
            t = p.read_text(encoding="utf-8")
            for table in ("B16005", "DP02", "S0101", "DP04", "B18102", "B09020"):
                self.assertIn(table, t, p.name)

    def test_moe_from_source_only(self):
        moe = privacy.load_moe()
        self.assertGreaterEqual(sum(1 for v in moe.values() if v["lep"] is not None), 430)
        for t in BUNDLE["tracts"]:
            self.assertEqual(len(t["m"]), 1 + len(BUNDLE["area_fields"]))
            self.assertIsNone(t["m"][1 + BUNDLE["area_fields"].index("power")])   # emPOWER: none
        cells = [c for p in sorted(PLAY.glob("*_*.html")) for c in AC.findall(p.read_text(encoding="utf-8"))]
        self.assertTrue(any(" ± " in c for c in cells))

    def test_privacy_line_everywhere(self):
        line = "Counts under 10 are not shown so no one can be identified."
        self.assertIn(line, (APP / "index.html").read_text(encoding="utf-8"))
        self.assertIn(line, BUNDLE["meta"]["privacy"])
        self.assertIn(line, (PLAY / "maui_tsunami.html").read_text(encoding="utf-8"))
        self.assertIn(line, (ROOT / "PLAN.md").read_text(encoding="utf-8"))


class StressFixes(unittest.TestCase):
    ST = json.loads((ROOT / "data" / "processed" / "stress_tests.json").read_text(encoding="utf-8"))

    def test_counties_together_one_rounding(self):
        for f in self.ST["findings"]:
            if f["test"] == "9":
                e = f["evidence"]
                self.assertEqual(f["people_affected"], e["cots"], f["id"])
                self.assertEqual(e["cots"], e["water_gal_per_day"], f["id"])

    def test_road_headline_both_times(self):
        f = next(x for x in self.ST["findings"] if x["id"] == "T24-flooded_maui-drive")
        self.assertIn("+92 min to any known site; +3.8 min to a 2026 site", stress_text.summary(f))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@unittest.skipUnless(BROWSER, "Chrome/Chromium not installed")
class RenderedApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        port = free_port()
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(APP))
        handler.log_message = lambda *a: None
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        b = f"http://127.0.0.1:{port}/"
        small = sorted({f for sc in BUNDLE["scenarios"].values() for f, v in sc["tracts"].items() if 0 < v[0] < 10})[:4]
        county = {t["f"]: t["c"] for t in BUNDLE["tracts"]}
        hz = {f: next(k.split("|")[1] for k, sc in BUNDLE["scenarios"].items() if f in sc["tracts"] and 0 < sc["tracts"][f][0] < 10)
              for f in small}
        cls.urls = ([f"{b}?county={c}&hazard={h}#plan" for c in COUNTIES for h in HAZARDS] +
                    [f"{b}?county=Maui&hazard=hurricane&area=15005031900#plan"] +
                    [f"{b}?county={county[f]}&hazard={hz[f]}&area={f}#plan" for f in small] +
                    [f"{b}?county={c}&hazard=tsunami#stress" for c in COUNTIES] +
                    [f"{b}?county={c}&hazard=tsunami#whatif" for c in COUNTIES])

        def dump(u):
            with tempfile.TemporaryDirectory() as prof:
                return subprocess.run([BROWSER, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={prof}",
                                       "--virtual-time-budget=12000", "--dump-dom", u], capture_output=True, text=True,
                                      timeout=180).stdout
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=6) as pool:
            cls.doms = dict(zip(cls.urls, pool.map(dump, cls.urls)))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_no_small_count_in_any_view(self):
        for u, dom in self.doms.items():
            self.assertIn("Data version", dom, u)
            bad = [c for c in map(html.unescape, AC.findall(dom)) if SMALL_SHOWN.match(c)]
            self.assertEqual(bad, [], u)

    def test_small_area_panel(self):
        dom = self.doms[self.urls[20]]
        panel = re.search(r'<section id="area-panel".*?</section>', dom, re.S).group(0)
        self.assertIn("suppressed (small area)", panel)
        self.assertNotIn("fewer than 10", re.sub(r"Counts under 10", "", panel))

    def test_small_counts_shown_as_fewer_than_10(self):
        for u in self.urls[21:25]:
            panel = re.search(r'<section id="area-panel".*?</section>', self.doms[u], re.S).group(0)
            self.assertIn("fewer than 10", panel, u)


if __name__ == "__main__":
    unittest.main()
