"""Fail-closed build inputs, the service worker VERSION and line endings.

Fast and offline: none of these tests needs data/raw/ (CI runs them on a fresh clone).
"""
import io
import json
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_access as ba  # noqa: E402
import build_app_data as bad  # noqa: E402
import build_islands  # noqa: E402
import build_map  # noqa: E402
import build_state_layers as bsl  # noqa: E402
import fetch_data  # noqa: E402
from raw_inputs import MissingInput, load_geojson, require_all_or_none  # noqa: E402

BUNDLE = json.loads((ROOT / "app" / "data" / "bundle.json").read_text(encoding="utf-8"))
COUNTIES4 = ("Honolulu", "Hawaii", "Maui", "Kauai")
SQUARE = {"type": "Polygon", "coordinates": [[[-157.9, 21.3], [-157.8, 21.3], [-157.8, 21.4],
                                               [-157.9, 21.4], [-157.9, 21.3]]]}


def quiet(fn, *a, **kw):
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        return fn(*a, **kw)


def fc(*features) -> str:
    return json.dumps({"type": "FeatureCollection", "features": list(features)})


class ServiceWorkerVersion(unittest.TestCase):
    def test_version_matches_app_files(self):
        """app/sw.js VERSION is the hash of the current app files. If this fails, run
        python3 scripts/build_app_data.py --copy-only and commit app/sw.js."""
        want = bad.cache_version(bad.precache_list())
        self.assertEqual(bad.sw_version(), want,
                         "app/sw.js VERSION is stale: run python3 scripts/build_app_data.py "
                         "--copy-only and commit app/sw.js")

    def test_precache_list_matches_sw(self):
        sw = (ROOT / "app" / "sw.js").read_text(encoding="utf-8")
        for rel in bad.precache_list():
            self.assertIn(json.dumps(rel), sw, rel)

    def test_write_sw_in_temp_app(self):
        with tempfile.TemporaryDirectory() as d:
            app, pb = Path(d) / "app", Path(d) / "playbooks"
            shutil.copytree(ROOT / "app", app, ignore=shutil.ignore_patterns("playbooks"))
            pb.mkdir()
            (pb / "x_tsunami.pdf").write_bytes(b"%PDF-1.4\r\n")
            (app / "styles.css").write_text("body { color: red; }\n", encoding="utf-8")
            precache, version = bad.write_sw(app, pb)
            self.assertIn("playbooks/x_tsunami.pdf", precache)
            self.assertEqual(bad.sw_version(app), version)
            self.assertEqual(version, bad.cache_version(precache, app, pb))
            self.assertNotEqual(version, bad.sw_version())          # styles.css changed


class LineEndings(unittest.TestCase):
    def make(self, d: Path, eol: bytes, pdf: bytes) -> tuple:
        app, pb = d / "app", d / "playbooks"
        (app / "data").mkdir(parents=True)
        pb.mkdir()
        for rel in bad.SHELL[1:]:
            text = b"line one\nline two\n" if not rel.endswith(".png") else b"\x89PNG\r\n\x1a\n"
            (app / rel).write_bytes(text.replace(b"\n", eol) if not rel.endswith(".png") else text)
        (app / "data" / "bundle.json").write_bytes(b'{"a": 1}\n'.replace(b"\n", eol))
        (pb / "a.pdf").write_bytes(pdf)
        return app, pb

    def test_crlf_and_lf_give_the_same_version(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            lf = self.make(Path(a), b"\n", b"%PDF\r\nx")
            crlf = self.make(Path(b), b"\r\n", b"%PDF\r\nx")
            v1 = bad.cache_version(bad.precache_list(*lf), *lf)
            v2 = bad.cache_version(bad.precache_list(*crlf), *crlf)
            self.assertEqual(v1, v2)

    def test_binary_files_are_not_normalised(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            x = self.make(Path(a), b"\n", b"%PDF\r\nx")
            y = self.make(Path(b), b"\n", b"%PDF\nx")
            self.assertNotEqual(bad.cache_version(bad.precache_list(*x), *x),
                                bad.cache_version(bad.precache_list(*y), *y))

    def test_gitattributes(self):
        text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("* text=auto eol=lf", text)
        for ext in ("*.pdf", "*.png", "*.ico"):
            self.assertRegex(text, rf"(?m)^{ext.replace('*', r'\*').replace('.', r'\.')}\s+binary")


class CommittedBundle(unittest.TestCase):
    """The committed bundle has every layer the full build requires."""

    def test_tsunami_zone_for_four_counties(self):
        for c in COUNTIES4:
            self.assertTrue(BUNDLE["tsunami_zone"].get(c), c)

    def test_sirens_for_four_counties(self):
        for c in COUNTIES4:
            self.assertTrue(BUNDLE["state"]["sirens"].get(c), c)
        self.assertEqual(BUNDLE["state"]["radius_ft"], 3400)

    def test_dam_zones_on_sites(self):
        state = bsl.load()
        dam_sites = [s for s in BUNDLE["sites"] if s.get("dam")]
        self.assertTrue(dam_sites)
        self.assertEqual(len(dam_sites), len(state["site_dam_zones"]))

    def test_every_area_has_island_and_siren_share(self):
        for t in BUNDLE["tracts"]:
            self.assertTrue(t["i"], t["f"])
            self.assertIn("sc", t, t["f"])

    def test_care_facilities_and_childcare(self):
        types = {f["t"] for f in BUNDLE["facilities"]}
        self.assertTrue({"childcare", "nursing_home", "dialysis", "hospital"} <= types)


class FailClosed(unittest.TestCase):
    def test_tsunami_overlay_missing_empty_or_partial(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "tsunami_zone.geojson"
            with self.assertRaises(MissingInput):
                bad.tsunami_overlay(p)                       # missing
            p.write_text("")
            with self.assertRaises(MissingInput):
                bad.tsunami_overlay(p)                       # empty file
            p.write_text(fc())
            with self.assertRaises(MissingInput):
                bad.tsunami_overlay(p)                       # no features
            p.write_text(fc({"type": "Feature", "properties": {"island": "OAHU"},
                             "geometry": SQUARE}))
            with self.assertRaises(MissingInput) as e:
                bad.tsunami_overlay(p)                       # Oʻahu only
            self.assertIn("Hawaii, Maui, Kauai", str(e.exception))

    def test_full_build_requires_summaries(self):
        with mock.patch.object(bad, "STATE", None), self.assertRaises(MissingInput):
            bad.require_summaries()
        with mock.patch.object(bad, "ACCESS", {"areas": {}, "facilities": []}), \
                self.assertRaises(MissingInput):
            bad.require_summaries()
        with mock.patch.object(bad, "ISLANDS", {}), self.assertRaises(MissingInput):
            bad.require_summaries()
        bad.require_summaries()                              # the committed ones pass

    def test_allow_missing_raw_only_with_copy_only(self):
        with self.assertRaises(SystemExit) as e:
            quiet(bad.main, ["--allow-missing-raw"])
        self.assertEqual(e.exception.code, 2)

    def test_full_build_stops_without_tsunami(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(bad, "load_inputs", return_value={}), \
                mock.patch.object(bad, "build",
                                  side_effect=lambda inp: bad.tsunami_overlay(Path(d) / "x")):
            self.assertEqual(quiet(bad.main, []), 1)

    def test_state_layers_partial_download_raises(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(bsl, "RAW", Path(d)):
            self.assertIsNone(bsl.summarize(offline=True))    # none: documented fallback
            (Path(d) / "sirens.geojson").write_text(fc())
            with self.assertRaises(MissingInput):
                bsl.summarize(offline=True)                  # partial set

    def test_state_layers_no_raw_and_no_summary_fails(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(bsl, "RAW", Path(d)), \
                mock.patch.object(bsl, "OUT", Path(d) / "none.json"):
            self.assertEqual(quiet(bsl.main, ["--offline"]), 1)

    def test_state_layers_empty_layer_raises(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(bsl, "RAW", Path(d)):
            for n in ("childcare.geojson", "sirens.geojson", "dams.geojson"):
                (Path(d) / n).write_text(fc())
            (Path(d) / "meta.json").write_text(json.dumps({"siren_radius": {"metres": 1036}}))
            with self.assertRaises(MissingInput):
                bsl.summarize(offline=True)

    def test_arcgis_partial_download_raises(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ba, "RAW", Path(d)):
            self.assertIsNone(ba.summarize(offline=True))
            (Path(d) / ba.REQUIRED[0]).write_text("{}")
            with self.assertRaises(MissingInput):
                ba.summarize(offline=True)

    def test_arcgis_no_raw_and_no_summary_fails(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(ba, "RAW", Path(d)), \
                mock.patch.object(ba, "OUT", Path(d) / "none.json"):
            self.assertEqual(quiet(ba.main, ["--offline"]), 1)

    def test_care_facilities_need_tsunami_layer(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(ba, "TSUNAMI", Path(d) / "tsunami_zone.geojson"):
            with self.assertRaises(MissingInput):
                ba.facilities(lambda x, y: "", offline=True)

    def test_islands_need_coastline(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(build_islands, "RAW", Path(d) / "coastline.geojson"):
            self.assertEqual(quiet(build_islands.main, ["--offline"]), 1)

    def test_map_needs_every_layer(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(build_map, "RAW", Path(d)):
            self.assertEqual(quiet(build_map.main), 1)

    def test_fetch_offline_needs_cached_layers(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(fetch_data, "RAW", Path(d)):
            with self.assertRaises(MissingInput):
                fetch_data.load_layers(["tsunami_zone"], offline=True)
            (Path(d) / "fema_open_shelters.geojson").write_text(fc())
            got = fetch_data.load_layers(["fema_open_shelters"], offline=True)
            self.assertEqual(got["fema_open_shelters"]["features"], [])   # may be empty

    def test_helpers(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(require_all_or_none(Path(d), ["a", "b"], "x"))
            (Path(d) / "a").write_text("{}")
            with self.assertRaises(MissingInput):
                require_all_or_none(Path(d), ["a", "b"], "x")
            (Path(d) / "g.json").write_text(json.dumps({"type": "x"}))
            with self.assertRaises(MissingInput):
                load_geojson(Path(d) / "g.json", "x")


if __name__ == "__main__":
    unittest.main()
