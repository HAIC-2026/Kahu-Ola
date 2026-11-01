"""Decisions from the independent review (PLAN.md section 9.1).

- Messages: a language shows as reviewed only with a native-speaker reviewer (reviewed_by) in
  config/communication.json; every other language reads "Draft — needs review by a native
  speaker before use" in the app data and the PDFs. Vietnamese stays unreviewed until the team
  lead sets it.
- Stress tests: the intro in the app, the playbook summary and the annexes says results depend
  on the 30 sites opened in 2026.
- Readiness sheet: top 3 findings, at most one per test.
- PLAN.md: metric statuses, fire footprint line, owner and refresh cycle."""
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
import message_library as ml  # noqa: E402
import stress_text as stx  # noqa: E402

APP = ROOT / "app"
PLAY = ROOT / "playbooks"
CONFIG = json.loads((ROOT / "config" / "communication.json").read_text(encoding="utf-8"))
REVIEW = CONFIG["message_library"]["language_review"]
MESSAGES = json.loads((APP / "data" / "messages.json").read_text(encoding="utf-8"))
BUNDLE = json.loads((APP / "data" / "bundle.json").read_text(encoding="utf-8"))
PLAN = (ROOT / "PLAN.md").read_text(encoding="utf-8")


def bundled_messages() -> list:
    """Message rows as the app loads them (messages.json may store shared texts by index)."""
    m = MESSAGES.get("messages")
    return m if m is not None else BUNDLE.get("messages", [])


class MessageReview(unittest.TestCase):
    def test_every_language_has_a_review_entry(self):
        langs = {r["language"] for r in ml.load_messages()}
        self.assertEqual(set(REVIEW), langs)
        for v in REVIEW.values():
            self.assertEqual(set(v), {"reviewed_by", "review_date"})

    def test_vietnamese_unreviewed(self):
        self.assertEqual(REVIEW["Vietnamese"]["reviewed_by"], "")

    def test_no_language_reviewed_without_reviewed_by(self):
        msgs = bundled_messages()
        self.assertTrue(msgs)
        for m in msgs:
            if not REVIEW[m["language"]]["reviewed_by"].strip():
                self.assertNotEqual(m["status"], ml.REVIEWED, m["language"])
                if m["text"]:
                    self.assertEqual(m["status"], "Draft — needs review by a county public information officer "
                                     "before use" if m["language"] == "English" else
                                     "Draft — needs review by a native speaker before use", m["language"])
        for c in BUNDLE["message_counts"]:
            if not REVIEW[c["language"]]["reviewed_by"].strip():
                self.assertEqual(c["reviewed"], 0, c["language"])

    def test_row_approval_alone_is_not_enough(self):
        r = {"approved": "yes", "reviewed_by": "Someone", "review_date": "2026-11-01", "text": "x",
             "language": "Vietnamese"}
        self.assertEqual(ml.review_status(r, {"Vietnamese": {"reviewed_by": ""}}), ml.DRAFT)
        self.assertEqual(ml.review_status(r, {"Vietnamese": {"reviewed_by": "Someone"}}), ml.REVIEWED)

    def test_label_in_app_and_pdfs(self):
        self.assertIn(ml.DRAFT, bp.MESSAGES_LINE)
        self.assertEqual(BUNDLE["meta"]["messages_line"], bp.MESSAGES_LINE)
        for p in sorted(PLAY.glob("*_*.html")):
            if p.parent == PLAY:
                self.assertIn(ml.DRAFT, p.read_text(encoding="utf-8"), p.name)

    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext not installed")
    def test_label_in_pdf_text(self):
        for pdf in sorted(PLAY.glob("*.pdf")):
            t = " ".join(subprocess.run(["pdftotext", str(pdf), "-"], capture_output=True, text=True,
                                        check=True).stdout.split())
            self.assertIn(ml.DRAFT, t, pdf.name)


class EnglishLabel(unittest.TestCase):
    def test_english_needs_county_review(self):
        self.assertEqual(ml.DRAFT_EN, "Draft — needs review by a county public information officer before use")
        en = [m for m in bundled_messages() if m["language"] == "English"]
        self.assertTrue(en)
        for m in en:
            self.assertEqual(m["status"], ml.DRAFT_EN)
            self.assertNotIn("native speaker", m["status"])
        r = {"approved": "no", "reviewed_by": "", "review_date": "", "text": "x", "language": "English"}
        self.assertEqual(ml.review_status(r, REVIEW), ml.DRAFT_EN)
        self.assertEqual(ml.review_status({**r, "language": "Spanish"}, REVIEW), ml.DRAFT)


class SitesNote(unittest.TestCase):
    def test_app_annex_playbook(self):
        js = (APP / "stress.js").read_text(encoding="utf-8")
        self.assertIn(f'const SITES_NOTE = "{stx.SITES_NOTE}";', js)
        self.assertRegex(js, r"S\.method, \" \", SITES_NOTE")
        for p in sorted((PLAY / "annex").glob("*.html")) + sorted(PLAY.glob("*_*.html")):
            self.assertIn(stx.SITES_NOTE, p.read_text(encoding="utf-8"), p.name)
        self.assertIn(stx.SITES_NOTE, PLAN[PLAN.index("### 5.10"):PLAN.index("### 5.11")])


class ReadinessFindings(unittest.TestCase):
    def test_one_per_test(self):
        inp = bp.load_inputs()
        for c in bp.COUNTY_LABEL:
            for h in bp.HAZARD_LABEL:
                top = stx.top(inp["stress"]["findings"], c, h, 3, per_test=1, by_type=True)
                types = [stx.TEST_TYPE.get(f["test"], f["test"]) for f in top]
                self.assertEqual(len(set(types)), len(top), (c, h))               # one per test type
                r = (PLAY / f"{bp.slug(c, h)}.html").read_text(encoding="utf-8")
                sheet = re.search(r'<section class="readiness">.*?</section>', r, re.S).group(0)
                items = re.findall(r"<li><b>(.*?):</b>", sheet)
                self.assertEqual(len(items), len(top), (c, h))


    def test_site_losses_are_one_type(self):
        self.assertEqual(stx.TEST_TYPE["1"], stx.TEST_TYPE["2"])


class PlanDecisions(unittest.TestCase):
    def test_lines(self):
        m6 = PLAN[PLAN.index("## 6."):PLAN.index("## 7.")]
        self.assertIn("calibrated, not validated (Lahaina sets the high wildfire rate)", m6)
        self.assertIn("**Status: not yet measured.**", m6)
        self.assertIn("Data request to counties", m6)
        self.assertNotIn("inside the band", PLAN)
        self.assertIn("Counties should choose the wildfire footprint; stress test 23b", PLAN)
        s10 = PLAN[PLAN.index("## 10."):PLAN.index("## 11.")]
        for w in ("Owner and refresh cycle", "ACS release", "hurricane season", "shelter list",
                  "Esri credits per rerun", "Hosting"):
            self.assertIn(w, s10)
        s9 = PLAN[PLAN.index("## 9."):PLAN.index("## 10.")]
        self.assertIn("statewide totals that did not add up (43,517 people vs 43,519 cots)", s9)
        self.assertIn("with a second AI as checker", s9)
        self.assertNotIn("TODO", s9)
        self.assertIn("Datatrove was used to confirm HHS emPOWER field definitions.", s9)


if __name__ == "__main__":
    unittest.main()
