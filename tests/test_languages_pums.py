"""Offline tests for detailed languages from ACS PUMS: python3 -m unittest discover tests"""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_languages_pums as bp  # noqa: E402
import match as mt  # noqa: E402

SRC = ROOT / "data" / "sources"
COMM = json.loads((ROOT / "config" / "communication.json").read_text(encoding="utf-8"))

# State of Hawaii Data Book 2024, Table 1.44 (DBEDT, ACS PUMS 2019-2023): persons 5+ who
# speak English less than "very well" – the top 10 languages by that count.
DBEDT_1_44 = {"Ilocano": 34269, "Tagalog, Filipino": 27582, "Chinese": 21856,
              "Japanese": 17683, "Korean": 9223, "Spanish": 6471, "Vietnamese": 6265,
              "Chuukese": 5279, "Samoan": 3002, "Other English-based Creole languages": 2720}
MICRODATA_COLUMNS = {"SERIALNO", "SPORDER", "PWGTP", "AGEP", "ENG", "LANP", "PUMA"}


def read(name):
    with open(SRC / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def person(puma="00100", lanp="3150", eng="3", age="40", w=10, rep=None):
    r = {"PUMA": puma, "LANP": lanp, "ENG": eng, "AGEP": age, "PWGTP": str(w)}
    r.update({f"PWGTP{i}": str(rep if rep is not None else w) for i in range(1, 81)})
    return r


class DbedtValidation(unittest.TestCase):
    def test_top10_within_5pct_of_dbedt_table_1_44(self):
        state = {r["language"]: r for r in read("pums_language_state_summary.csv")}
        for lang, dbedt in DBEDT_1_44.items():
            ours = int(state[lang]["speak_english_less_than_very_well"])
            self.assertLessEqual(abs(ours - dbedt) / dbedt, 0.05, (lang, ours, dbedt))

    def test_dbedt_top10_is_our_top10(self):
        state = [r for r in read("pums_language_state_summary.csv") if r["suppressed"] == "False"]
        self.assertEqual({r["language"] for r in state[:10]}, set(DBEDT_1_44))


class Geography(unittest.TestCase):
    def test_puma_nesting_recorded_and_kauai_maui_combined(self):
        rows = {r["puma"]: r for r in read("puma_county_2020.csv")}
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows["00100"]["counties"], "Kauai;Maui")      # incl. Kalawao (Maui)
        self.assertEqual(rows["00100"]["nests_in_one_county"], "False")
        self.assertEqual(rows["00200"]["area"], "Hawaii")
        self.assertTrue(all(rows[p]["area"] == "Honolulu" for p in rows if p.startswith("003")))
        self.assertTrue(all(r["source_url"] == bp.REL_URL for r in rows.values()))

    def test_area_of(self):
        self.assertEqual(bp.area_of(["Maui", "Kauai"]), "Kauai + Maui")
        self.assertEqual(bp.area_of(["Honolulu"]), "Honolulu")


class Aggregation(unittest.TestCase):
    def setUp(self):
        names = {"3150": "Ilocano", "2910": "Tagalog, Filipino", "2920": "Tagalog, Filipino"}
        rows = [person(lanp="3150", eng="3", w=20, rep=22) for _ in range(12)]
        rows += [person(lanp="3150", eng="1", w=50)]                          # very well
        rows += [person(lanp="3150", eng="4", age="4", w=999)]                # under 5
        rows += [person(lanp="", eng="", w=999)]                              # English only
        rows += [person(puma="00200", lanp="2910", eng="2", w=30) for _ in range(3)]
        rows += [person(puma="00200", lanp="2920", eng="2", w=30) for _ in range(2)]
        self.agg = bp.aggregate(rows, names, {"00100": "Kauai + Maui", "00200": "Hawaii"})

    def test_weights_age_and_english_ability(self):
        a = self.agg[("Kauai + Maui", "Ilocano")]
        self.assertEqual(a["speakers"], 12 * 20 + 50)
        self.assertEqual(a["lep"], 240)
        self.assertEqual(a["n_lep"], 12)

    def test_groupings_and_state_rollup(self):
        self.assertEqual(self.agg[("Hawaii", "Tagalog, Filipino")]["lep"], 150)  # Filipino+Tagalog
        self.assertEqual(self.agg[("Hawaii State", "Ilocano")]["lep"], 240)

    def test_replicate_moe(self):
        a = self.agg[("Kauai + Maui", "Ilocano")]
        # every replicate = 12*22 = 264, est 240 -> SE = sqrt(4/80*80*24^2) = 48
        self.assertAlmostEqual(bp.moe90(a["lep"], a["lep_reps"]), 1.645 * 48)

    def test_suppression(self):
        rows = {r["language"]: r for r in bp.table(self.agg, "Hawaii", "Hawaii")}
        tf = rows["Tagalog, Filipino"]                       # 150 weighted but n = 5 < 10
        self.assertEqual(tf["speak_english_less_than_very_well"], "<100")
        self.assertEqual((tf["moe_90"], tf["share_of_area_lep"], tf["rank"]), ("", "", ""))
        self.assertTrue(tf["suppressed"])
        il = bp.table(self.agg, "Kauai + Maui", "Kauai;Maui")[0]
        self.assertEqual(il["speak_english_less_than_very_well"], 240)
        self.assertEqual(il["rank"], 1)
        self.assertTrue(bp.suppressed(99, 50))
        self.assertTrue(bp.suppressed(500, 9))
        self.assertFalse(bp.suppressed(100, 10))

    def test_dictionary_groupings(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "dict.csv"
            p.write_text('VAL,LANP,C,4,"2000","2000","Mandarin"\n'
                         'VAL,LANP,C,4,"3150","3150","Ilocano"\n'
                         'VAL,ENG,C,1,"1","1","Very well"\n', encoding="utf-8")
            self.assertEqual(bp.language_names(p), {"2000": "Chinese", "3150": "Ilocano"})


class CommittedOutputs(unittest.TestCase):
    def test_aggregates_only_and_suppressed_cells(self):
        for name in ("languages_by_county.csv", "pums_language_state_summary.csv"):
            rows = read(name)
            self.assertFalse(MICRODATA_COLUMNS & set(rows[0]), name)
            for r in rows:
                if r["suppressed"] == "True":
                    self.assertEqual(r["speak_english_less_than_very_well"], "<100")
                    self.assertEqual(r["moe_90"], "")
                else:
                    self.assertGreaterEqual(int(r["speak_english_less_than_very_well"]), 100)
                    self.assertTrue(r["moe_90"])
                if r["speakers_5plus"] != "<100":
                    self.assertGreaterEqual(int(r["speakers_5plus"]), 100)

    def test_areas_and_sources(self):
        rows = read("languages_by_county.csv")
        self.assertEqual({r["area"] for r in rows}, {"Kauai + Maui", "Honolulu", "Hawaii"})
        self.assertTrue(all(r["source_url"] == bp.PUMS_URL for r in rows))
        langs = mt.load_languages()
        self.assertEqual(langs["Kauai"], langs["Maui"])                        # shared PUMA
        self.assertNotIn("Other Asian and Pacific Island languages",
                         {l["language"] for ls in langs.values() for l in ls})


class Selection(unittest.TestCase):
    def langs(self, names):
        return [{"language": n, "area": "A", "speak_english_less_than_very_well": 1000 - i,
                 "moe_90": 1, "share_of_area_lep": 0.1, "rank": i + 1}
                for i, n in enumerate(names)]

    def test_top6_plus_always_include(self):
        ls = self.langs(["Ilocano", "Tagalog, Filipino", "Chinese", "Japanese", "Korean",
                         "Hawaiian", "Vietnamese", "Chuukese", "Samoan"])
        sel = [l["language"] for l in mt.select_languages(ls, COMM)]
        self.assertEqual(sel, ["Ilocano", "Tagalog, Filipino", "Chinese", "Japanese", "Korean",
                               "Hawaiian", "Chuukese"])     # Marshallese absent (suppressed)

    def test_real_selection(self):
        langs = mt.load_languages()
        hon = [l["language"] for l in mt.select_languages(langs["Honolulu"], COMM)]
        self.assertEqual(hon[:3], ["Ilocano", "Tagalog, Filipino", "Chinese"])
        for always in ("Hawaiian", "Chuukese", "Marshallese"):
            self.assertIn(always, hon)

    def test_library_prunes_only_header_only_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            lib = root / COMM["message_library"]["dir"]
            lib.mkdir(parents=True)
            header = ",".join(COMM["message_library"]["columns"]) + "\n"
            (lib / "old_header_only.csv").write_text(header, encoding="utf-8")
            (lib / "old_with_rows.csv").write_text(header + "m1,x,x,x,x,x,x,x,,,no\n",
                                                   encoding="utf-8")
            mt.ensure_message_library({"Maui": self.langs(["Ilocano"])}, COMM, root)
            self.assertFalse((lib / "old_header_only.csv").exists())
            self.assertTrue((lib / "old_with_rows.csv").exists())
            self.assertTrue((lib / "ilocano.csv").exists())

    def test_committed_library_matches_selection(self):
        langs = mt.load_languages()
        want = {"english.csv"} | {f"{mt.slug(l['language'])}.csv" for ls in langs.values()
                                  for l in mt.select_languages(ls, COMM)}
        have = {p.name for p in (ROOT / "data/sources/messages").glob("*.csv")}
        self.assertEqual(have, want)


if __name__ == "__main__":
    unittest.main()
