#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – population-weighted in-zone shares from 2020 Census blocks.

Share of a Census area's people inside a zone (or within range of something) =
    sum of 2020 block population (PL 94-171 P1_001N) whose block internal point is inside
    / sum of 2020 block population of the area.
Blocks with 0 people are ignored. The share is then applied to the area's population, as
before. Block internal points come from TIGERweb (2020 Census Blocks layer, fetched at build
time and cached in data/raw/blocks/, gitignored); if that cache is missing, the identical
internal points in the 2020 PL 94-171 geographic header are used (both are the Census
Bureau's MAF/TIGER internal points). If neither is available, callers fall back to the old
area method (share of about 100 grid points) and every figure is labelled "share of the
area" instead of "of people".

Usage:  python3 scripts/block_shares.py     (fetch TIGERweb block internal points)
"""
from __future__ import annotations

import io
import json
import sys
import urllib.parse
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_tract_labels import BLOCKS, PL_URL, GEO_SUMLEV, GEO_GEOCODE, GEO_LOGRECNO, read_blocks  # noqa: E402
from fetch_data import fetch_json  # noqa: E402
from hawaii_time import now_hst  # noqa: E402

TIGERWEB = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
            "tigerWMS_Census2020/MapServer/10")
CACHE = BLOCKS / "tigerweb_block_points.json"
GEO_INTPTLAT, GEO_INTPTLON = 92, 93      # 2020 PL geographic header, 0-based
PAGE = 5000
METHOD = {
    "population": "share of the area's 2020 Census block population whose block internal "
                  "point is inside (blocks with no people ignored)",
    "area": "share of the area (about 100 grid points spread over it); not weighted by "
            "where people live",
}
WORD = {"population": "of people", "area": "of the area"}


def fetch_points() -> int:
    """All Hawaiʻi blocks with people from TIGERweb: GEOID, internal point, POP100."""
    out, offset = {}, 0
    while True:
        q = urllib.parse.urlencode({"where": "STATE='15' AND POP100>0",
                                    "outFields": "GEOID,INTPTLAT,INTPTLON,POP100",
                                    "returnGeometry": "false", "f": "json",
                                    "resultOffset": offset, "resultRecordCount": PAGE,
                                    "orderByFields": "GEOID"})
        page = fetch_json(f"{TIGERWEB}/query?{q}")
        if "error" in page:
            raise RuntimeError(page["error"])
        feats = page.get("features", [])
        for f in feats:
            a = f["attributes"]
            out[a["GEOID"]] = [float(a["INTPTLON"]), float(a["INTPTLAT"]), int(a["POP100"] or 0)]
        if len(feats) < PAGE and not page.get("exceededTransferLimit"):
            break
        offset += len(feats)
    BLOCKS.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"source": TIGERWEB, "fetched_at": now_hst(), "blocks": out}),
                     encoding="utf-8")
    return len(out)


def pl_points() -> dict:
    """GEOID -> (lon, lat) from the 2020 PL geographic header (summary level 750)."""
    path = BLOCKS / PL_URL.rsplit("/", 1)[1]
    if not path.exists():
        return {}
    out = {}
    with zipfile.ZipFile(path) as z:
        for line in io.TextIOWrapper(z.open("higeo2020.pl"), encoding="latin-1"):
            f = line.split("|")
            if f[GEO_SUMLEV] == "750":
                out[f[GEO_GEOCODE]] = (float(f[GEO_INTPTLON]), float(f[GEO_INTPTLAT]))
    return out


def load() -> dict | None:
    """{"method", "source", "blocks": {tract: [(lon, lat, pop), ...]}, "tract_pop": {tract: pop}}
    with 2020 block population (P1_001N) and internal points; None when blocks are missing."""
    try:
        pops = read_blocks()["pop"]
    except (FileNotFoundError, KeyError):
        return None
    source, pts = None, {}
    if CACHE.exists():
        c = json.loads(CACHE.read_text(encoding="utf-8"))
        pts = {g: (v[0], v[1]) for g, v in c["blocks"].items()}
        source = f"TIGERweb 2020 Census Blocks internal points (fetched {c['fetched_at'][:10]})"
    if not pts:
        pts = pl_points()
        source = "2020 PL 94-171 geographic header block internal points (MAF/TIGER)"
    if not pts:
        return None
    blocks, tract_pop, missing = {}, {}, 0
    for g, pop in pops.items():
        if pop <= 0:
            continue
        if g not in pts:
            missing += pop
            continue
        blocks.setdefault(g[:11], []).append((*pts[g], pop))
        tract_pop[g[:11]] = tract_pop.get(g[:11], 0) + pop
    return {"method": "population", "source": source, "blocks": blocks, "tract_pop": tract_pop,
            "missing_pop": missing}


def share(blocks: dict | None, tract: str, inside) -> float | None:
    """Population-weighted share for one tract; inside(lon, lat) -> bool. None when the
    tract has no populated blocks (callers then use the area method for that tract)."""
    if not blocks:
        return None
    rows = blocks["blocks"].get(tract)
    if not rows:
        return None
    total = sum(p for _x, _y, p in rows)
    return sum(p for x, y, p in rows if inside(x, y)) / total if total else None


if __name__ == "__main__":
    print(f"{fetch_points()} populated blocks -> {CACHE.relative_to(BLOCKS.parent.parent.parent)}")
