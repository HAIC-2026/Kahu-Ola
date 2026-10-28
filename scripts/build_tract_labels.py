#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – readable tract labels ("Tract 308 · Kihei").

Each census tract gets a community name from a spatial join of its representative
point (an interior point, scripts/geo.py) to the 2020 Census Designated Place (CDP)
polygons from Census TIGERweb (tigerWMS_Census2020, layer 28):
  * point inside a CDP            -> community = CDP name             (method "inside")
  * else nearest CDP within 5 km  -> community = "near <CDP>"         (method "near")
  * else                          -> community = "rural <island>"     (method "rural")
The island comes from data/sources/communities_by_island.csv (DBEDT Data Book 01.12
assignment of each CDP). For "rural" tracts it is the island of the nearest CDP in the
same county, except three places with no CDP at all: Niʻihau (Kauaʻi County, west of
160°W), Kahoʻolawe (Maui County, tract 9800) and the Northwestern Hawaiian Islands
(Honolulu County, west of 160.6°W).

Tract number = last 6 digits of the tract code: 030800 -> 308, 030903 -> 309.03.

Usage:  python3 scripts/build_tract_labels.py            (download CDPs, build)
        python3 scripts/build_tract_labels.py --offline  (use data/raw cache)
Input:  data/processed/afn_tracts.geojson (build_map.py), communities_by_island.csv
Output: data/sources/tract_communities.csv (committed; read by model_needs.py,
        build_app_data.py and the playbooks)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geo import bbox_of, point_in_geometry, representative_point  # noqa: E402
from fetch_data import fetch_json, query_url  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "tiger_cdp_2020.geojson"
AFN = ROOT / "data" / "processed" / "afn_tracts.geojson"
COMMUNITIES = ROOT / "data" / "sources" / "communities_by_island.csv"
OUT = ROOT / "data" / "sources" / "tract_communities.csv"

CDP_LAYER = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
             "tigerWMS_Census2020/MapServer/28")
CDP_WHERE = "STATE='15'"
NEAR_KM = 5.0
NIIHAU_WEST_OF = -160.0
NWHI_WEST_OF = -160.6                              # same cut as svgmap.MAIN_ISLANDS_WEST
KAHOOLAWE_BBOX = (-156.70, 20.49, -156.52, 20.61)  # lon0, lat0, lon1, lat1
FIELDS = ["tract_fips", "county", "tract_number", "community", "island", "tract_label",
          "method", "cdp_geoid", "cdp_name", "distance_km", "point_lon", "point_lat",
          "source", "source_url"]


def tract_number(fips: str) -> str:
    """'15009030800' -> '308'; '15009030903' -> '309.03'."""
    code = str(fips)[-6:]
    base, suffix = int(code[:4]), code[4:]
    return str(base) if suffix == "00" else f"{base}.{suffix}"


def tract_label(fips: str, community: str) -> str:
    return f"Tract {tract_number(fips)} · {community}"


def download_cdps() -> dict:
    features, offset = [], 0
    while True:
        page = fetch_json(query_url(CDP_LAYER, CDP_WHERE, offset))
        if "error" in page:
            raise RuntimeError(f"TIGERweb error: {page['error']}")
        batch = page.get("features", [])
        features += batch
        if len(batch) == 0 or not page.get("properties", {}).get("exceededTransferLimit") \
                and not page.get("exceededTransferLimit"):
            break
        offset += len(batch)
    return {"type": "FeatureCollection", "features": features,
            "metadata": {"source_url": f"{CDP_LAYER}/query", "where": CDP_WHERE}}


def cdp_islands(path: Path = COMMUNITIES) -> dict:
    """CDP GEOID (7 digits) -> (island label, county) from communities_by_island.csv."""
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["row_type"] == "place":
                out[r["geoid"][-7:]] = (r["island"], r["county"])
    return out


def km_xy(lon: float, lat: float, lat0: float) -> tuple:
    return (lon * 111.320 * math.cos(math.radians(lat0)), lat * 110.574)


def dist_to_segment(p, a, b) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def rings(geom: dict):
    if geom["type"] == "Polygon":
        yield from geom["coordinates"]
    elif geom["type"] == "MultiPolygon":
        for poly in geom["coordinates"]:
            yield from poly


def distance_km(lon: float, lat: float, geom: dict) -> float:
    """Distance from a point to a polygon boundary (0 if inside), local flat projection."""
    if point_in_geometry(lon, lat, geom):
        return 0.0
    p = km_xy(lon, lat, lat)
    best = math.inf
    for ring in rings(geom):
        pts = [km_xy(x, y, lat) for x, y, *_ in ring]
        for a, b in zip(pts, pts[1:]):
            best = min(best, dist_to_segment(p, a, b))
    return best


def build(afn: dict, cdps: dict, islands: dict) -> list:
    places = []
    for f in cdps["features"]:
        p, g = f["properties"], f["geometry"]
        if g:
            places.append((p["GEOID"], p["BASENAME"], g, bbox_of(g)))
    rows = []
    for f in afn["features"]:
        fips, county = f["properties"]["tract_fips"], f["properties"]["county"]
        lon, lat = representative_point(f["geometry"])
        pad_lon, pad_lat = NEAR_KM / (111.32 * math.cos(math.radians(lat))), NEAR_KM / 110.574
        near = []
        for geoid, name, g, (x0, y0, x1, y1) in places:
            if x0 - pad_lon <= lon <= x1 + pad_lon and y0 - pad_lat <= lat <= y1 + pad_lat:
                near.append((distance_km(lon, lat, g), name, geoid))
        near.sort()
        if near and near[0][0] == 0.0:
            d, name, geoid = near[0]
            method, community = "inside", name
        elif near and near[0][0] <= NEAR_KM:
            d, name, geoid = near[0]
            method, community = "near", f"near {name}"
        else:
            method, d = "rural", None
            same = [(math.hypot(lon - (b[0] + b[2]) / 2, lat - (b[1] + b[3]) / 2), n_, gid)
                    for gid, n_, _g, b in places if islands.get(gid, ("", ""))[1] == county]
            _, name, geoid = min(same)
        island = islands[geoid][0]
        if method == "rural":
            island = remote_island(county, lon, lat) or island
            community, name, geoid = f"rural {island}", "", ""
        rows.append({
            "tract_fips": fips, "county": county, "tract_number": tract_number(fips),
            "community": community, "island": island,
            "tract_label": tract_label(fips, community), "method": method,
            "cdp_geoid": geoid, "cdp_name": name if method != "rural" else "",
            "distance_km": "" if d is None else round(d, 2),
            "point_lon": round(lon, 5), "point_lat": round(lat, 5),
            "source": "Census TIGERweb 2020 Census Designated Places (layer 28); "
                      "island from DBEDT Data Book 2025 table 01.12",
            "source_url": f"{CDP_LAYER}/query?where=STATE%3D%2715%27",
        })
    return rows


def remote_island(county: str, lon: float, lat: float) -> str:
    """Island name for points on islands without any CDP, else ''."""
    x0, y0, x1, y1 = KAHOOLAWE_BBOX
    if county == "Honolulu" and lon < NWHI_WEST_OF:
        return "Northwestern Hawaiian Islands"
    if county == "Kauai" and lon < NIIHAU_WEST_OF:
        return "Niʻihau"
    if county == "Maui" and x0 <= lon <= x1 and y0 <= lat <= y1:
        return "Kahoʻolawe"
    return ""


def load_labels(path: Path = OUT) -> dict:
    """tract_fips -> row (community, island, tract_label, ...). Empty if not built."""
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["tract_fips"]: r for r in csv.DictReader(fh)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Readable tract labels with community names")
    ap.add_argument("--offline", action="store_true", help="use cached CDP polygons")
    args = ap.parse_args(argv)
    if not args.offline:
        RAW.parent.mkdir(parents=True, exist_ok=True)
        RAW.write_text(json.dumps(download_cdps()), encoding="utf-8")
    cdps = json.loads(RAW.read_text(encoding="utf-8"))
    afn = json.loads(AFN.read_text(encoding="utf-8"))
    rows = build(afn, cdps, cdp_islands())
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    counts = {m: sum(r["method"] == m for r in rows) for m in ("inside", "near", "rural")}
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(rows)} tracts, {len(cdps['features'])} CDPs; "
          f"inside {counts['inside']}, near {counts['near']}, rural {counts['rural']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
