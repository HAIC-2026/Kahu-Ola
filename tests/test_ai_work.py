"""All AI work is shown: every message row, build-time counts, the "How AI built this
plan" page and section, provenance labels, and no new network calls."""
import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ai_work  # noqa: E402

APP = ROOT / "app"
PLAY = ROOT / "playbooks"
BUNDLE = json.loads((APP / "data" / "bundle.json").read_text(encoding="utf-8"))
JS = (APP / "app.js").read_text(encoding="utf-8")
ROWS = ai_work.load_messages()
STORED = ("message_id", "hazard", "trigger", "timing", "channel", "language", "text", "status",
          "translated_by", "review_assignee", "reviewed_by", "review_date", "approved", "notes")
PAGES = sorted(p for p in PLAY.glob("*.html") if p.name != "index.html")


class Messages(unittest.TestCase):
    def test_every_row_in_bundle_unchanged(self):
        self.assertEqual(len(BUNDLE["messages"]), len(ROWS))
        bundled = {(m["file"], m["message_id"]): m for m in BUNDLE["messages"]}
        for r in ROWS:
            m = bundled[(r["file"], r["message_id"])]
            for k in STORED:
                self.assertEqual(m[k], r[k], (r["file"], r["message_id"], k))

    def test_badges_show_stored_status(self):
        self.assertIn("badge(m.status)", JS)
        self.assertIn('el("span", { class: kind }, status || "(no status)")', JS)
        for k in ("m.reviewed_by", "m.review_date", "m.review_assignee", "m.approved",
                  "m.translated_by"):
            self.assertIn(k, JS)

    def test_counts_match_files(self):
        by_lang = {}
        for r in ROWS:
            c = by_lang.setdefault(r["language"], [0, 0, 0, 0])
            c[0] += 1
            c[1] += r["status"].startswith("DRAFT") and bool(r["text"].strip())
            c[2] += r["status"].startswith("NEEDS HUMAN") and not r["text"].strip()
            c[3] += r["approved"].strip().lower() == "yes"
        got = {c["language"]: [c["rows"], c["drafts"], c["placeholders"], c["approved"]]
               for c in BUNDLE["ai"]["message_counts"]}
        self.assertEqual(got, by_lang)
        self.assertEqual(BUNDLE["ai"]["messages_total"], len(ROWS))
        self.assertEqual(BUNDLE["ai"]["messages_approved"], sum(v[3] for v in by_lang.values()))

    def test_filters_only_narrow(self):
        self.assertIn('const MSG = { county: null, onlyCounty: false, hazard: "", phase: "", language: "" };', JS)
        self.assertIn("Showing ${fmt(shown.length)} of ${fmt(all.length)} messages.", JS)
        self.assertIn("navigator.clipboard.writeText(text)", JS)

    def test_english_source_and_placeholders_included(self):
        langs = {m["language"] for m in BUNDLE["messages"]}
        self.assertIn("English", langs)
        for lang in BUNDLE["ai"]["human_translation_languages"]:
            self.assertTrue(any(m["language"] == lang and m["text"] == "" for m in BUNDLE["messages"]))


class AIPage(unittest.TestCase):
    def test_tasks_and_not_done_list(self):
        ai = BUNDLE["ai"]
        self.assertEqual([t["task"] for t in ai["tasks"]],
                         ["Shelter list", "Data discovery", "Software", "Multilingual messages"])
        self.assertEqual([k for k, _ in ai["not_done"]],
                         ["Compute the numbers", "Decide shelter status", "Run during an emergency"])
        self.assertIn("What AI does NOT do", JS)
        self.assertEqual(ai["tasks"][0]["evidence"][0][1],
                         "https://github.com/HAIC-2026/Kahu-Ola/blob/main/data/sources/county_shelter_activations.csv")

    def test_counts_computed_at_build_time(self):
        ai = BUNDLE["ai"]
        self.assertEqual(ai["tests"], ai_work.test_count())
        try:
            n = int(subprocess.run(["git", "-C", str(ROOT), "rev-list", "--count", ai["head"]],
                                   capture_output=True, text=True, check=True).stdout)
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("git not available")
        self.assertEqual(ai["commits"], n)
        software = ai["tasks"][2]["people"]
        self.assertIn(f"{ai['commits']:,} commits", software)
        self.assertIn(f"{ai['coauthored']:,} of them co-authored by Claude", software)
        self.assertIn(f"{ai['tests']:,} automated tests", software)

    def test_shelter_records_label_from_files(self):
        sh = ai_work.shelter_stats()
        with open(ai_work.SHELTERS, newline="", encoding="utf-8") as fh:
            records = sum(1 for _ in fh) - 1
        sites = json.loads(ai_work.SITES.read_text(encoding="utf-8"))["features"]
        twice = sum(f["properties"]["times_opened_2026"] == 2 for f in sites)
        self.assertEqual((sh["rows"], sh["sites"]), (records, len(sites)))
        want = (f"{records} activation records for {len(sites)} sites ({twice} sites opened "
                "twice), all citing an official county source")
        self.assertEqual(BUNDLE["ai"]["shelter_records"], want)
        self.assertIn(want, BUNDLE["ai"]["tasks"][0]["ai"])
        self.assertIn("ai.shelter_records", JS)
        for path in PAGES:
            self.assertIn(want, path.read_text(encoding="utf-8"), path.name)

    def test_every_playbook_has_ai_section(self):
        for path in PAGES:
            html = path.read_text(encoding="utf-8")
            self.assertIn("9. How AI built this plan", html, path.name)
            self.assertIn("What AI does NOT do", html, path.name)
            for k, _ in ai_work.NOT_DONE:
                self.assertIn(k, html, path.name)
            self.assertIn(ai_work.LINKS["shelters"], html, path.name)


class Provenance(unittest.TestCase):
    def test_labels_in_playbooks_and_app(self):
        for path in PAGES:
            html = path.read_text(encoding="utf-8")
            self.assertIn("Compiled with AI from official county releases · verified by team", html)
            self.assertIn("Calculated by open code from public data · see Sources", html)
        self.assertIn("provLabel(DATA.provenance.numbers", JS)
        self.assertIn("provLabel(DATA.provenance.shelters)", JS)


class NoNewCalls(unittest.TestCase):
    def test_menu_visible_in_header(self):
        html = (APP / "index.html").read_text(encoding="utf-8")
        header = html[html.index('<header class="site-header">'):html.index("</header>")]
        for href, name in (("#plan", "Plan"), ("#messages", "Messages"), ("#ai", "How AI built this")):
            self.assertIn(f'href="{href}">{name}</a>', header)

    def test_no_new_requests_or_ai_services(self):
        self.assertEqual(re.findall(r"fetch\(([^)]*)\)", JS),
                         ['VERSION_URL, { cache: "no-store" }', "BUNDLE_URL"])
        self.assertNotRegex(JS, r"https?://(?!www\.w3\.org/2000/svg)")
        for word in ("anthropic", "openai", "api.", "XMLHttpRequest", "WebSocket", "EventSource"):
            self.assertNotIn(word, JS.lower() if word.islower() else JS)
        links = re.findall(r'"(https?://[^"]+)"', json.dumps(BUNDLE["ai"], ensure_ascii=False))
        self.assertTrue(links)
        self.assertTrue(all(u == ai_work.REPO or u.startswith(ai_work.REPO + "/") for u in links))


if __name__ == "__main__":
    unittest.main()
