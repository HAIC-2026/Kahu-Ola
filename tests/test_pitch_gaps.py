"""Pitch gaps: how to reach residents, more CMIST detail, county lines, high-rise homes,
trust decision point, service animals, island names, who else to plan for, results."""
import csv
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_playbooks as bp  # noqa: E402

APP = ROOT / "app"
PLAY = ROOT / "playbooks"
PROC = ROOT / "data" / "processed"
BUNDLE = json.loads((APP / "data" / "bundle.json").read_text(encoding="utf-8"))
JS = (APP / "app.js").read_text(encoding="utf-8")
PAGES = sorted(p for p in PLAY.glob("*.html") if p.name != "index.html")
NEEDS = json.loads((PROC / "needs_by_scenario.json").read_text(encoding="utf-8"))["scenarios"]
with open(PROC / "needs_by_tract.csv", newline="", encoding="utf-8") as fh:
    TRACT_ROWS = list(csv.DictReader(fh))
AFN = {f["properties"]["tract_fips"]: f["properties"] for f in
       json.loads((PROC / "afn_tracts.geojson").read_text(encoding="utf-8"))["features"]}
LINES = list(csv.DictReader(open(ROOT / "data" / "sources" / "county_lines.csv", encoding="utf-8")))


def html(p):
    return p.read_text(encoding="utf-8")


class Reach(unittest.TestCase):
    def test_channels_and_formats(self):
        text = " ".join(c[0] for c in BUNDLE["reach"]["channels"])
        for word in ("Wireless Emergency Alerts", "Emergency Alert System", "county alert sign-ups",
                     "radio", "sirens", "Trusted community messengers", "Printed notices"):
            self.assertIn(word, text)
        formats = [f[0] for f in BUNDLE["reach"]["formats"]]
        self.assertEqual(formats, ["ASL video", "Captions", "Large print", "Plain language",
                                   "Screen-reader-friendly text"])
        for p in PAGES:
            t = html(p)
            self.assertIn("How to reach residents", t)
            for f in formats:
                self.assertIn(f, t, p.name)
        self.assertIn('"How to reach residents"', JS)


class CmistDetail(unittest.TestCase):
    FIELDS = {"C_hearing_at_risk": "C_hearing_difficulty", "C_vision_at_risk": "C_vision_difficulty",
              "I_cognitive_at_risk": "I_cognitive_difficulty",
              "S_age65_alone_at_risk": "S_age65_living_alone"}

    def test_source_table(self):
        rows = list(csv.DictReader(open(ROOT / "data" / "sources" / "cmist_detail_by_tract.csv",
                                        encoding="utf-8")))
        self.assertGreaterEqual(len(rows), 436)
        for r in rows:
            self.assertEqual(r["vintage"], "ACS 2020-2024 5-year")
            self.assertIn("ACSDT5Y2024.B18102", r["tables"])
            self.assertTrue(r["source_url"].startswith("https://data.census.gov/"))

    def test_map_and_model(self):
        with_data = [p for p in AFN.values() if p.get("C_hearing_difficulty") is not None]
        self.assertGreaterEqual(len(with_data), 430)
        for r in TRACT_ROWS[:200]:
            t = AFN[r["tract_fips"]]
            for model, src in self.FIELDS.items():
                want = (t.get(src) or 0) * float(r["share_at_risk"])
                self.assertAlmostEqual(float(r[model]), want, delta=0.02 * want + 1)
        for sc in NEEDS:
            rows = [r for r in TRACT_ROWS if r["county"] == sc["county"] and r["hazard"] == sc["hazard"]]
            for model in self.FIELDS:
                self.assertAlmostEqual(sc[model], sum(float(r[model]) for r in rows), delta=len(rows))

    def test_shown_in_kpis_tables_and_playbooks(self):
        for k in ("hearing", "vision", "cognitive", "age65_alone"):
            for p in PAGES:
                self.assertIn(bp.COL[k], html(p), p.name)
        self.assertIn("More needs in the largest communities", html(PAGES[0]))
        sc = BUNDLE["scenarios"]["Maui|hurricane"]
        for model in self.FIELDS:
            self.assertIn(model, sc["summary"])
            self.assertIn(model, sc["largest"][0])
        self.assertIn("DATA.meta.detail_keys", JS)


class CountyLines(unittest.TestCase):
    def test_sourced_and_separate(self):
        self.assertEqual({(r["county"], r["line"]) for r in LINES},
                         {(c, l) for c in ("Honolulu", "Hawaii", "Maui", "Kauai")
                          for l in ("homelessness", "visitors")})
        for r in LINES:
            self.assertTrue(r["source_url"].startswith("https://"), r)
            self.assertTrue(r["source"] and r["period"])
        # never added to Census-area totals
        for sc in NEEDS:
            rows = [r for r in TRACT_ROWS if r["county"] == sc["county"] and r["hazard"] == sc["hazard"]]
            self.assertEqual(sc["at_risk_pop"], round(sum(float(r["at_risk_pop"]) for r in rows)))
        for p in PAGES:
            self.assertIn("Also plan for (county counts, not included in the totals above)", html(p))

    def test_visitor_numbers_match_dbedt(self):
        raw = ROOT / "data" / "raw" / "visitors" / "DB2025_section07.xlsx"
        if not raw.exists():
            self.skipTest("DBEDT file not cached")
        from build_demographics import xlsx_sheet
        table = {r[0]: r[2] for r in xlsx_sheet(raw, "07.06")}
        want = {"Honolulu": table["Oahu"], "Hawaii": table["Hawaii"], "Kauai": table["Kauai"],
                "Maui": table["Maui County"]}
        for r in LINES:
            if r["line"] == "visitors":
                self.assertEqual(r["value"], want[r["county"]], r["county"])

    def test_pit_numbers_match_btg_report(self):
        txt = ROOT / "data" / "raw" / "pit" / "btg.txt"
        if not txt.exists():
            self.skipTest("BTG report text not cached")
        text = txt.read_text(encoding="utf-8")
        for county, table in (("Hawaii", "Table 5:"), ("Kauai", "Table 19:"), ("Maui", "Table 23:")):
            block = text[text.index(table):text.index(table) + 4000]
            total = re.search(r"^ Total\s+.*?([\d,]+)\s*$", block, re.M).group(1).replace(",", "")
            got = next(r for r in LINES if r["county"] == county and r["line"] == "homelessness")
            self.assertEqual(got["value"], total, county)


class HighRise(unittest.TestCase):
    def test_hurricane_only(self):
        for sc in NEEDS:
            if sc["hazard"] == "hurricane":
                want = sum(AFN[f].get("multi_unit_10plus") or 0 for f in AFN
                           if AFN[f]["county"] == sc["county"])
                self.assertAlmostEqual(sc["highrise_units_at_risk"], want, delta=2)
        for p in PAGES:
            self.assertEqual(bp.COL["highrise"] in html(p), p.stem.endswith("_hurricane"), p.name)
        self.assertIn('if (hazard === "hurricane") kpis.push([C.highrise', JS)


class Trust(unittest.TestCase):
    def test_before_row_every_hazard(self):
        dp = json.loads((ROOT / "config" / "decision_points.json").read_text(encoding="utf-8"))
        for hz, rows in dp["decision_points"].items():
            row = next(r for r in rows if r["trigger"] == "shelter_access_notice")
            self.assertEqual((row["timing"], row["owner"]), ("before", "county_em"))
            self.assertIn("who may use shelters and what ID is needed", row["action"])
            self.assertIn("proposed", row["status"])
            shown = [d[3] for d in BUNDLE["decision_points"][hz]]
            self.assertTrue(any("trusted community messengers share it" in a for a in shown), hz)


class SmallLines(unittest.TestCase):
    def test_service_animals_who_else_and_kalawao(self):
        for p in PAGES:
            t = html(p)
            self.assertIn(bp.SERVICE_ANIMALS, t)
            self.assertIn("Who else to plan for", t)
            for k, _ in bp.WHO_ELSE:
                self.assertIn(k, t)
            self.assertEqual(bp.KALAWAO_NOTE in t, p.stem.startswith("maui"), p.name)
        self.assertEqual(BUNDLE["meta"]["service_animals"], bp.SERVICE_ANIMALS)

    def test_island_names(self):
        labels = {t["f"]: t["l"] for t in BUNDLE["tracts"]}
        self.assertEqual(labels["15005031900"], "Kalaupapa (Kalawao) · Census area 319")
        self.assertEqual(labels["15007041200"], "Niʻihau · Census area 412")


class Results(unittest.TestCase):
    def test_numbers_from_data_files(self):
        r = BUNDLE["results"]
        cov = json.loads((PROC / "coverage.json").read_text(encoding="utf-8"))
        counties = [v for v in cov.values() if isinstance(v, dict) and "tracts" in v]
        self.assertEqual(r["tracts"], sum(v["tracts"] for v in counties))
        self.assertEqual(r["with_nri"], sum(v["with_nri"] for v in counties))
        with open(PROC / "backtest.csv", newline="", encoding="utf-8") as fh:
            bt = next(csv.DictReader(fh))
        self.assertEqual(r["backtest"][0]["observed"], bt["observed"])
        timing = json.loads((PROC / "rebuild_timing.json").read_text(encoding="utf-8"))
        self.assertEqual(r["rebuild"]["seconds"], timing["seconds"])
        base = json.loads((ROOT / "config" / "results.json").read_text(encoding="utf-8"))
        self.assertEqual((r["baseline"]["value"], r["baseline"]["unit"]),
                         (base["time_baseline"]["value"], base["time_baseline"]["unit"]))
        self.assertNotIn("PLAN.md", r["baseline"]["source"])
        self.assertIn("function resultsSection()", JS)
        self.assertIn("calibration event, not validation", JS)

    def test_plan_states_measured_time(self):
        timing = json.loads((PROC / "rebuild_timing.json").read_text(encoding="utf-8"))
        plan = (ROOT / "PLAN.md").read_text(encoding="utf-8")
        self.assertIn(f"takes **{timing['seconds']} seconds**", plan)
        self.assertIn(f"all {timing['steps']} build steps", plan)


if __name__ == "__main__":
    unittest.main()
