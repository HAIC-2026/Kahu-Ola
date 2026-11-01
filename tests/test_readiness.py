"""Page 1 readiness sheet and the "After the event" section of every playbook.

Readiness sheet: one printed page with county, hazard, data date, the planning-aid and privacy
lines, the county risk-area totals (± an approximate MOE for the sum where the source has
one), the top 3 stress-test findings, the usable 2026 sites (names only) and the partner
checklist (roles; Before / During / After). It holds county totals only: no per-area count.
After the event: static text, agency names only, no figures."""
import re
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_playbooks as bp  # noqa: E402
import privacy  # noqa: E402

PLAY = ROOT / "playbooks"
PAIRS = [(c, h) for c in bp.COUNTY_LABEL for h in bp.HAZARD_LABEL]


def readiness(src: str) -> str:
    m = re.search(r'<section class="readiness">.*?</section>', src, re.S)
    return m.group(0) if m else ""


def after(src: str) -> str:
    m = re.search(r'<section class="page after">.*?</section>', src, re.S)
    return m.group(0) if m else ""


def text(fragment: str) -> str:
    import html
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


class ReadinessHtml(unittest.TestCase):
    def test_contents(self):
        for c, h in PAIRS:
            src = (PLAY / f"{bp.slug(c, h)}.html").read_text(encoding="utf-8")
            r = readiness(src)
            self.assertTrue(r, (c, h))
            self.assertLess(src.index(r), src.index("1. Summary"), (c, h))       # page 1
            t = text(r)
            for want in (bp.COUNTY_LABEL[c], bp.HAZARD_LABEL[h], "Data as of", bp.DISCLAIMER,
                         privacy.PRIVACY_LINE, bp.COL["at_risk"], "May need a public shelter (low – high)",
                         bp.COL["lep"], bp.COL["power"], bp.COL["disability"], bp.COL["age65_alone"],
                         bp.COL["no_car"], "stress-test findings", "Stress test, not a forecast",
                         "Usable 2026 sites for this hazard", "Partner checklist", "Before", "During", "After"):
                self.assertIn(want, t, (c, h, want))
            for role, *_ in bp.CHECKLIST_ROLES:
                self.assertIn(role, t, (c, h))
            self.assertNotIn('class="ac"', r, (c, h))                           # no per-area cell

    def test_county_totals_and_moe(self):
        inp = bp.load_inputs()
        for c, h in PAIRS:
            sc = bp.scenario(inp, c, h)
            r = readiness((PLAY / f"{bp.slug(c, h)}.html").read_text(encoding="utf-8"))
            for field, key in bp.READINESS_FIELDS:
                v = bp.n(sc[key])
                moe = None if field == "power" else bp.county_moe(inp, c, h, field)
                want = f"{v} ± {round(moe):,}" if moe is not None else v
                self.assertIn(f">{want}<", r, (c, h, field))
            self.assertIn(f'{bp.n(sc["shelter_demand_low"])} – {bp.n(sc["shelter_demand_high"])}', r)
            self.assertIsNone(bp.county_moe(inp, c, h, "power"))

    def test_nowrap_on_ranges_dates_and_moe(self):
        for c, h in PAIRS:
            r = readiness((PLAY / f"{bp.slug(c, h)}.html").read_text(encoding="utf-8"))
            self.assertRegex(r, r'<span class="nw">\d{4}-\d\d-\d\d</span>')
            for m in re.finditer(r"[\d,]+ (?:±|–) [\d,]+", text(r)):
                self.assertIn(f'<span class="nw">{m.group(0)}</span>', r, (c, h, m.group(0)))

    def test_sites_are_names_of_usable_sites(self):
        inp = bp.load_inputs()
        for c, h in PAIRS:
            r = text(readiness((PLAY / f"{bp.slug(c, h)}.html").read_text(encoding="utf-8")))
            for s in bp.sites_for(inp, c, h):
                if s["status"] == "ok":
                    self.assertIn(s["name"], r, (c, h))


@unittest.skipUnless(shutil.which("pdftotext"), "pdftotext not installed")
class ReadinessPdf(unittest.TestCase):
    def page(self, pdf, n):
        return " ".join(subprocess.run(["pdftotext", "-f", str(n), "-l", str(n), str(pdf), "-"],
                                       capture_output=True, text=True, check=True).stdout.split())

    def test_one_page_no_small_per_area_count(self):
        for c, h in PAIRS:
            pdf = PLAY / f"{bp.slug(c, h)}.pdf"
            p1, p2 = self.page(pdf, 1), self.page(pdf, 2)
            self.assertIn("Readiness sheet", p1, pdf.name)
            self.assertIn("Roles are proposals, to be confirmed with each partner", p1, pdf.name)  # last line fits
            self.assertNotIn("Partner checklist", p2, pdf.name)
            self.assertTrue(p2.startswith("Data as of"), pdf.name)                 # page 2 is the summary
            self.assertNotRegex(p1, r"(?<![\d,.])[1-9] ± \d|\([1-9] to |to [1-9] people\)", pdf.name)


class AfterTheEvent(unittest.TestCase):
    def test_section(self):
        for c, h in PAIRS:
            a = after((PLAY / f"{bp.slug(c, h)}.html").read_text(encoding="utf-8"))
            t = text(a)
            for want in ("11. After the event", "temporary housing", "SNAP", "Med-QUEST",
                         "disaster assistance", "check current rules with the agency",
                         "Language access in recovery", "When to rerun the plan"):
                self.assertIn(want, t, (c, h, want))
            body = t.replace("11. After the event", "").replace("section 7", "")
            self.assertNotRegex(body, r"\d", (c, h))                                # no figures
            self.assertNotRegex(t.lower(), r"\beligible\b|\bqualif", (c, h))       # no eligibility claims


if __name__ == "__main__":
    unittest.main()
