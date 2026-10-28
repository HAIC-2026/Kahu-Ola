"""Build and "data as of" dates use Hawaiʻi time (Pacific/Honolulu, UTC-10), not UTC."""
import json
import re
import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from hawaii_time import hst_date, now_hst  # noqa: E402

PROC = ROOT / "data" / "processed"


def load(p):
    return json.loads(p.read_text(encoding="utf-8"))


class Helpers(unittest.TestCase):
    def test_now_is_utc_minus_10(self):
        self.assertTrue(now_hst().endswith("-10:00"), now_hst())
        self.assertEqual(datetime.fromisoformat(now_hst()).utcoffset().total_seconds(), -36000)

    def test_hst_date(self):
        self.assertEqual(hst_date("2026-10-28T07:26:28+00:00"), "2026-10-27")   # 9:26 pm HST
        self.assertEqual(hst_date("2026-10-28T07:26:28Z"), "2026-10-27")
        self.assertEqual(hst_date("2026-10-28T07:26:28"), "2026-10-27")        # naive = UTC
        self.assertEqual(hst_date("2026-10-28T10:00:00+00:00"), "2026-10-28")   # midnight HST
        self.assertEqual(hst_date("2026-10-27T21:00:00-10:00"), "2026-10-27")
        self.assertEqual(hst_date(""), "")


class Outputs(unittest.TestCase):
    def test_build_timestamps_are_hst(self):
        stamps = {
            "afn_tracts": load(PROC / "afn_tracts.geojson")["metadata"]["built_at"],
            "needs": load(PROC / "needs_by_scenario.json")["built_at"],
            "shelters": load(PROC / "shelters_2026.geojson")["metadata"]["built_at"],
        }
        for name, s in stamps.items():
            self.assertTrue(s.endswith("-10:00"), (name, s))

    def test_data_as_of_everywhere_is_the_hst_build_date(self):
        want = hst_date(load(PROC / "needs_by_scenario.json")["built_at"])
        version = load(ROOT / "app" / "data" / "version.json")
        bundle = load(ROOT / "app" / "data" / "bundle.json")
        self.assertEqual(version["data_as_of"], want)
        self.assertEqual(bundle["meta"]["data_as_of"], want)
        for path in (ROOT / "playbooks").glob("*.html"):
            dates = set(re.findall(r"Data as of (\d{4}-\d{2}-\d{2})", path.read_text(encoding="utf-8")))
            self.assertEqual(dates, {want}, path.name)

    def test_plan_has_no_utc_timestamps(self):
        text = (ROOT / "PLAN.md").read_text(encoding="utf-8")
        self.assertNotRegex(text, r"\d{2}:\d{2}(:\d{2})?(Z|\+00:00)")
        self.assertNotIn(" UTC", text)


if __name__ == "__main__":
    unittest.main()
