"""Render every app view in headless Chrome (local server, no outside requests) and check
the visible text: no "null"/"undefined"/"NaN", no file paths or code words. The PDF text
gets the same code-word check. Skipped when Chrome or pdftotext is not installed."""
import functools
import html
import http.server
import re
import shutil
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
from fetch_data import COUNTIES  # noqa: E402
from model_needs import HAZARDS  # noqa: E402

APP = ROOT / "app"
BROWSER = bp.find_browser()
BAD_VALUES = re.compile(r"\b(null|undefined|NaN)\b")
CODE_WORDS = re.compile(
    r"\b(?:data|config|scripts|app|playbooks|tests)/[\w./-]+"      # repo paths
    r"|\w+\.(?:json|csv|py|geojson)\b"                             # file names
    r"|PLAN\.md|team_assumption"
    r"|\b[a-z]+_[a-z]+(?:_[a-z]+)*\b")                             # snake_case ids


def visible_text(dom: str) -> str:
    dom = re.sub(r"(?s)<(script|style|noscript)[^>]*>.*?</\1>", " ", dom)
    return html.unescape(re.sub(r"<[^>]+>", " ", dom))


@unittest.skipUnless(BROWSER, "Chrome/Chromium not installed")
class RenderedViews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(APP))
        handler.log_message = lambda *a: None
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{cls.server.server_address[1]}/"
        urls = [f"{base}?county={c}&hazard={h}" for c in COUNTIES for h in HAZARDS]
        urls.append(f"{base}#messages")
        with ThreadPoolExecutor(max_workers=6) as pool:
            cls.pages = dict(zip(urls, pool.map(cls.dump, urls)))

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    @staticmethod
    def dump(url: str) -> str:
        with tempfile.TemporaryDirectory() as profile:
            out = subprocess.run(
                [BROWSER, "--headless=new", "--disable-gpu", "--no-first-run",
                 f"--user-data-dir={profile}", "--virtual-time-budget=10000", "--dump-dom", url],
                capture_output=True, text=True, timeout=120)
        return out.stdout

    def test_all_views_rendered(self):
        self.assertEqual(len(self.pages), 21)
        for url, dom in self.pages.items():
            text = visible_text(dom)
            self.assertIn("Data version", text, url)
            self.assertIn("Messages" if url.endswith("#messages") else "Results", text, url)

    def test_no_null_undefined_nan(self):
        for url, dom in self.pages.items():
            hits = BAD_VALUES.findall(visible_text(dom))
            self.assertEqual(hits, [], url)

    def test_no_file_paths_or_code_words(self):
        for url, dom in self.pages.items():
            hits = sorted(set(CODE_WORDS.findall(visible_text(dom))))
            self.assertEqual(hits, [], url)


@unittest.skipUnless(shutil.which("pdftotext"), "pdftotext not installed")
class PdfText(unittest.TestCase):
    def test_no_file_paths_or_code_words(self):
        for pdf in sorted((ROOT / "playbooks").glob("*.pdf")):
            text = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True,
                                  check=True).stdout
            text = re.sub(r"https?://\S+", " ", text)                  # source links are fine
            hits = sorted(set(CODE_WORDS.findall(text)))
            self.assertEqual(hits, [], pdf.name)


class DecisionRows(unittest.TestCase):
    def test_before_during_after_for_every_hazard(self):
        import json
        dp = json.loads((ROOT / "config" / "decision_points.json").read_text(encoding="utf-8"))
        bundle = json.loads((APP / "data" / "bundle.json").read_text(encoding="utf-8"))
        for hz, rows in dp["decision_points"].items():
            self.assertTrue({"before", "during", "after"} <= {r["timing"] for r in rows}, hz)
            self.assertTrue({"before", "during", "after"} <=
                            {d[0] for d in bundle["decision_points"][hz]}, hz)
        hur = [d for d in bundle["decision_points"]["hurricane"] if d[0] == "during"]
        self.assertEqual(hur[0][1], "Hurricane conditions / county shelter-in-place order")
        cf = [d for d in bundle["decision_points"]["coastal_flood"] if d[0] == "during"]
        self.assertEqual(cf[0][1], "Coastal Flood Warning in effect")
        self.assertIn("Use inland sites only", cf[0][3])
        for p in (ROOT / "playbooks").glob("*_hurricane.html"):
            self.assertIn("Hurricane conditions / county shelter-in-place order",
                          p.read_text(encoding="utf-8"))

    def test_who_else_items(self):
        for k in ("Caregivers and personal care attendants", "Behavioral health", "Niʻihau",
                  "Families afraid to seek shelter (including immigrant families)"):
            self.assertIn(k, [w[0] for w in bp.WHO_ELSE])
            for p in (ROOT / "playbooks").glob("*.html"):
                if p.name != "index.html":
                    self.assertIn(k, p.read_text(encoding="utf-8"), p.name)

    def test_results_in_every_pdf(self):
        if not shutil.which("pdftotext"):
            self.skipTest("pdftotext not installed")
        for pdf in sorted((ROOT / "playbooks").glob("*.pdf")):
            text = " ".join(subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True,
                                           text=True, check=True).stdout.split())
            self.assertIn("9. Results", text, pdf.name)
            self.assertIn("calibration event, not validation", text, pdf.name)


class ResultsWithoutTime(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext not installed")
    def test_results_show_coverage_and_backtest_not_time(self):
        """Results: Coverage and Backtest only. The rebuild time stays in PLAN.md §6."""
        pdfs = sorted((ROOT / "playbooks").glob("*.pdf"))
        self.assertEqual(len(pdfs), 20)
        for pdf in pdfs:
            text = " ".join(subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True,
                                           text=True, check=True).stdout.split())
            results = text.split("9. Results", 1)[1]
            self.assertIn("Coverage:", results, pdf.name)
            self.assertIn("Backtest –", results, pdf.name)
            self.assertNotIn("Time:", results, pdf.name)
            self.assertNotIn("full rebuild from local data", results, pdf.name)
            self.assertNotIn("Team-assumed baseline", results, pdf.name)
        js = (APP / "app.js").read_text(encoding="utf-8")
        section = js.split("function resultsSection()", 1)[1].split("\n}\n", 1)[0]
        self.assertIn('"Coverage: "', section)
        self.assertIn("Backtest", section)
        self.assertNotIn("Time", section)
        self.assertNotIn("r.rebuild", section)


class CssMobile(unittest.TestCase):
    def test_targets_and_sizes(self):
        css = (APP / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".site-footer li a { display: inline-flex; align-items: center; min-height: 44px;", css)
        self.assertIn(".results small { font-size: var(--font-size-small); }", css)
        self.assertIn(".dataver { min-height:", css)
        self.assertIn("li a { display: inline-flex; align-items: center; min-height: 44px; }", css)
        index = (APP / "index.html").read_text(encoding="utf-8")
        self.assertIn('<div class="skeleton" aria-hidden="true">', index)


if __name__ == "__main__":
    unittest.main()
