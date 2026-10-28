"""Plain-language playbooks and app: wording, Hawaiian spellings, reading guide,
sources under tables, and the app's new-data notice."""
import csv
import json
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_place_names as pn  # noqa: E402
import build_playbooks as bp  # noqa: E402

PLAY = ROOT / "playbooks"
APP = ROOT / "app"
NAMES = list(csv.DictReader(open(pn.OUT, encoding="utf-8")))
LABELS = list(csv.DictReader(open(ROOT / "data" / "sources" / "tract_communities.csv",
                                  encoding="utf-8")))
PAGES = sorted(p for p in PLAY.glob("*.html") if p.name != "index.html")
JARGON = ("Power-dep.", "AFN need", "class 1 of", ">At risk<", ">Limited English<",
          "Shelter low / central / high", "tract-level", "(SFHA)", ">No vehicle<", ">65+<",
          "central estimate", ">Tract ")


class PlaceNames(unittest.TestCase):
    def test_letters_never_change(self):
        for r in NAMES:
            self.assertEqual(pn.fold(r["display_name"]), pn.fold(r["census_name"]), r)
            self.assertTrue(r["source_url"].startswith("https://prd-tnm.s3.amazonaws.com/"))

    def test_official_spellings(self):
        got = {(r["county"], r["census_name"]): r["display_name"] for r in NAMES}
        self.assertEqual(got[("Maui", "Kihei")], "Kīhei")
        self.assertEqual(got[("Maui", "Waikapu")], "Waikapū")
        self.assertEqual(got[("Maui", "Waihee-Waiehu")], "Waiheʻe-Waiehu")   # from parts
        self.assertEqual(got[("Honolulu", "Halawa")], "Hālawa")
        self.assertEqual(got[("Kauai", "Lihue")], "Līhuʻe")
        self.assertEqual(got[("Maui", "Lahaina")], "Lahaina")                # GNIS spelling

    def test_unchanged_only_without_gnis_match(self):
        for r in NAMES:
            if r["method"] == "census_unchanged":
                self.assertEqual(r["display_name"], r["census_name"])
                self.assertEqual(r["gnis_feature_id"], "")
            else:
                self.assertTrue(r["gnis_feature_id"], r)

    def test_labels_use_display_spellings(self):
        display = {r["display_name"] for r in NAMES}
        ascii_only = {r["census_name"] for r in NAMES if r["display_name"] != r["census_name"]}
        for r in LABELS:
            main = re.sub(r"^(rural near |near |rural )", "", r["label_main"])
            for part in main.split(" / "):
                if r["method"] in ("pop_rural", "area_rural") and not r["label_main"].startswith("rural near"):
                    continue                                   # "rural <island>"
                self.assertIn(part, display, r["tract_label"])
                self.assertNotIn(part, ascii_only, r["tract_label"])


class Playbooks(unittest.TestCase):
    def test_plain_headers_and_no_jargon(self):
        for path in PAGES:
            html = path.read_text(encoding="utf-8")
            for col in bp.COL.values():
                self.assertIn(col, html, path.name)
            for word in JARGON:
                self.assertNotIn(word, html, (path.name, word))

    def test_community_cells_are_display_labels(self):
        mains = {r["label_main"] for r in LABELS}
        for path in PAGES:
            cells = re.findall(r"<td>([^<]+)<br><small>Census area [\d.]+</small>",
                               path.read_text(encoding="utf-8"))
            self.assertTrue(cells, path.name)
            for c in cells:
                self.assertIn(c.replace("&#x27;", "'"), mains, path.name)

    def test_map_legend_and_site_key(self):
        inp = bp.load_inputs()
        html = (PLAY / "maui_hurricane.html").read_text(encoding="utf-8")
        self.assertIn("Lowest need", html)
        self.assertIn("Highest need", html)
        sites = bp.sites_for(inp, "Maui", "hurricane")
        key = re.search(r'<ol class="sitekey">(.*?)</ol>', html, re.S).group(1)
        self.assertEqual(key.count("<li>"), len(sites))
        self.assertIn("<b>1</b> = Baldwin High School (usable)", key)

    def test_guide_after_page_one_and_sources_under_tables(self):
        for path in PAGES:
            html = path.read_text(encoding="utf-8")
            self.assertLess(html.index("2. Scope"), html.index("How to read this playbook"))
            self.assertLess(html.index("How to read this playbook"), html.index("3. Map"))
            body = html[:html.index("8. Sources and assumptions")]
            guide = re.search(r'<section class="guide.*?</section>', body, re.S).group(0)
            body = body.replace(guide, "")
            for m in re.finditer(r"</table>", body):
                self.assertIn('class="src"', body[m.end():m.end() + 400], path.name)
            for word in ("Census area", "low", "likely", "high", "C – Communication",
                         "M – Medical", "I – Independence", "S – Safety and support",
                         "T – Transportation", "upper bound", "Lowest need",
                         "ACS 2018–2022", "2020 Census", "2025",
                         "follow county announcements"):
                self.assertIn(word, guide, (path.name, word))

    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext not installed")
    def test_reading_guide_is_page_two_of_every_pdf(self):
        for pdf in sorted(PLAY.glob("*.pdf")):
            text = subprocess.run(["pdftotext", "-f", "2", "-l", "2", str(pdf), "-"],
                                  capture_output=True, text=True, check=True).stdout
            self.assertTrue(text.lstrip().startswith("How to read this playbook"), pdf.name)


class AppUpdateNotice(unittest.TestCase):
    JS = (APP / "app.js").read_text(encoding="utf-8")

    def test_version_checked_without_cache(self):
        self.assertIn('fetch(VERSION_URL, { cache: "no-store" })', self.JS)
        self.assertIn("latest.version !== DATA.meta.version", self.JS)
        self.assertIn("New planning data available", self.JS)
        self.assertIn('"Reload"', self.JS)
        self.assertRegex(self.JS, r"render\(\);\s*checkForUpdate\(\);")      # on load
        self.assertIn('addEventListener("online", checkForUpdate)', self.JS)

    def test_reload_refreshes_service_worker_cache(self):
        self.assertIn("reg.update()", self.JS)
        self.assertIn("location.reload()", self.JS)
        sw = (APP / "sw.js").read_text(encoding="utf-8")
        net = sw.index('url.pathname.endsWith("/data/version.json")')
        self.assertLess(net, sw.index("caches.match(req, { ignoreSearch: true }).then"))
        self.assertIn("fetch(req).catch", sw[net:net + 300])                 # network first

    def test_header_always_shows_version_and_date(self):
        html = (APP / "index.html").read_text(encoding="utf-8")
        header = html[html.index('<header class="site-header">'):html.index("</header>")]
        self.assertIn('id="dataver"', header)
        self.assertIn('id="update"', html)
        self.assertIn("Data version ${DATA.meta.version} · Data as of ${DATA.meta.data_as_of}", self.JS)

    def test_version_file_matches_bundle(self):
        v = json.loads((APP / "data" / "version.json").read_text(encoding="utf-8"))
        b = json.loads((APP / "data" / "bundle.json").read_text(encoding="utf-8"))
        self.assertEqual(v["version"], b["meta"]["version"])
        self.assertEqual(v["data_as_of"], b["meta"]["data_as_of"])

    def test_help_panel_and_shared_wording(self):
        b = json.loads((APP / "data" / "bundle.json").read_text(encoding="utf-8"))
        self.assertEqual(b["meta"]["cols"], bp.COL)
        self.assertEqual([tuple(x) for x in b["meta"]["cmist"]], bp.CMIST)
        self.assertIn("How to read this page", self.JS)
        def leaves(x):                       # displayed text only, not internal keys
            if isinstance(x, dict):
                return [s for v in x.values() for s in leaves(v)]
            if isinstance(x, list):
                return [s for v in x for s in leaves(v)]
            return [x] if isinstance(x, str) else []
        shown = " ".join(leaves(b["meta"]))
        for word in JARGON:
            self.assertNotIn(word.strip("<>"), shown)


if __name__ == "__main__":
    unittest.main()
