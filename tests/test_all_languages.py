"""Languages: the full "All languages" list (app + PDFs) matches the PUMS summary file,
low-reliability flags follow the CV rule, Vietnamese appears in every area, and the
statewide draft-messages line is shown."""
import csv
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
from test_map_detail import Serve, chrome, free_port, text  # noqa: E402

ROWS = list(csv.DictReader(open(bp.LANG_CSV, encoding="utf-8")))
AREAS = sorted({r["area"] for r in ROWS})
BUNDLE = json.loads((ROOT / "app" / "data" / "bundle.json").read_text(encoding="utf-8"))
COUNTY_AREA = {r_c: r["area"] for r in ROWS for r_c in r["counties"].split(";")}


def section(t: str) -> str:
    """PDF text of the "All languages" table (up to the next section)."""
    return t.split("All languages in the survey for", 1)[1].split("8. Sources and assumptions", 1)[0]


class DataFile(unittest.TestCase):
    def test_list_matches_data_file(self):
        for area in AREAS:
            want = [r for r in ROWS if r["area"] == area]
            got = bp.all_languages(area)
            self.assertEqual([g["language"] for g in got], [r["language"] for r in want], area)
            for g, r in zip(got, want):
                if r["suppressed"] == "True":
                    self.assertIsNone(g["people"])
                    self.assertEqual(r["speak_english_less_than_very_well"], "<100")
                else:
                    self.assertEqual((g["people"], g["moe"]),
                                     (int(r["speak_english_less_than_very_well"]), int(r["moe_90"])))

    def test_flags_follow_cv_rule(self):
        for area in AREAS:
            for g in bp.all_languages(area):
                if g["people"] is None:
                    self.assertTrue(g["low"], g)                 # too few to estimate
                else:
                    cv = g["moe"] / 1.645 / g["people"]
                    self.assertEqual(g["low"], cv > 0.40, g)

    def test_bundle_matches_for_every_county(self):
        for c, L in BUNDLE["languages"].items():
            want = [[bp.lang_label(g["language"]), g["people"], g["moe"], int(g["low"])]
                    for g in bp.all_languages(COUNTY_AREA[c])]
            self.assertEqual(L["all"], want, c)

    def test_vietnamese_in_every_area(self):
        for c, L in BUNDLE["languages"].items():
            row = next(r for r in L["all"] if r[0] == "Vietnamese")
            self.assertTrue(row[1] is None or row[1] > 0, c)

    def test_messages_line_matches_library(self):
        self.assertEqual(BUNDLE["meta"]["messages_line"], bp.MESSAGES_LINE)
        drafts = {c["label"] for c in BUNDLE["message_counts"] if c["drafts"] and c["label"] != "English"}
        waiting = {c["label"] for c in BUNDLE["message_counts"] if c["placeholders"]}
        for name in ("Chinese", "Hawaiian", "Ilocano", "Japanese", "Korean", "Spanish", "Vietnamese"):
            self.assertIn(name, drafts)
        self.assertTrue(any(d.startswith("Pidgin") for d in drafts))
        self.assertTrue(any(d.startswith("Tagalog") for d in drafts))
        self.assertEqual(waiting, {"Chuukese", "Marshallese"})


class Pdfs(unittest.TestCase):
    def test_every_pdf_has_full_list_and_line(self):
        pages = sorted((ROOT / "playbooks").glob("*_*.html"))
        self.assertEqual(len(pages), 20)
        for p in pages:
            t = text(p.read_text(encoding="utf-8"))
            self.assertIn(bp.MESSAGES_LINE, t, p.name)
            s = section(t)
            county = next(c for c, lab in bp.COUNTY_LABEL.items() if p.name.startswith(bp.slug(c, "x").split("_")[0]))
            for g in bp.all_languages(COUNTY_AREA[county]):
                name = re.escape(bp.lang_label(g["language"]))
                value = bp.TOO_FEW if g["people"] is None else f"{g['people']:,}"
                self.assertRegex(s, name + r" " + re.escape(value), (p.name, g["language"]))
            self.assertRegex(s, r"Vietnamese (too few to estimate|[\d,]+)", p.name)


@unittest.skipUnless(bp.find_browser(), "Chrome/Chromium not installed")
class App(unittest.TestCase):
    def test_details_list_in_app(self):
        port = free_port()
        server = Serve(port)
        try:
            with tempfile.TemporaryDirectory() as prof:
                dom = chrome(f"http://127.0.0.1:{port}/?county=Hawaii&hazard=wildfire", prof)
        finally:
            server.stop()
        m = re.search(r'<details class="all-languages".*?</details>', dom, re.S)
        self.assertTrue(m)
        t = text(m.group(0))
        n = len(BUNDLE["languages"]["Hawaii"]["all"])
        self.assertIn(f"All languages ({n})", t)
        self.assertIn("Vietnamese too few to estimate", t)
        self.assertIn(bp.MESSAGES_LINE, text(dom))


if __name__ == "__main__":
    unittest.main()
