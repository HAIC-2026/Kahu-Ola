#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – which island each Census area and each site is on.

Point-in-polygon against the island outlines of the Hawaiʻi Statewide GIS "Coastline"
layer (Terrestrial/MapServer/3, from USGS Digital Line Graphs), downloaded at build time
like the other State layers and cached in data/raw/coastline.geojson.
  * Census area: its representative point on land – the interior grid point
    (scripts/geo.py sample_points) nearest the area's center that lies inside an island
    outline. Census areas include water (Pearl Harbor, Kāneʻohe Bay), so a center point
    can fall in the sea.
  * Site: its located point.
Kalawao / Kalaupapa falls on Molokaʻi by geometry. The Northwestern Hawaiian Islands are
not in the main-island coastline layer; the one Census area there (west of 160.6°W, no
2020 population) is assigned "Northwestern Hawaiian Islands" and logged.
The build fails if any Census area or located site gets no island.

Usage:  python3 scripts/build_islands.py            (download coastline, assign)
        python3 scripts/build_islands.py --offline  (use data/raw cache)
Output: data/sources/islands.csv (read by build_app_data.py)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import fetch_json, query_url  # noqa: E402
from geo import ZoneIndex, area_centroid, point_in_geometry, sample_points  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "coastline.geojson"
AFN = ROOT / "data" / "processed" / "afn_tracts.geojson"
SHELTERS = ROOT / "data" / "processed" / "shelters_2026.geojson"
OUT = ROOT / "data" / "sources" / "islands.csv"
LAYER = "https://geodata.hawaii.gov/arcgis/rest/services/Terrestrial/MapServer/3"
ISLE = {"niihau": "Niʻihau", "kauai": "Kauaʻi", "oahu": "Oʻahu", "molokai": "Molokaʻi",
        "lanai": "Lānaʻi", "maui": "Maui", "kahoolawe": "Kahoʻolawe", "hawaii": "Hawaiʻi"}
NWHI = "Northwestern Hawaiian Islands"
NWHI_WEST_OF = -160.6
FIELDS = ["kind", "id", "county", "name", "lon", "lat", "island", "method", "source_url"]


def download() -> dict:
    fc = fetch_json(query_url(LAYER, "1=1", 0))
    if "features" not in fc:
        raise RuntimeError(f"coastline layer: unexpected response {str(fc)[:200]}")
    fc["metadata"] = {"source_url": f"{LAYER}/query"}
    return fc


def island_of(index: ZoneIndex, x: float, y: float) -> str:
    hit = index.find(x, y)
    return ISLE[str(hit["properties"]["isle"]).lower()] if hit else ""


def land_point(geom: dict, index: ZoneIndex, n: int = 400):
    """Interior point on land nearest the area's center, or None. The center itself when
    it is inside the area and on land (most areas); otherwise the nearest grid point."""
    cx, cy = area_centroid(geom)
    if point_in_geometry(cx, cy, geom) and index.find(cx, cy):
        return cx, cy
    pts = [p for p in sample_points(geom, n) if index.find(*p)]
    if not pts:
        return None
    return min(pts, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)


def assign(afn: dict, shelters: dict, coast: dict) -> tuple:
    index = ZoneIndex(coast)
    rows, missing = [], []
    for f in afn["features"]:
        p = f["properties"]
        pt = land_point(f["geometry"], index)
        if pt:
            island, method = island_of(index, *pt), "representative point on land"
        else:
            cx, cy = area_centroid(f["geometry"])
            pt = (cx, cy)
            island, method = ((NWHI, "west of 160.6°W: not in the main-island coastline layer")
                              if cx < NWHI_WEST_OF else ("", "no land point"))
        if not island:
            missing.append(f"area {p['tract_fips']}")
        rows.append({"kind": "area", "id": p["tract_fips"], "county": p["county"], "name": "",
                     "lon": round(pt[0], 5), "lat": round(pt[1], 5), "island": island,
                     "method": method, "source_url": f"{LAYER}/query"})
    for f in shelters["features"]:
        p, g = f["properties"], f.get("geometry")
        if not g:
            continue                                   # not located: not on the map
        x, y = g["coordinates"][:2]
        island = island_of(index, x, y)
        if not island:
            missing.append(f"site {p['name']}")
        rows.append({"kind": "site", "id": f"{p['name']}|{p['county']}", "county": p["county"],
                     "name": p["name"], "lon": round(x, 5), "lat": round(y, 5), "island": island,
                     "method": "site point", "source_url": f"{LAYER}/query"})
    return rows, missing


def load(path: Path = OUT) -> dict:
    """{('area', fips) or ('site', 'name|county'): island}."""
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {(r["kind"], r["id"]): r["island"] for r in csv.DictReader(fh)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Assign Census areas and sites to islands")
    ap.add_argument("--offline", action="store_true", help="use the cached coastline layer")
    if not ap.parse_args(argv).offline:
        RAW.parent.mkdir(parents=True, exist_ok=True)
        RAW.write_text(json.dumps(download()), encoding="utf-8")
    coast = json.loads(RAW.read_text(encoding="utf-8"))
    rows, missing = assign(json.loads(AFN.read_text(encoding="utf-8")),
                           json.loads(SHELTERS.read_text(encoding="utf-8")), coast)
    for r in rows:
        if r["island"] == NWHI:
            print(f"  note: area {r['id']} -> {NWHI} ({r['method']})")
    if missing:
        print("No island for:", *missing, sep="\n  ", file=sys.stderr)
        return 1
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    counts = {}
    for r in rows:
        counts[(r["kind"], r["island"])] = counts.get((r["kind"], r["island"]), 0) + 1
    print(f"Wrote {OUT.relative_to(ROOT)}: " + ", ".join(
        f"{k} {i} {n}" for (k, i), n in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
