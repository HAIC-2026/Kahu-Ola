"""Offline tests for the deliverables: printable playbooks and the offline PWA."""
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_playbooks as bp  # noqa: E402
import svgmap  # noqa: E402

PLAY = ROOT / "playbooks"
APP = ROOT / "app"
COUNTIES = ("kauai", "honolulu", "maui", "hawaii")
HAZARDS = ("hurricane", "wildfire", "tsunami", "inland_flood", "coastal_flood")
DISCLAIMER = ("Planning aid. Supports, does not replace, county emergency plans. "
              "Not an official shelter list.")


def bundle():
    return json.loads((APP / "data" / "bundle.json").read_text(encoding="utf-8"))


class Playbooks(unittest.TestCase):
    def test_twenty_playbooks_html_and_pdf(self):
        for c in COUNTIES:
            for h in HAZARDS:
                html = PLAY / f"{c}_{h}.html"
                pdf = PLAY / f"{c}_{h}.pdf"
                self.assertTrue(html.exists(), html)
                self.assertTrue(pdf.exists(), pdf)
                self.assertEqual(pdf.read_bytes()[:5], b"%PDF-")
        self.assertEqual(len(list(PLAY.glob("*_*.html"))), 20)
        self.assertEqual(len(list(PLAY.glob("*.pdf"))), 20)

    def test_disclaimer_and_data_as_of_everywhere(self):
        for f in PLAY.glob("*_*.html"):
            t = f.read_text(encoding="utf-8")
            self.assertIn(DISCLAIMER, t, f)
            self.assertIn("Data as of 20", t, f)
            # printed footer on every page comes from the @page margin box
            self.assertRegex(t, r"@bottom-left \{ content: \"Data as of 20\d\d-\d\d-\d\d · Planning aid")

    def test_sections_in_order(self):
        t = (PLAY / "maui_tsunami.html").read_text(encoding="utf-8")
        heads = ["1. Summary", "2. Scope", "Largest single community", "How to read this playbook",
                 "3. Map", "4. Known sites",
                 "5. Needs and proposed partners", "6. Decision points",
                 "7. Priority outreach and languages", "8. Sources and assumptions"]
        pos = [t.index(h) for h in heads]
        self.assertEqual(pos, sorted(pos))
        self.assertIn("People in the extreme tsunami zone", t)
        self.assertIn("Kauaʻi and Maui share one language list", t)
        self.assertIn("<svg", t)
        self.assertIn('role="img"', t)

    def test_maui_tsunami_excludes_lahaina_and_kilohana(self):
        inp = bp.load_inputs()
        sites = {s["name"]: s for s in bp.sites_for(inp, "Maui", "tsunami")}
        for name in ("Lahaina Civic Center Gym", "Kilohana Recreation Center"):
            self.assertEqual(sites[name]["status"], "exclude")
            self.assertIn("tsunami", sites[name]["reason"])
        t = (PLAY / "maui_tsunami.html").read_text(encoding="utf-8")
        for name in ("Lahaina Civic Center Gym", "Kilohana Recreation Center"):
            row = re.search(r"<tr>(?:(?!</tr>).)*" + re.escape(name) + r"(?:(?!</tr>).)*</tr>", t, re.S)
            self.assertIn("✕ Not for this hazard", row.group(0))

    def test_no_network_resources_in_playbooks(self):
        for f in list(PLAY.glob("*.html")):
            t = f.read_text(encoding="utf-8")
            self.assertNotRegex(t, r"(src|href)=\"https?://")
            self.assertNotIn("@import", t)
            self.assertNotRegex(t, r"url\(\s*['\"]?https?:")
            self.assertNotIn("<script", t)

    def test_index_links_all_twenty(self):
        t = (PLAY / "index.html").read_text(encoding="utf-8")
        for c in COUNTIES:
            for h in HAZARDS:
                self.assertIn(f'href="{c}_{h}.pdf"', t)

    def test_footer_css_and_browser_finder(self):
        self.assertIn('"Data as of 2026-01-01 · Planning aid', bp.css("2026-01-01"))
        b = bp.find_browser()
        self.assertTrue(b is None or Path(b).exists())


class Bundle(unittest.TestCase):
    def test_small(self):
        self.assertLess((APP / "data" / "bundle.json").stat().st_size, 600_000)

    def test_no_person_fields(self):
        b = bundle()
        allowed = id(b["sites"])

        def walk(o, inside_sites=False):
            if isinstance(o, dict):
                for k, v in o.items():
                    self.assertNotIn(k.lower(), {"phone", "email", "dob", "ssn", "person", "client"})
                    if k in ("name", "address"):
                        self.assertTrue(inside_sites, f"'{k}' outside public facility list")
                    walk(v, inside_sites)
            elif isinstance(o, list):
                for v in o:
                    walk(v, inside_sites or id(o) == allowed)
        walk(b)
        self.assertNotRegex(json.dumps(b), r"\(?\d{3}\)?[ -]\d{3}-\d{4}")

    def test_contents(self):
        b = bundle()
        self.assertEqual(len(b["scenarios"]), 20)
        self.assertTrue(b["meta"]["version"] and b["meta"]["data_as_of"])
        self.assertEqual(json.loads((APP / "data" / "version.json").read_text())["version"],
                         b["meta"]["version"])
        st = {s["name"]: s["status"]["tsunami"][0] for s in b["sites"]
              if s["county"] == "Maui" and "tsunami" in s["status"]}
        self.assertEqual(st["Lahaina Civic Center Gym"], "exclude")
        self.assertEqual(st["Kilohana Recreation Center"], "exclude")
        for key, sc in b["scenarios"].items():
            self.assertTrue((ROOT / sc["playbook"]).exists(), key)       # copied in at build


class ServiceWorker(unittest.TestCase):
    def precache(self):
        sw = (APP / "sw.js").read_text(encoding="utf-8")
        m = re.search(r"const PRECACHE = (\[.*?\]);", sw, re.S)
        return sw, json.loads(m.group(1))

    def test_caches_every_data_file_and_pdf(self):
        sw, pre = self.precache()
        self.assertNotIn('const VERSION = "dev"', sw)
        for f in (APP / "data").iterdir():
            self.assertIn(f"data/{f.name}", pre)
        pdfs = sorted(p.name for p in PLAY.glob("*.pdf"))
        for name in pdfs:
            self.assertIn(f"playbooks/{name}", pre)
        for shell in ("index.html", "app.js", "styles.css", "manifest.webmanifest",
                      "icon-180.png", "icon-192.png", "icon-512.png"):
            self.assertIn(shell, pre)
        for rel in pre:                      # PDFs live in playbooks/ until the build copies them
            src = ROOT / rel if rel.startswith("playbooks/") else APP / ("index.html" if rel == "./" else rel)
            self.assertTrue(src.exists(), rel)

    def test_pdfs_committed_once_and_copied_at_build(self):
        import tempfile
        import build_app_data as bad
        self.assertIn("app/playbooks/", (ROOT / ".gitignore").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as d:
            out = bad.copy_playbooks(PLAY, Path(d))
            self.assertEqual(len(out), 20)
            self.assertEqual(len(list((Path(d) / "playbooks").glob("*.pdf"))), 20)

    def test_same_origin_only(self):
        sw = (APP / "sw.js").read_text(encoding="utf-8")
        self.assertIn("origin !== self.location.origin", sw)
        self.assertNotRegex(sw, r"https?://")


class AppCode(unittest.TestCase):
    def test_no_external_calls_tracking_or_location(self):
        js = (APP / "app.js").read_text(encoding="utf-8")
        urls = set(re.findall(r"https?://[^\s\"'`)]+", js))
        self.assertEqual(urls, {"http://www.w3.org/2000/svg"})           # SVG namespace only
        self.assertEqual(re.findall(r"fetch\(([^)]*)\)", js),
                         ["VERSION_URL, { cache: \"no-store\" }", "BUNDLE_URL"])
        self.assertIn('const VERSION_URL = "data/version.json"', js)
        self.assertIn('const BUNDLE_URL = "data/bundle.json"', js)
        code = re.sub(r"/\*.*?\*/|//[^\n]*", "", js, flags=re.S)          # ignore comments
        for banned in ("XMLHttpRequest", "WebSocket", "sendBeacon", "geolocation",
                       "analytics", "gtag", "localStorage", "document.cookie", "api.weather.gov",
                       "innerHTML", "eval("):
            self.assertNotIn(banned, code)

    def test_csp_and_static_fallback(self):
        html = (APP / "index.html").read_text(encoding="utf-8")
        self.assertIn("connect-src 'self'", html)
        self.assertIn("default-src 'self'", html)
        self.assertNotRegex(html, r"(src|href)=\"https?://")
        for c in COUNTIES:
            for h in HAZARDS:
                self.assertIn(f'href="playbooks/{c}_{h}.pdf"', html)
        self.assertIn("Planning aid. Supports, does not replace, county emergency plans.", html)
        headers = (APP / "_headers").read_text(encoding="utf-8")
        self.assertIn("geolocation=()", headers)
        self.assertIn("connect-src 'self'", headers)

    def test_manifest_and_png_icons(self):
        m = json.loads((APP / "manifest.webmanifest").read_text(encoding="utf-8"))
        self.assertEqual(m["display"], "standalone")
        sizes = {i["sizes"] for i in m["icons"]}
        self.assertTrue({"192x192", "512x512"} <= sizes)
        for i in m["icons"]:
            self.assertTrue((APP / i["src"]).exists(), i["src"])
        for n in (180, 192, 512):
            png = (APP / f"icon-{n}.png").read_bytes()
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(int.from_bytes(png[16:20], "big"), n)        # IHDR width
        self.assertIn('<link rel="apple-touch-icon" href="icon-180.png">',
                      (APP / "index.html").read_text(encoding="utf-8"))


def _lum(hexc):
    hexc = hexc.lstrip("#")
    rgb = [int(hexc[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class Accessibility(unittest.TestCase):
    def setUp(self):
        css = (APP / "styles.css").read_text(encoding="utf-8")
        self.css = css
        self.v = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", css))

    def test_wcag_aa_text_contrast(self):
        pairs = [("color-text", "color-bg"), ("color-muted", "color-bg"),
                 ("color-accent", "color-bg"), ("color-accent-text", "color-accent"),
                 ("color-text", "color-surface"), ("color-muted", "color-surface"),
                 ("color-warn-text", "color-warn-bg"),
                 ("color-offline-text", "color-offline-bg")]
        for fg, bg in pairs:
            self.assertGreaterEqual(contrast(self.v[fg], self.v[bg]), 4.5, (fg, bg))
        self.assertGreaterEqual(contrast(self.v["color-focus"], self.v["color-bg"]), 3.0)

    def test_min_text_size(self):
        self.assertIn("--font-size-small: 14px", self.css)
        for size in re.findall(r"font-size:\s*(\d+)px", self.css):
            self.assertGreaterEqual(int(size), 14)
        self.assertIn(":focus-visible", self.css)

    def test_map_ramp_is_grayscale_ordered(self):
        lums = [_lum(c) for c in svgmap.RAMP]
        self.assertEqual(lums, sorted(lums, reverse=True))        # lighter -> darker
        js_ramp = [self.v[f"ramp-{i}"] for i in range(1, 6)]
        self.assertEqual([c.lower() for c in js_ramp], [c.lower() for c in svgmap.RAMP])


class SvgMap(unittest.TestCase):
    def test_simplify_keeps_ends_and_closes(self):
        ring = [[0, 0], [1, 0.0001], [2, 0], [2, 2], [0, 2], [0, 0]]
        s = svgmap.simplify(ring, 0.01)
        self.assertEqual((s[0], s[-1]), (ring[0], ring[-1]))
        self.assertNotIn([1, 0.0001], s)

    def test_classify_and_projection(self):
        cls, bounds = svgmap.classify({"a": 1, "b": 2, "c": 3, "d": 4, "e": 5, "z": 0})
        self.assertEqual(len(bounds), 5)
        self.assertNotIn("z", cls)
        self.assertEqual(cls["a"], 0)
        self.assertEqual(cls["e"], 4)
        proj = svgmap.Projection((-157, 20, -156, 21), 100, 100, pad=0)
        x0, y0 = proj(-157, 21)
        self.assertEqual((x0 >= 0, y0 >= 0), (True, True))
        self.assertLess(proj(-156.5, 20.5)[1], proj(-156.5, 20.1)[1])   # north is up

    def test_render_has_title_and_markers(self):
        f = {"type": "Feature", "properties": {"tract_fips": "1"},
             "geometry": {"type": "Polygon", "coordinates": [[[-157, 20], [-156, 20], [-156, 21], [-157, 20]]]}}
        svg, _ = svgmap.render([f], {"1": 10}, {"1"},
                               [{"n": 1, "lon": -156.5, "lat": 20.3, "status": "exclude"}], "T & co")
        self.assertIn("<title id=\"maptitle\">T &amp; co</title>", svg)
        self.assertIn("<rect x=", svg)                                   # excluded = square
