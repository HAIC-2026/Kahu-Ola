"""Lahaina-area Census areas (community label names Lahaina) carry the pre-fire population
note wherever they are named: app views, area panel, PDFs; Maui summary line."""
import csv
import re
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
import build_playbooks as bp  # noqa: E402
from test_map_detail import Serve, chrome, free_port, panel, text  # noqa: E402

NOTE = bp.LAHAINA_NOTE
with open(ROOT / "data" / "sources" / "tract_communities.csv", newline="", encoding="utf-8") as fh:
    LAHAINA = {r["tract_fips"]: r for r in csv.DictReader(fh) if bp.is_lahaina(r["label_main"])}
# every way a Lahaina area is named: "Census area 314.02" (tables, panel, lists) or
# "Lahaina (314.02, …)" (grouped list in the PDFs)
NAMED = re.compile("|".join([rf"{re.escape(r['label_sub'])}(?![\d.])" for r in LAHAINA.values()]
                            + [r"\bLahaina \((?=\d)"]))
WINDOW = 400


def unnoted(t: str) -> list:
    """Places where a Lahaina area is named without the note within WINDOW characters."""
    return [t[max(0, m.start() - 40):m.end() + 60] for m in NAMED.finditer(t)
            if NOTE not in t[m.start():m.end() + WINDOW]]


class Rule(unittest.TestCase):
    def test_lahaina_areas_from_labels(self):
        self.assertEqual(sorted(r["tract_number"] for r in LAHAINA.values()), ["314.02", "314.04", "314.05"])
        self.assertTrue(all(r["county"] == "Maui" for r in LAHAINA.values()))

    def test_note_text(self):
        self.assertEqual(NOTE, "Population is from the 2020 Census, before the August 2023 Lahaina "
                               "fire, which destroyed much of the town. Use current County of Maui "
                               "figures for Lahaina.")


class Pdfs(unittest.TestCase):
    def test_every_pdf_naming_lahaina_shows_note(self):
        named = 0
        for p in sorted((ROOT / "playbooks").glob("*_*.html")):
            t = text(p.read_text(encoding="utf-8"))
            if NAMED.search(t):
                named += 1
                self.assertEqual(unnoted(t), [], p.name)
        self.assertGreater(named, 0)

    def test_maui_pdfs_summary_line(self):
        for p in sorted((ROOT / "playbooks").glob("maui_*.html")):
            self.assertIn(bp.LAHAINA_SUMMARY, text(p.read_text(encoding="utf-8")), p.name)
        for p in sorted((ROOT / "playbooks").glob("honolulu_*.html")):
            self.assertNotIn(bp.LAHAINA_SUMMARY, text(p.read_text(encoding="utf-8")), p.name)

    def test_site_rows_not_tagged(self):
        t = (ROOT / "playbooks" / "maui_tsunami.html").read_text(encoding="utf-8")
        row = re.search(r"<tr>(?:(?!</tr>).)*Lahaina Civic Center Gym(?:(?!</tr>).)*</tr>", t, re.S).group(0)
        self.assertNotIn(NOTE, row)


@unittest.skipUnless(bp.find_browser(), "Chrome/Chromium not installed")
class App(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        port = free_port()
        cls.server = Serve(port)
        base = f"http://127.0.0.1:{port}/"
        cls.urls = [f"{base}?county=Maui&hazard={h}" for h in
                    ("hurricane", "wildfire", "tsunami", "inland_flood", "coastal_flood")]
        cls.panels = [f"{base}?county=Maui&hazard={h}&area={f}" for f in LAHAINA for h in ("tsunami", "wildfire")]

        def run(u):
            with tempfile.TemporaryDirectory() as prof:
                return chrome(u, prof)
        with ThreadPoolExecutor(max_workers=6) as pool:
            cls.views = list(pool.map(run, cls.urls))
            cls.panel_doms = list(pool.map(run, cls.panels))

    @classmethod
    def tearDownClass(cls):
        cls.server.stop()

    def test_every_maui_view_naming_lahaina_shows_note(self):
        for u, dom in zip(self.urls, self.views):
            t = text(re.sub(r"(?s)<(script|style|noscript)[^>]*>.*?</\1>", " ", dom))
            self.assertTrue(NAMED.search(t), u)              # the area list names them
            self.assertEqual(unnoted(t), [], u)
            self.assertIn(bp.LAHAINA_SUMMARY, t, u)

    def test_no_object_strings(self):
        for u, dom in zip(self.urls + self.panels, self.views + self.panel_doms):
            self.assertNotIn("[object ", dom, u)

    def test_area_panel_shows_note(self):
        for u, dom in zip(self.panels, self.panel_doms):
            p = text(panel(dom))
            self.assertIn("Lahaina", p, u)
            self.assertIn(NOTE, p, u)


if __name__ == "__main__":
    unittest.main()
