"""No per-area value from 1 to 9 exists in any file served from app/, and what people see did
not change when the per-area computation moved to build time.

Served files: every JSON under app/data (bundle, stress tests and what-if, area panels,
messages), the JavaScript and HTML, the CSV exports the app builds, and the text of every PDF
under app/playbooks. A per-area count field holds a number of 10 or more, 0, the marker
"lt10", or nothing (areas with fewer than 100 residents ship their population only).

Rendered views are compared with a reference (tests/golden/views_before.json.gz, see
tests/render_views.py). It was first rendered before the change; the only difference then was
the one the rules require: in the what-if panel, a per-area or per-site value that is
"fewer than 10" at the plan rate reads "fewer than 10 at plan rates" when a slider raises the
rate (its true value is not shipped, so it cannot be re-checked). The reference was
regenerated when the privacy line was reworded, and now includes that rule, so every view
must match it exactly."""
import json
import math
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import area_view  # noqa: E402
import build_playbooks as bp  # noqa: E402

APP = ROOT / "app"
DATA = APP / "data"
BROWSER = bp.find_browser()
NODE = shutil.which("node")
LOAD = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in sorted(DATA.glob("*.json"))}
COUNT_KEYS = set(area_view.LARGEST) | set(area_view.PRIORITY) | {"at_risk_plain"}


def bad(x) -> bool:
    """A number that would show as a count from 1 to 9."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x > 0 and math.floor(x + 0.5) < 10


def bad_cell(c) -> bool:
    if isinstance(c, list):
        return bad(c[0]) or (len(c) > 1 and not isinstance(c[0], int))   # an MOE only with a shown count
    return bad(c)


class ServedJson(unittest.TestCase):
    def test_files(self):
        self.assertEqual(sorted(LOAD), ["areas.json", "bundle.json", "messages.json", "stress.json", "version.json"])

    def test_bundle_has_no_raw_per_area_counts(self):
        b = LOAD["bundle.json"]
        for t in b["tracts"]:
            self.assertFalse({"n", "m"} & set(t), t["f"])                 # no whole-area count arrays
            self.assertFalse(bad(t["pop"]), t["f"])
        for key, sc in b["scenarios"].items():
            self.assertNotIn("tracts", sc, key)
            self.assertEqual([x for x in sc["map"]["bounds"] if bad(x)], [], key)
            self.assertEqual([r for r in sc["map"]["in"] if bad(r[2])], [], key)
            for row in sc["largest"] + sc["priority_tracts"]:
                for k in COUNT_KEYS & set(row):
                    self.assertFalse(bad_cell(row[k]), (key, row.get("tract_fips"), k))

    def test_area_panels(self):
        a = LOAD["areas.json"]
        for f, cells in a["w"].items():
            self.assertEqual([c for c in cells if bad_cell(c)], [], f)
        for key, areas in a["s"].items():
            for f, (at, likely, cells) in areas.items():
                self.assertFalse(bad_cell(at) or bad_cell(likely), (key, f))
                self.assertEqual([c for c in cells if bad_cell(c)], [], (key, f))
        small = [t["f"] for t in LOAD["bundle.json"]["tracts"] if t["pop"] < 100]
        self.assertTrue(small)
        for f in small:                                                    # population only
            self.assertNotIn(f, a["w"])
            self.assertFalse(any(f in v for v in a["s"].values()), f)

    def test_stress_and_whatif(self):
        s = LOAD["stress.json"]
        for r in s["stress"]["rows"]:
            if r[1] not in ("19", "22"):                                   # facilities are not people
                self.assertFalse(bad(r[5]), r[0])
        for key, w in s["whatif"]["areas"].items():
            for f, (people, nc) in w["areas"].items():
                self.assertFalse(bad(people) or bad(nc), (key, f))
            self.assertEqual([k for k, v in w["load"].items() if bad(v)], [], key)
            self.assertFalse(bad(w["unassigned"]), key)

    def test_no_count_field_anywhere_holds_a_small_value(self):
        def walk(x, path=""):
            if isinstance(x, dict):
                for k, v in x.items():
                    if k in COUNT_KEYS:
                        self.assertFalse(bad_cell(v), f"{path}.{k}")
                    walk(v, f"{path}.{k}")
            elif isinstance(x, list):
                for i, v in enumerate(x):
                    walk(v, f"{path}[{i}]")
        for name, data in LOAD.items():
            walk(data, name)

    def test_code_and_html_carry_no_data(self):
        for p in [*APP.glob("*.js"), *APP.glob("*.html")]:
            t = p.read_text(encoding="utf-8")
            self.assertNotRegex(t, r"sc\.tracts|\.n\[|tr\.m\b", p.name)    # no raw per-area arrays read
        self.assertNotRegex((APP / "index.html").read_text(encoding="utf-8"), r"\b[1-9] people\b")


@unittest.skipUnless(shutil.which("pdftotext"), "pdftotext not installed")
class ServedPdfs(unittest.TestCase):
    def test_pdf_text(self):
        pdfs = sorted((APP / "playbooks").rglob("*.pdf")) or sorted((ROOT / "playbooks").rglob("*.pdf"))
        self.assertGreaterEqual(len(pdfs), 24)
        for pdf in pdfs:
            t = " ".join(subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True,
                                        check=True).stdout.split())
            self.assertNotRegex(t, r"(?<![\d,.])[1-9] ± \d", pdf.name)               # a shown count with its MOE
            self.assertNotRegex(t, r"\((?:\d[\d,]*|fewer than 10) to [1-9] people\)|\([1-9] to ", pdf.name)


@unittest.skipUnless(BROWSER, "Chrome/Chromium not installed")
class RenderedUnchanged(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import render_views as rv
        cls.golden = rv.load_golden()
        cls.now = rv.render(APP, rv.views([tuple(x) for x in cls.golden["panels"]]))

    def test_same_views(self):
        self.assertEqual(sorted(self.now), sorted(self.golden["texts"]))

    def test_text_identical(self):
        changed = [k for k, before in sorted(self.golden["texts"].items()) if self.now[k] != before]
        self.assertEqual(changed, [])

    def test_whatif_rule_in_reference(self):
        # a value "fewer than 10" at the plan rate is not scaled when a slider raises the rate
        self.assertIn("fewer than 10 at plan rates",
                      self.golden["texts"]["whatif county=Hawaii&hazard=tsunami&outage=5&rate=0.08"])
        self.assertFalse(any("at plan rates" in v and "rate=" not in k for k, v in self.golden["texts"].items()
                             if k.startswith("whatif ")))


@unittest.skipUnless(BROWSER and NODE, "Chrome/Chromium or Node.js not installed")
class CsvExports(unittest.TestCase):
    """The CSV files the app builds (stress tests, what-if) carry no per-area count 1-9."""
    CAPTURE = ("(async () => { const out = []; window.downloadCsv = (n, rows) => out.push(rows); downloadCsv = window.downloadCsv;"
               " for (const b of document.querySelectorAll('button')) if (/CSV/.test(b.textContent)) b.click();"
               " await new Promise((r) => setTimeout(r, 300)); return JSON.stringify(out); })()")

    def test_csv(self):
        import functools
        import http.server
        import threading
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]

        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Quiet, directory=str(APP)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            b = f"http://127.0.0.1:{port}/"
            urls = [f"{b}?county={c}&hazard=tsunami#whatif" for c in ("Honolulu", "Maui", "Hawaii", "Kauai")] + \
                   [f"{b}?county={c}&hazard=tsunami&rate=0.2#whatif" for c in ("Honolulu", "Hawaii")] + \
                   [f"{b}?county={c}&hazard=tsunami#stress" for c in ("Honolulu", "Maui", "Hawaii", "Kauai")]
            out = subprocess.run([NODE, str(ROOT / "tests" / "views_check.mjs"), BROWSER,
                                  json.dumps({"urls": urls, "after": self.CAPTURE})], capture_output=True, text=True, timeout=600)
            res = json.loads(out.stdout)["online"]
        finally:
            server.shutdown()
        n = 0
        for v in res:
            for rows in json.loads(v["after"]):
                n += 1
                head = next((i for i, r in enumerate(rows) if r and r[0] in ("Census area", "Rank in county")), None)
                self.assertIsNotNone(head, v["url"])
                col = 1 if rows[head][0] == "Census area" else 6        # people in shelter / Number
                for r in rows[head + 1:]:
                    if rows[head][0] == "Rank in county" and r[2] in ("19", "22"):
                        continue
                    self.assertNotRegex(str(r[col]), r"^[1-9]$", (v["url"], r[:3]))
        self.assertGreaterEqual(n, 10)


if __name__ == "__main__":
    unittest.main()
