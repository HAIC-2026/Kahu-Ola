"""Offline tests for the MATCH step and language access: python3 -m unittest discover tests"""
import csv
import json
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import fetch_languages as fl  # noqa: E402
import match as mt  # noqa: E402

PARTNERS = json.loads((ROOT / "config" / "partners.json").read_text(encoding="utf-8"))
DP = json.loads((ROOT / "config" / "decision_points.json").read_text(encoding="utf-8"))
COMM = json.loads((ROOT / "config" / "communication.json").read_text(encoding="utf-8"))
REQUIRED_TYPES = {"dhs", "county_em", "hiema", "doe", "hspls", "doh", "dot", "oha", "red_cross",
                  "salvation_army", "hawaii_voad", "faith_based", "health_care", "utilities",
                  "philanthropy", "business_community", "other_agencies"}
REQUIRED_FUNCS = {"shelter_operations", "feeding", "afn_support_medical", "power_medical_devices",
                  "transportation", "language_access", "pets", "donations_volunteers"}
LANGS = {"Maui": [{"language": "Ilocano", "area": "Kauai + Maui",
                   "speak_english_less_than_very_well": 800, "moe_90": 90,
                   "share_of_area_lep": 0.8, "rank": 1},
                  {"language": "Spanish", "area": "Kauai + Maui",
                   "speak_english_less_than_very_well": 200,
                   "moe_90": 40, "share_of_area_lep": 0.2, "rank": 2}],
         "Kauai": [], "Honolulu": [], "Hawaii": []}


def scenario(county="Maui", hazard="tsunami", **kw):
    s = {"county": county, "hazard": hazard, "scope": "x", "shelter_demand_low": 40,
         "shelter_demand_central": 100, "shelter_demand_high": 220, "cots": 100,
         "floor_sqft_72h": 2000, "floor_sqft_2wk": 4000, "water_gal_per_day": 100,
         "meals_per_day": 200, "toilets_72h": 3, "toilets_2wk": 5, "staff_per_shift": 9,
         "power_outlets": 2, "T_no_vehicle_persons_at_risk": 70, "dog_households": 18,
         "cat_households": 11, "S_children_in_shelter": 22, "C_lep_in_shelter": 10,
         "known_sites_usable": 3}
    s.update(kw)
    return s


def tract_row(fips, county="Maui", hazard="tsunami", p=0, d=0, c=0, t=0):
    return {"tract_fips": fips, "county": county, "hazard": hazard, "at_risk_pop": "1000",
            "M_power_dependent_at_risk": str(p), "I_disability_at_risk": str(d),
            "C_lep_at_risk": str(c), "T_no_vehicle_persons_at_risk": str(t)}


class PartnerTemplate(unittest.TestCase):
    def test_all_challenge_partner_types_and_functions(self):
        types = {p["partner_type"] for p in PARTNERS["partners"]}
        self.assertEqual(types, REQUIRED_TYPES)
        self.assertEqual(set(PARTNERS["functions"]), REQUIRED_FUNCS)
        self.assertEqual(sorted(p["county"] for p in PARTNERS["partners"]
                                if p["partner_type"] == "county_em"),
                         ["Hawaii", "Honolulu", "Kauai", "Maui"])

    def test_roles_are_proposals_with_no_invented_capacity_or_contacts(self):
        self.assertIn("HAIC_AI Challenge_Submission_DHS_Disaster_2026.pdf",
                      PARTNERS["source"]["document"])
        for p in PARTNERS["partners"]:
            self.assertTrue(p["listed_in_challenge"])
            self.assertIsNone(p["contact"])
            self.assertIsNone(p["capacity_confirmed_by"])
            for f in p["functions"]:
                self.assertEqual(f["status"], "proposed – to be confirmed with partner")
                self.assertIn(f["role"], ("lead", "support"))
                self.assertIn(f["function"], REQUIRED_FUNCS)
            for fields in p["capacity"].values():
                self.assertTrue(all(v is None for v in fields.values()))
        text = json.dumps(PARTNERS)
        self.assertNotRegex(text, r"\(?\d{3}\)?[ -]\d{3}-\d{4}")          # no phone numbers
        self.assertNotIn("@", text)                                       # no emails

    def test_every_function_has_a_lead_in_every_county(self):
        for c in ("Kauai", "Honolulu", "Maui", "Hawaii"):
            for fn in REQUIRED_FUNCS:
                self.assertTrue(mt.partners_for(PARTNERS["partners"], fn, c)["lead"], (c, fn))

    def test_county_partners_scoped_to_their_county(self):
        ps = [{"partner_type": "county_em", "county": "Kauai",
               "functions": [{"function": "pets", "role": "lead"}]},
              {"partner_type": "hawaii_voad",
               "functions": [{"function": "pets", "role": "support"}]}]
        self.assertEqual(mt.partners_for(ps, "pets", "Maui"), {"lead": [], "support": ["hawaii_voad"]})
        self.assertEqual(mt.partners_for(ps, "pets", "Kauai")["lead"], ["county_em"])


class Pledges(unittest.TestCase):
    def test_blank_pledge_means_unknown_gap(self):
        self.assertIsNone(mt.pledged(PARTNERS["partners"], ("shelter_operations", "cots"), "Maui"))
        self.assertEqual(mt.gap_text(100, None), "unknown – confirm with partner")

    def test_pledges_counted_per_county_never_double(self):
        ps = [{"county": "Maui", "capacity": {"shelter_operations": {"cots": 60}}},
              {"county": "Kauai", "capacity": {"shelter_operations": {"cots": 999}}},
              {"capacity": {"shelter_operations": {"cots": {"Maui": 30, "Kauai": 5}}}},
              {"capacity": {"shelter_operations": {"cots": 500}}}]      # unallocated statewide
        self.assertEqual(mt.pledged(ps, ("shelter_operations", "cots"), "Maui"), 90)
        self.assertEqual(mt.gap_text(100, 90), "shortfall 10")
        self.assertEqual(mt.gap_text(80, 90), "covered")
        self.assertIsNone(mt.pledged(ps, None, "Maui"))


class Needs(unittest.TestCase):
    def setUp(self):
        self.lines = mt.need_lines(scenario(), PARTNERS["partners"], LANGS["Maui"])
        self.by = {l["need"]: l for l in self.lines}

    def test_every_need_line_present(self):
        for need, *_ in mt.NEEDS:
            self.assertIn(need, self.by)
        self.assertEqual(self.by["Cots / sleeping space"]["quantity"], 100)
        self.assertEqual(self.by["Accessible transport"]["quantity"], 70)
        self.assertEqual(self.by["Power outlets for power-dependent residents"]["lead_partner_types"], "doh")

    def test_interpreters_by_language(self):
        self.assertEqual(self.by["Interpreters – Ilocano"]["quantity"], 8)
        self.assertIn("ACS PUMS 2019-2023", self.by["Interpreters – Ilocano"]["basis"])
        self.assertEqual(self.by["Interpreters – Spanish"]["quantity"], 2)
        self.assertEqual(self.by["Interpreters – Spanish"]["language"], "Spanish")

    def test_lead_and_support_and_gap(self):
        cots = self.by["Cots / sleeping space"]
        self.assertEqual(cots["lead_partner_types"], "county_em")
        self.assertIn("red_cross", cots["support_partner_types"])
        staff = self.by["Shelter staff"]
        self.assertIn("hawaii_voad", staff["support_partner_types"])      # 2nd function's lead
        self.assertNotIn("county_em", staff["support_partner_types"])     # already lead
        for l in self.lines:
            self.assertEqual(l["pledged_capacity"], "")
            self.assertEqual(l["gap"], "unknown – confirm with partner")
            self.assertTrue(l["status"].startswith("proposed"))


class DecisionPoints(unittest.TestCase):
    def test_official_triggers_with_sources(self):
        products = {t["product"] for t in DP["triggers"].values()}
        for p in ("Hurricane Watch", "Hurricane Warning", "Tsunami Warning",
                  "Flash Flood Warning", "Red Flag Warning"):
            self.assertIn(p, products)
        for k in ("hurricane_watch", "hurricane_warning", "tsunami_warning",
                  "flash_flood_warning", "red_flag_warning", "coastal_flood_warning",
                  "pre_season_hurricane"):
            self.assertTrue(DP["triggers"][k]["url"].startswith("https://www."))
            self.assertTrue(DP["triggers"][k]["definition"])

    def test_tables_ordered_and_marked_proposed(self):
        types = {p["partner_type"] for p in PARTNERS["partners"]}
        for hz in ("hurricane", "wildfire", "tsunami", "inland_flood", "coastal_flood"):
            t = mt.decision_table(DP, hz, PARTNERS["partners"])
            self.assertTrue(t)
            order = [DP["timing_order"].index(r["timing"]) for r in t]
            self.assertEqual(order, sorted(order))
            for r in t:
                self.assertEqual(r["status"], "proposed – supports, does not replace, county plans")
                self.assertIn(r["owner"], types)
                for s in filter(None, r["support"].split("; ")):
                    self.assertIn(s, types)

    def test_no_notice_hazards_preposition_before_season(self):
        for hz in DP["no_notice_hazards"]:
            first = mt.decision_table(DP, hz, PARTNERS["partners"])[0]
            self.assertEqual(first["timing"], "before")
            self.assertIn("PRE-POSITION", first["action"])
            self.assertIn("pre-positioning", first["trigger"])


class Communication(unittest.TestCase):
    def test_message_library_header_only_and_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            lib = mt.ensure_message_library(LANGS, COMM, root)
            self.assertEqual([l["language"] for l in lib],
                             ["English", "Ilocano", "Spanish"])
            p = root / "data/sources/messages/spanish.csv"
            self.assertEqual(p.read_text(encoding="utf-8").strip(),
                             ",".join(COMM["message_library"]["columns"]))
            with open(p, "a", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(["m1", "tsunami", "tsunami_warning", "during", "radio",
                                         "Spanish", "texto", "t", "", "", "no"])
            lib = mt.ensure_message_library(LANGS, COMM, root)
            sp = [l for l in lib if l["language"] == "Spanish"][0]
            self.assertEqual(sp["templates"], 1)
            self.assertEqual(sp["approved_templates"], 0)       # not reviewed -> not approved

    def library(self):
        out = {}
        for p in sorted((ROOT / "data/sources/messages").glob("*.csv")):
            with open(p, newline="", encoding="utf-8") as fh:
                out[p.name] = list(csv.DictReader(fh))
        return out

    def test_no_approved_row_without_a_reviewer(self):
        lib = COMM["message_library"]
        for name, rows in self.library().items():
            for r in rows:
                if r["approved"].lower() == "yes":
                    self.assertTrue(r["reviewed_by"] and r["review_date"], (name, r["message_id"]))
                else:
                    self.assertEqual(r["approved"], "no", (name, r["message_id"]))
                if not r["reviewed_by"]:                       # unreviewed -> must say so
                    self.assertEqual(r["approved"], "no")
                    self.assertTrue(r["status"].startswith(("DRAFT", "NEEDS HUMAN")), r["status"])
                if r["language"] != "English" and r["text"] and not r["reviewed_by"]:
                    self.assertEqual(r["status"], lib["draft_status_translation"], name)

    def test_drafts_cover_every_hazard_and_message(self):
        ids = {f"{h}-{k}" for h in ("hurricane", "wildfire", "tsunami", "inland_flood",
                                    "coastal_flood") for k in ("pre", "evac", "shelter")}
        for name, rows in self.library().items():
            self.assertEqual(list(rows[0]), COMM["message_library"]["columns"], name)
            self.assertEqual({r["message_id"] for r in rows}, ids, name)

    def test_vietnamese_assigned_to_kim(self):
        rows = self.library()["vietnamese.csv"]
        self.assertTrue(all(r["review_assignee"] == "Kim Quynh Do" for r in rows))
        self.assertTrue(all(r["text"] and not r["reviewed_by"] for r in rows))

    def test_english_makes_no_promises_counties_have_not_made(self):
        for r in self.library()["english.csv"]:
            t = r["text"].lower()
            for banned in ("police", "law enforcement", "immigration", "guarantee", "safe from",
                           "will be safe", "we will", "pets are allowed", "pets allowed"):
                self.assertNotIn(banned, t, r["message_id"])
            if r["message_id"].endswith("shelter") or r["message_id"].endswith("evac"):
                self.assertRegex(t, r"county announcements|officials|call 911")

    def test_county_pathways(self):
        lib = [{"language": "Spanish", "approved_templates": 0}]
        c = mt.communication(LANGS, COMM, lib)
        self.assertEqual(c["Maui"]["top_languages_lep"][0]["language"], "Ilocano")
        self.assertEqual(c["Maui"]["language_area"], "Kauai + Maui")
        self.assertEqual({ch["channel"] for ch in c["Maui"]["channels"]},
                         {"official_alerts", "radio", "sirens", "trusted_messengers",
                          "printed_notices"})
        self.assertEqual(c["Maui"]["message_library_status"], "no approved templates yet")


class PriorityTracts(unittest.TestCase):
    def test_top_ten_by_afn_need_tract_level_only(self):
        rows = [tract_row(f"150090{i:05d}", p=i, d=i, c=i, t=i) for i in range(15)]
        rows.append(tract_row("15001000001", county="Hawaii", p=999))
        rows.append(tract_row("15009099999", hazard="wildfire", p=999))
        top = mt.priority_tracts(rows, "Maui", "tsunami")
        self.assertEqual(len(top), 10)
        self.assertEqual(top[0]["tract_fips"], "15009000014")
        self.assertEqual(top[0]["afn_need_sum"], 56.0)
        self.assertEqual([t["rank"] for t in top], list(range(1, 11)))
        for t in top:
            self.assertEqual(set(t), {"rank", "tract_fips", "tract_label", "label_main", "label_sub", "at_risk_pop",
                                      "power_dependent",
                                      "disability", "limited_english", "no_vehicle",
                                      "afn_need_sum"})


class EndToEnd(unittest.TestCase):
    def test_run_is_offline_and_complete(self):
        needs = {"built_at": "t", "scenarios": [scenario(), scenario(hazard="wildfire")]}
        rows = [tract_row("15009000001", p=5), tract_row("15009000002", hazard="wildfire", d=3)]
        with mock.patch.object(urllib.request, "urlopen",
                               side_effect=AssertionError("network call in MATCH")):
            plan = mt.run(needs, rows, PARTNERS, DP, COMM, LANGS, [], [])
        self.assertEqual(len(plan["scenarios"]), 2)
        self.assertEqual(set(plan["decision_points"]), {"tsunami", "wildfire"})
        self.assertIn("No individual records", plan["privacy"])
        self.assertEqual(plan["scenarios"][0]["priority_tracts"][0]["tract_fips"], "15009000001")
        self.assertEqual(json.dumps(plan), json.dumps(
            mt.run(needs, rows, PARTNERS, DP, COMM, LANGS, [], [])))      # deterministic


class Languages(unittest.TestCase):
    LABELS = {
        "C16001_001E": {"label": "Estimate!!Total:"},
        "C16001_002E": {"label": "Estimate!!Total:!!Speak only English"},
        "C16001_003E": {"label": "Estimate!!Total:!!Spanish:"},
        "C16001_004E": {"label": 'Estimate!!Total:!!Spanish:!!Speak English "very well"'},
        "C16001_005E": {"label": 'Estimate!!Total:!!Spanish:!!Speak English less than "very well"'},
        "C16001_027E": {"label": "Estimate!!Total:!!Tagalog (incl. Filipino):"},
        "C16001_029E": {"label": 'Estimate!!Total:!!Tagalog (incl. Filipino):!!Speak English less than "very well"'},
    }

    def response(self):
        h = ["GEO_ID", "NAME", "C16001_003E", "C16001_005E", "C16001_005M",
             "C16001_027E", "C16001_029E", "C16001_029M"]
        return {"response": {"dataAPIURI": "https://api.census.gov/x", "data": [h,
                ["0500000US15009", "Maui", "500", "100", "30", "900", "300", "40"],
                ["0500000US15005", "Kalawao", "10", "5", "-555555555", "0", "0", "0"],
                ["0500000US15007", "Kauai", "50", "20", "10", "400", "200", "30"]]}}

    def test_language_vars_from_labels(self):
        self.assertEqual(fl.language_vars(self.LABELS),
                         {"Spanish": ("C16001_003E", "C16001_005E"),
                          "Tagalog (incl. Filipino)": ("C16001_027E", "C16001_029E")})

    def test_tidy_merges_kalawao_ranks_and_shares(self):
        rows = fl.tidy(self.response(), self.LABELS, "t")
        maui = [r for r in rows if r["county"] == "Maui"]
        self.assertEqual([r["language"] for r in maui], ["Tagalog (incl. Filipino)", "Spanish"])
        sp = maui[1]
        self.assertEqual(sp["speak_english_less_than_very_well"], 105)       # 100 + Kalawao 5
        self.assertEqual(sp["speakers_5plus"], 510)
        self.assertEqual(sp["moe_90"], 30)                                     # sentinel ignored
        self.assertAlmostEqual(sp["share_of_county_lep"], round(105 / 405, 4))
        self.assertEqual(maui[0]["moe_90"], 40)
        self.assertEqual(sp["api_url"], "https://api.census.gov/x")
        self.assertEqual({r["county"] for r in rows}, {"Maui", "Kauai"})   # Kalawao folded in
        self.assertNotIn("NAME", rows[0])

    def test_c16001_kept_as_secondary_source(self):
        self.assertTrue(str(fl.OUT).endswith("languages_by_county_c16001.csv"))
        with open(fl.OUT, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual({r["county"] for r in rows}, {"Kauai", "Honolulu", "Maui", "Hawaii"})
        self.assertTrue(all(r["table"] == "C16001" and r["source_url"] for r in rows))


if __name__ == "__main__":
    unittest.main()
