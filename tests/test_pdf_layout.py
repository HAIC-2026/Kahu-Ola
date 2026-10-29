"""Printed playbooks: no text outside the printable area, text at true size (>= 9 pt),
every source URL complete in the text (after joining wrapped lines) and clickable."""
import html
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_playbooks as bp  # noqa: E402

PDFS = sorted((ROOT / "playbooks").glob("*.pdf"))
MARGIN = 0.6 * 72                 # @page side margins: 0.6 in
TOL = 0.5                         # points
WORD = re.compile(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">([^<]*)</word>')


def bbox_pages(pdf: Path) -> list:
    """[(page width, [(xMin, yMin, xMax, yMax, word)])] from pdftotext -bbox."""
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "b.html"
        subprocess.run(["pdftotext", "-bbox", str(pdf), str(out)], check=True, capture_output=True)
        data = out.read_text(encoding="utf-8")
    pages = []
    for p in re.split(r"<page ", data)[1:]:
        w = float(re.search(r'width="([\d.]+)"', p).group(1))
        pages.append((w, [(float(a), float(b), float(c), float(e), html.unescape(t))
                          for a, b, c, e, t in WORD.findall(p)]))
    return pages


@unittest.skipUnless(shutil.which("pdftotext"), "pdftotext not installed")
class Layout(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = {p.name: bbox_pages(p) for p in PDFS}

    def test_no_text_outside_printable_area(self):
        self.assertEqual(len(PDFS), 20)
        for name, pages in self.pages.items():
            for i, (w, words) in enumerate(pages, 1):
                for x0, _y0, x1, _y1, t in words:
                    self.assertLessEqual(x1, w - MARGIN + TOL, f"{name} p{i}: {t[:60]}")
                    self.assertGreaterEqual(x0, MARGIN - TOL, f"{name} p{i}: {t[:60]}")

    def test_true_size_text(self):
        """No shrink-to-fit: the smallest CSS text is 9 pt (word box about 10 pt high)."""
        for name, pages in self.pages.items():
            heights = [y1 - y0 for _w, words in pages for _x0, y0, _x1, y1, _t in words]
            self.assertGreaterEqual(min(heights), 9.0, name)


@unittest.skipUnless(shutil.which("pdftotext"), "pdftotext not installed")
class Urls(unittest.TestCase):
    URLS = [html.unescape(c) for _a, _b, c in bp.data_sources(bp.load_inputs())
            if c.startswith(("http://", "https://"))]

    def test_every_source_url_complete_after_joining_lines(self):
        """Read the URL column only (word positions right of the Source and Fetched columns,
        24% + 11% of the text width), in reading order, and join its wrapped lines."""
        self.assertGreater(len(self.URLS), 20)
        for pdf in PDFS:
            pages = bbox_pages(pdf)
            cols = []
            for i, (w, words) in enumerate(pages):
                x_url = MARGIN + 0.35 * (w - 2 * MARGIN) - 2
                cols += [(i, round(y0), x0, t) for x0, y0, _x1, _y1, t in words if x0 >= x_url]
            joined = "".join(t for *_k, t in sorted(cols))
            for u in self.URLS:
                self.assertIn(u, joined, (pdf.name, u))

    def test_every_source_url_is_a_link(self):
        for pdf in PDFS:
            raw = pdf.read_bytes()
            for u in self.URLS:
                self.assertIn(u.encode(), raw, (pdf.name, u))    # link annotation target

    def test_sources_table_fixed_columns(self):
        t = (ROOT / "playbooks" / "maui_tsunami.html").read_text(encoding="utf-8")
        self.assertIn('<table class="sources-table"><colgroup><col class="c-src"><col class="c-date"><col class="c-url"></colgroup>', t)
        self.assertRegex(t, r"table\.sources-table \{ table-layout: fixed;")
        for rule in ("col.c-src { width: 24%; }",
                     "col.c-date { width: 11%; }", "col.c-url { width: 65%; }",
                     "td.url { overflow-wrap: anywhere; }", "td.url a { word-break: break-all; }"):
            self.assertIn(rule, t)

    def test_linkify_keeps_url_text_and_skips_tags(self):
        out = bp.linkify('<p>See https://a.gov/x.pdf.</p><a href="https://b.gov">https://b.gov</a>'
                         '<style>p{}</style>')
        self.assertIn('<a href="https://a.gov/x.pdf">https://a.gov/x.pdf</a>.', out)
        self.assertEqual(out.count('href="https://b.gov"'), 1)


if __name__ == "__main__":
    unittest.main()
