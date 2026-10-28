"""QA fixes: partner names, labels, sources links, rates, spellings, duplicates, touch
targets, keyboard access, layout shift, headers and PLAN.md numbers."""
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_playbooks as bp  # noqa: E402

APP = ROOT / "app"
PLAY = ROOT / "playbooks"
BUNDLE = json.loads((APP / "data" / "bundle.json").read_text(encoding="utf-8"))
JS = (APP / "app.js").read_text(encoding="utf-8")
CSS = (APP / "styles.css").read_text(encoding="utf-8")
INDEX = (APP / "index.html").read_text(encoding="utf-8")
PAGES = sorted(p for p in PLAY.glob("*.html") if p.name != "index.html")
PARTNERS = json.loads((ROOT / "config" / "partners.json").read_text(encoding="utf-8"))["partners"]


def visible(html: str) -> str:
    """Text a reader sees: no <style>, no tags."""
    return re.sub(r"<[^>]+>", " ", re.sub(r"<style>.*?</style>", "", html, flags=re.S))


def shown_strings(x):
    if isinstance(x, dict):
        return [s for v in x.values() for s in shown_strings(v)]
    if isinstance(x, list):
        return [s for v in x for s in shown_strings(v)]
    return [x] if isinstance(x, str) else []


class PartnerNames(unittest.TestCase):
    IDS = sorted({p["id"] for p in PARTNERS} | {p["partner_type"] for p in PARTNERS})

    def find_ids(self, text):
        return [i for i in self.IDS if re.search(rf"(?<![\w-]){re.escape(i)}(?![\w-])", text)]

    def test_no_partner_id_in_app_output(self):
        shown = " ".join(shown_strings(BUNDLE["decision_points"]))
        shown += " " + " ".join(s for sc in BUNDLE["scenarios"].values() for row in sc["needs"]
                                for s in shown_strings(row))
        self.assertEqual(self.find_ids(shown), [])

    def test_no_partner_id_in_playbooks(self):
        for p in PAGES:
            self.assertEqual(self.find_ids(visible(p.read_text(encoding="utf-8"))), [], p.name)

    def test_support_column_uses_names(self):
        row = BUNDLE["decision_points"]["hurricane"][0]
        self.assertIn("Hawaiʻi Department of Human Services (DHS)", row[5])


class Labels(unittest.TestCase):
    def test_challenge_statement_label(self):
        for p in PAGES:
            text = visible(p.read_text(encoding="utf-8"))
            self.assertIn("Hawaiʻi DHS – ESF-6 challenge statement (2026)", text, p.name)
            self.assertNotIn("HAIC_", text)
            self.assertNotIn(".pdf (2026", text)
            self.assertNotIn("Hawaii DHS", text)

    def test_spellings_and_language_labels(self):
        for p in PAGES:
            text = visible(p.read_text(encoding="utf-8"))
            self.assertNotIn("Other English-based Creole languages", text, p.name)
            self.assertNotIn("Kauai + Maui", text, p.name)
            self.assertNotIn("State of Hawaii Data Book", text, p.name)
            self.assertIn("Hawaiʻi Data Book", text, p.name)
            if p.stem.startswith(("kauai", "maui")):
                self.assertIn("Kauaʻi + Maui", text, p.name)
        langs = [r[0] for c in BUNDLE["languages"].values() for r in c["rows"]]
        self.assertIn("Pidgin (Hawaiʻi Creole English)", langs)
        self.assertNotIn("Other English-based Creole languages", langs)
        self.assertEqual(BUNDLE["languages"]["Maui"]["area"], "Kauaʻi + Maui")
        needs = {row[0] for sc in BUNDLE["scenarios"].values() for row in sc["needs"]}
        self.assertIn("Interpreters – Pidgin (Hawaiʻi Creole English)", needs)

    def test_pets_source(self):
        self.assertIn("AVMA (2020 data)", BUNDLE["meta"]["sources"]["needs"])
        for p in PAGES:
            text = visible(p.read_text(encoding="utf-8"))
            self.assertIn("AVMA (2020 data)", text)
            self.assertNotIn("AVMA 2022", text)


class SourcesLink(unittest.TestCase):
    def test_app_has_no_section_numbers(self):
        for k, v in BUNDLE["meta"]["sources"].items():
            self.assertNotIn("section 8", v, k)
        self.assertGreaterEqual(sum("{SOURCES}" in v for v in BUNDLE["meta"]["sources"].values()), 3)
        self.assertIn('split("{SOURCES}")', JS)
        self.assertIn('"see Sources"', JS)

    def test_pdfs_keep_section_8(self):
        for p in PAGES:
            text = visible(p.read_text(encoding="utf-8"))
            self.assertIn("8. Sources and assumptions", text)
            self.assertNotIn("{SOURCES}", text)
            self.assertGreaterEqual(text.count("section 8"), 3, p.name)


class Rates(unittest.TestCase):
    def test_pct_text(self):
        self.assertEqual(bp.pct_text(0.112), "11.2%")
        self.assertEqual(bp.pct_text(0.11), "11%")
        self.assertEqual(bp.pct_text(0.05), "5%")
        self.assertEqual(bp.pct_text(0.02), "2%")

    def test_no_trailing_zero_decimals(self):
        for p in PAGES:
            text = visible(p.read_text(encoding="utf-8"))
            self.assertIsNone(re.search(r"\b\d+\.0%", text), p.name)
        self.assertIn("11.2%", visible((PLAY / "maui_wildfire.html").read_text(encoding="utf-8")))
        self.assertIn("high 11%", visible((PLAY / "maui_tsunami.html").read_text(encoding="utf-8")))
        self.assertIn("Number.isInteger(p)", JS)
        self.assertNotIn("pct(s.rate_high, 1)", JS)


class Duplicates(unittest.TestCase):
    def test_disclaimer_and_privacy_once(self):
        self.assertNotIn("DATA.meta.disclaimer", JS)
        self.assertNotIn("DATA.meta.privacy", JS)
        self.assertEqual(INDEX.count("Planning aid. Supports, does not replace"), 1)
        self.assertEqual(INDEX.count("No individual records."), 1)

    def test_one_flood_check_label(self):
        for text in [JS, json.dumps(BUNDLE["meta"], ensure_ascii=False),
                     json.dumps(BUNDLE["status_labels"], ensure_ascii=False)] + \
                [p.read_text(encoding="utf-8") for p in PAGES]:
            self.assertNotIn("heck flood risk", text)
        self.assertIn('"check": ["triangle", "Check flood zone"]', JS)


class Accessibility(unittest.TestCase):
    def test_touch_targets_and_text_size(self):
        self.assertIn(".menu a, .button, .skip:focus { min-height: 44px;", CSS)
        self.assertIn("details > summary { min-height: 44px;", CSS)
        self.assertIn(".prov a, .src a { display: inline-flex; align-items: center; min-height: 44px; }", CSS)
        self.assertIn('.msg-filters input[type="checkbox"] { width: 24px; height: 24px;', CSS)
        self.assertIn(".button, .msg small { font-size: 1rem; }", CSS)
        self.assertRegex(CSS, r"@media \(max-width: 480px\) \{\s*\.map svg text \{ font-size: 28px; \}")

    def test_keyboard_regions_and_area_list(self):
        self.assertIn('{ class: "table-wrap", tabindex: "0", role: "region", "aria-label": name }', JS)
        self.assertIn("Census areas on this map in the risk area", JS)


class LayoutShift(unittest.TestCase):
    def test_no_jump_on_load(self):
        head = INDEX[:INDEX.index("</head>")]
        self.assertIn('<script src="app.js" defer></script>', head)
        self.assertIn('<link rel="preload" href="data/bundle.json" as="fetch" crossorigin>', head)
        self.assertRegex(INDEX, r'<section id="fallback"[^>]*hidden>')
        self.assertNotRegex(INDEX, r'<nav id="menu"[^>]*hidden')
        self.assertNotRegex(INDEX, r'<form id="controls"[^>]*hidden')
        self.assertIn("#app { min-height: 100vh; }", CSS)
        self.assertIn("setTimeout(() => { if (!DATA) fb.hidden = false; }, 2000)", JS)
        noscript = INDEX[INDEX.index("<noscript>"):INDEX.index("</noscript>")]
        footer = INDEX[INDEX.index("<footer"):INDEX.index("</footer>")]
        for part in (noscript, footer):
            self.assertEqual(part.count('href="playbooks/'), 20)


class Headers(unittest.TestCase):
    CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
           "connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'none'")

    def test_headers_and_files(self):
        h = (APP / "_headers").read_text(encoding="utf-8")
        self.assertIn("Strict-Transport-Security: max-age=31536000; includeSubDomains", h)
        self.assertNotIn("interest-cohort", h)
        self.assertIn(f"Content-Security-Policy: {self.CSP}; frame-ancestors 'none'", h)
        self.assertIn(f'content="{self.CSP}"', INDEX)                      # CSP unchanged
        robots = (APP / "robots.txt").read_text(encoding="utf-8")
        self.assertIn("User-agent: *", robots)
        self.assertRegex(INDEX, r'<meta name="description" content="[^"]{50,}">')


class PlanNumbers(unittest.TestCase):
    PLAN = (ROOT / "PLAN.md").read_text(encoding="utf-8")

    @unittest.skipUnless(shutil.which("pdfinfo"), "pdfinfo not installed")
    def test_pages_per_playbook(self):
        pages = {int(re.search(r"Pages:\s+(\d+)", subprocess.run(
            ["pdfinfo", str(p)], capture_output=True, text=True, check=True).stdout).group(1))
            for p in PLAY.glob("*.pdf")}
        self.assertEqual(len(pages), 1)
        self.assertIn(f"{pages.pop()} pages each", self.PLAN)

    def test_bundle_size(self):
        kb = round((APP / "data" / "bundle.json").stat().st_size / 1024)
        m = re.search(r"one (\d+) KB bundle", self.PLAN)
        self.assertTrue(m)
        self.assertLessEqual(abs(int(m.group(1)) - kb), max(10, kb // 20))

    def test_test_count(self):
        n = unittest.TestLoader().discover(str(ROOT / "tests")).countTestCases()
        self.assertIn(f"{n} automated tests", self.PLAN)


if __name__ == "__main__":
    unittest.main()
