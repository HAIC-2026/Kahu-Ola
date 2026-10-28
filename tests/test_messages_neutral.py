"""Messages tab with a neutral review status, a two-tab menu, and no "AI"/"Claude"
wording anywhere in the app or the printed playbooks."""
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import message_library as ml  # noqa: E402

APP = ROOT / "app"
PLAY = ROOT / "playbooks"
BUNDLE = json.loads((APP / "data" / "bundle.json").read_text(encoding="utf-8"))
JS = (APP / "app.js").read_text(encoding="utf-8")
ROWS = ml.load_messages()
WORDS = re.compile(r"\bAI\b|Claude")
TEXT = (".html", ".js", ".css", ".json", ".webmanifest", ".svg", "")


class NoAIWording(unittest.TestCase):
    def test_app_files(self):
        files = [p for p in APP.rglob("*") if p.is_file() and p.suffix in TEXT]
        self.assertTrue(any(p.name == "bundle.json" for p in files))
        for p in files:
            self.assertIsNone(WORDS.search(p.read_text(encoding="utf-8")), p)

    def test_playbook_html(self):
        for p in PLAY.glob("*.html"):
            self.assertIsNone(WORDS.search(p.read_text(encoding="utf-8")), p.name)

    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext not installed")
    def test_playbook_pdfs(self):
        pdfs = sorted(PLAY.glob("*.pdf")) + sorted((APP / "playbooks").glob("*.pdf"))
        self.assertTrue(pdfs)
        for pdf in pdfs:
            text = subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True,
                                  text=True, check=True).stdout
            self.assertIsNone(WORDS.search(text), pdf.name)


class Navigation(unittest.TestCase):
    def test_exactly_two_tabs(self):
        html = (APP / "index.html").read_text(encoding="utf-8")
        nav = re.search(r'<nav id="menu".*?</nav>', html, re.S).group(0)
        self.assertEqual(re.findall(r'<a [^>]*href="(#\w+)">([^<]+)</a>', nav),
                         [("#plan", "Plan"), ("#messages", "Messages")])
        self.assertIn('const VIEWS = { plan: "Plan", messages: "Messages" };', JS)

    def test_header_unchanged(self):
        html = (APP / "index.html").read_text(encoding="utf-8")
        header = html[html.index('<header class="site-header">'):html.index("</header>")]
        self.assertIn("<h1>Hawaiʻi ESF-6 Planning</h1>", header)
        self.assertIn("Planning aid. Supports, does not replace, county emergency plans. "
                      "Not an official shelter list.", header)
        self.assertIn('id="dataver"', header)
        self.assertIn("Data version ${DATA.meta.version} · Data as of ${DATA.meta.data_as_of}", JS)


class ReviewStatus(unittest.TestCase):
    def test_every_unapproved_message_is_a_draft(self):
        bundled = {(m["file"], m["message_id"]): m for m in BUNDLE["messages"]}
        self.assertEqual(len(bundled), len(ROWS))
        for r in ROWS:
            m = bundled[(r["file"], r["message_id"])]
            approved = (r["approved"].strip().lower() == "yes" and r["reviewed_by"].strip()
                        and r["review_date"].strip())
            self.assertEqual(m["status"], "Reviewed" if approved else "Draft — not yet reviewed",
                             (r["file"], r["message_id"]))
            self.assertEqual(m["text"], r["text"])

    def test_only_two_statuses_and_rule_edges(self):
        self.assertEqual({m["status"] for m in BUNDLE["messages"]} - {"Reviewed"},
                         {"Draft — not yet reviewed"})
        base = {"approved": "yes", "reviewed_by": "A. Reviewer", "review_date": "2026-11-01"}
        self.assertEqual(ml.review_status(base), "Reviewed")
        for missing in ("reviewed_by", "review_date"):
            self.assertEqual(ml.review_status({**base, missing: ""}), "Draft — not yet reviewed")
        self.assertEqual(ml.review_status({**base, "approved": "no"}), "Draft — not yet reviewed")

    def test_badge_shows_bundle_status(self):
        self.assertIn("badge(m.status)", JS)
        self.assertIn('status === "Reviewed" ? "badge reviewed" : "badge draft"', JS)

    def test_counts_match_files(self):
        got = {c["language"]: (c["rows"], c["reviewed"]) for c in BUNDLE["message_counts"]}
        want = {}
        for r in ROWS:
            n, rev = want.get(r["language"], (0, 0))
            want[r["language"]] = (n + 1, rev + (ml.review_status(r) == "Reviewed"))
        self.assertEqual(got, want)


class Removed(unittest.TestCase):
    def test_no_ai_page_or_count_builder(self):
        self.assertNotIn("ai", BUNDLE)
        self.assertNotIn("renderAI", JS)
        self.assertFalse((ROOT / "scripts" / "ai_work.py").exists())
        for name in ("git_stats", "test_count", "coauthored"):
            for p in (ROOT / "scripts").glob("*.py"):
                self.assertNotIn(name, p.read_text(encoding="utf-8"), p.name)

    def test_no_new_requests(self):
        self.assertEqual(re.findall(r"fetch\(([^)]*)\)", JS),
                         ['VERSION_URL, { cache: "no-store" }', "BUNDLE_URL"])
        self.assertNotRegex(JS, r"https?://(?!www\.w3\.org/2000/svg)")


if __name__ == "__main__":
    unittest.main()
