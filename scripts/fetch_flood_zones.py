#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – site-level FEMA flood zones.

Point-queries the official FEMA flood hazard areas (DFIRM / NFHL, as republished by
Hawaii Statewide GIS) for every located site in data/processed/shelters_2026.geojson
and data/processed/candidates.geojson, and caches the answers in
data/sources/site_flood_zones.csv. Build scripts read only this cache; they never
call the network.

Special Flood Hazard Area (SFHA) = FEMA zone starting with A or V (1% annual chance).

Usage:  python3 scripts/fetch_flood_zones.py          (only queries points not cached)
        python3 scripts/fetch_flood_zones.py --refresh
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hawaii_time import now_hst  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "sources" / "site_flood_zones.csv"
PROC = ROOT / "data" / "processed"

# Hawaii Statewide GIS "State DFIRM": FEMA flood hazard areas for the State of Hawaii,
# downloaded from the FEMA Map Service Center 6/15/26.
LAYER_URL = "https://geodata.hawaii.gov/arcgis/rest/services/Hazards/MapServer/6"
FIELDS = ["site_key", "lon", "lat", "fld_zone", "in_sfha", "source_url", "queried_at"]
NOT_A_ZONE = {"AREA NOT INCLUDED"}       # starts with "A" but is not a flood zone


def is_sfha(zone: str | None) -> bool | None:
    """True for A* / V* zones, False for other zones, None when there is no zone."""
    z = (zone or "").strip().upper()
    if not z:
        return None
    return z not in NOT_A_ZONE and z.startswith(("A", "V"))


def pick_zone(zones: list) -> str:
    """A point on a polygon edge can hit several zones: report the most hazardous."""
    zones = [z.strip() for z in zones if z and z.strip()]
    for prefix in ("V", "A"):
        for z in sorted(zones):
            if z.upper().startswith(prefix) and is_sfha(z):
                return z
    return sorted(zones)[0] if zones else ""


def point_url(lon: float, lat: float) -> str:
    params = {
        "geometry": f"{lon:.6f},{lat:.6f}",
        "geometryType": "esriGeometryPoint",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "fld_zone,zone_subty,sfha_tf,dfirm_id",
        "returnGeometry": "false",
        "f": "json",
    }
    return f"{LAYER_URL}/query?{urllib.parse.urlencode(params)}"


def query_point(lon: float, lat: float, fetch=None, retries: int = 3,
                pause: float = 2.0) -> tuple[str, str]:
    """Return (fld_zone, url). ArcGIS can answer HTTP 200 with an error body: retry it."""
    if fetch is None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from fetch_data import fetch_json as fetch  # lazy: fetch_data imports this module
    url = point_url(lon, lat)
    last = None
    for attempt in range(retries):
        data = fetch(url)
        if "error" not in data:
            return pick_zone([(f.get("attributes") or {}).get("fld_zone")
                              for f in data.get("features", [])]), url
        last = data["error"]
        time.sleep(pause * (attempt + 1))
    raise RuntimeError(f"Flood query failed after {retries} tries: {url}\n{last}")


def key(lon, lat) -> tuple:
    return round(float(lon), 6), round(float(lat), 6)


def load_cache(path: Path = CACHE) -> dict:
    """(lon, lat) rounded to 6 decimals -> {"fld_zone": str|None, "in_sfha": bool|None}."""
    if not path.exists():
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            sf = {"True": True, "False": False}.get(r.get("in_sfha", ""))
            out[key(r["lon"], r["lat"])] = {"fld_zone": r.get("fld_zone") or None,
                                            "in_sfha": sf}
    return out


def lookup(cache: dict, lon: float, lat: float) -> dict:
    """Flood fields for a point; None values when the point was never queried."""
    return cache.get(key(lon, lat), {"fld_zone": None, "in_sfha": None})


def sites(proc: Path = PROC) -> list:
    """(site_key, lon, lat) for every located site, de-duplicated by position."""
    out, seen = [], set()
    for fname, prefix, label in (("shelters_2026.geojson", "shelter", "name"),
                                 ("candidates.geojson", "candidate", "name")):
        p = proc / fname
        if not p.exists():
            continue
        for f in json.loads(p.read_text(encoding="utf-8"))["features"]:
            g = f.get("geometry") or {}
            if g.get("type") != "Point":
                continue
            lon, lat = g["coordinates"][:2]
            pr = f["properties"]
            k = key(lon, lat)
            if k in seen:
                continue
            seen.add(k)
            out.append((f"{prefix}:{pr.get('county', '')}:{pr.get(label, '')}", k[0], k[1]))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Cache FEMA flood zones for site points")
    ap.add_argument("--refresh", action="store_true", help="re-query cached points")
    ap.add_argument("--pause", type=float, default=1.0, help="seconds between requests")
    args = ap.parse_args(argv)

    cache = {} if args.refresh else load_cache()
    todo = [s for s in sites() if key(s[1], s[2]) not in cache]
    print(f"{len(todo)} sites to query ({len(cache)} cached) against {LAYER_URL}")
    mode = "w" if args.refresh or not CACHE.exists() else "a"
    with open(CACHE, mode, newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if mode == "w":
            w.writeheader()
        for i, (site_key, lon, lat) in enumerate(todo, 1):
            zone, url = query_point(lon, lat)
            sf = is_sfha(zone)
            w.writerow({"site_key": site_key, "lon": f"{lon:.6f}", "lat": f"{lat:.6f}",
                        "fld_zone": zone, "in_sfha": "" if sf is None else sf,
                        "source_url": url,
                        "queried_at": now_hst()})
            fh.flush()
            if i % 25 == 0:
                print(f"  {i}/{len(todo)}")
            time.sleep(args.pause)
    print(f"Done -> {CACHE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
