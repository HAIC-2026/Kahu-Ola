"""Offline tests: python3 -m unittest discover tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_data as fd  # noqa: E402
import geo  # noqa: E402

SQUARE = [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]
WITH_HOLE = SQUARE + [[[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]]


def pt(lon, lat, **props):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": props}


def fc(features, label="test"):
    return {"type": "FeatureCollection", "features": features,
            "metadata": {"source": label, "source_url": "https://example", "fetched_at": "x"}}


class Geometry(unittest.TestCase):
    def test_inside_outside(self):
        self.assertTrue(geo.point_in_polygon(5, 1, SQUARE))
        self.assertFalse(geo.point_in_polygon(11, 5, SQUARE))

    def test_hole(self):
        self.assertFalse(geo.point_in_polygon(5, 5, WITH_HOLE))
        self.assertTrue(geo.point_in_polygon(2, 2, WITH_HOLE))

    def test_multipolygon(self):
        g = {"type": "MultiPolygon", "coordinates": [SQUARE,
             [[[20, 20], [30, 20], [30, 30], [20, 20]]]]}
        self.assertTrue(geo.point_in_geometry(25, 22, g))
        self.assertFalse(geo.point_in_geometry(15, 15, g))

    def test_share_inside(self):
        left_half = fc([{"type": "Feature", "properties": {}, "geometry": {
            "type": "Polygon", "coordinates": [[[0, 0], [5, 0], [5, 10], [0, 10], [0, 0]]]}}])
        share = geo.ZoneIndex(left_half).share_inside(
            {"type": "Polygon", "coordinates": SQUARE}, 100)
        self.assertAlmostEqual(share, 0.5, delta=0.05)

    def test_representative_point_inside(self):
        g = {"type": "Polygon", "coordinates": WITH_HOLE}
        self.assertTrue(geo.point_in_geometry(*geo.representative_point(g), g))


class County(unittest.TestCase):
    def test_islands(self):
        self.assertEqual(fd.county_of(-159.5, 22.0), "Kauai")
        self.assertEqual(fd.county_of(-157.86, 21.31), "Honolulu")
        self.assertEqual(fd.county_of(-156.50, 20.89), "Maui")
        self.assertEqual(fd.county_of(-157.0, 21.1), "Maui")
        self.assertEqual(fd.county_of(-155.08, 19.72), "Hawaii")

    def test_fips(self):
        self.assertEqual(fd.county_from_fips("15009031400"), "Maui")
        self.assertEqual(fd.county_from_fips("15005031900"), "Maui")  # Kalawao
        self.assertEqual(fd.county_from_fips("15001021000"), "Hawaii")
        self.assertEqual(fd.county_from_fips("06001000100"), "")


class Shelters(unittest.TestCase):
    def test_candidates(self):
        zone = fc([{"type": "Feature", "properties": {},
                    "geometry": {"type": "Polygon",
                                 "coordinates": [[[-156.7, 20.85], [-156.6, 20.85],
                                                  [-156.6, 20.95], [-156.7, 20.95],
                                                  [-156.7, 20.85]]]}}])
        layers = {
            "schools": fc([
                pt(-156.65, 20.90, sch_name="Coastal School", address="1 Beach Rd",
                   city="Lahaina", zip="96761"),
                pt(-156.50, 20.89, sch_name="Upland School"),
                pt(-155.08, 19.72, sch_name=""),
            ], "schools"),
            "tsunami_zone": zone,
            "tsunami_extreme": None,
            "fema_open_shelters": fc([], "fema"),
        }
        out = fd.build_candidates(layers)
        props = {f["properties"]["name"]: f["properties"] for f in out["features"]}
        self.assertEqual(len(out["features"]), 3)
        self.assertTrue(props["Coastal School"]["hazard_excluded"])
        self.assertFalse(props["Upland School"]["hazard_excluded"])
        self.assertEqual(props["Coastal School"]["address"], "1 Beach Rd, Lahaina, 96761")
        self.assertTrue(props["(unnamed)"]["needs_review"])
        self.assertEqual(props["(unnamed)"]["county"], "Hawaii")
        for p in props.values():
            self.assertIn("Not an official shelter", p["disclaimer"])
            self.assertTrue(p["source_url"])

    def test_query_url_pagination_and_bbox(self):
        u = fd.query_url("https://h/x", "ST_ABBR='HI'", 2000, (-160, 18, -154, 22))
        self.assertIn("resultOffset=2000", u)
        self.assertIn("outSR=4326", u)
        self.assertIn("esriGeometryEnvelope", u)


if __name__ == "__main__":
    unittest.main()
