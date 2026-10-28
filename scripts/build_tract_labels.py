#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – readable tract labels ("Tract 308 · Kihei").

Each census tract gets a community name weighted by where its people live, from two
official Census files (no geometry):
  * 2020 Census Block Assignment File, incorporated place / CDP (block -> CDP)
  * 2020 PL 94-171 redistricting file, block-level total population (P1_001N)
For each tract (block GEOID characters 1-11) the population is split by CDP; blocks in
no CDP count as "outside CDPs". Rule (thresholds tested at their edges):
  * outside CDPs > 50% of the people -> "rural near <largest CDP>"  (method "pop_rural")
  * people, but no block in any CDP  -> "near <nearest CDP>" by geography, i.e. the CDP
    the area method below finds (overlapping, or within 5 km)     (method "pop_near");
    "rural <island>" only if no CDP is within 5 km                (method "pop_rural")
  * else the CDP with the most people; add the second CDP as "A / B" when it has
    >= 25% of the tract's people                                  (method "pop", "pop_2")
Tracts with 0 people in 2020 fall back to the area method: the share of the tract's
area inside each 2020 CDP polygon from Census TIGERweb (tigerWMS_Census2020, layer 28),
estimated from a grid of points (scripts/geo.py sample_points):
  * one CDP covers >= 20%          -> that CDP                    (method "area")
  * two or more CDPs cover >= 20%  -> "A / B", largest first      (method "area_2")
  * else the CDP overlapping most, or the nearest CDP within 5 km -> "near <CDP>"
  * else                           -> "rural <island>"            (method "area_rural")
The island comes from data/sources/communities_by_island.csv (DBEDT Data Book 01.12
assignment of each CDP). For "rural" tracts it is the island of the nearest CDP in the
same county, except three places with no CDP at all: Niʻihau (Kauaʻi County, west of
160°W), Kahoʻolawe (Maui County, tract 9800) and the Northwestern Hawaiian Islands
(Honolulu County, west of 160.6°W).

Readers see the community first and the Census ID second: "Waikapū / Waiheʻe-Waiehu"
with "Census area 308" (tract number = last 6 digits of the code: 030800 -> 308,
030903 -> 309.03). Place names use Hawaiian spellings from build_place_names.py
(USGS GNIS); IDs stay ASCII.

Usage:  python3 scripts/build_tract_labels.py            (download, build)
        python3 scripts/build_tract_labels.py --offline  (use data/raw cache)
Input:  data/processed/afn_tracts.geojson (build_map.py), communities_by_island.csv
Output: data/sources/tract_communities.csv (committed; read by model_needs.py,
        build_app_data.py and the playbooks)
        data/sources/tract_cdp_population_2020.csv (tract x CDP 2020 population)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geo import bbox_of, point_in_geometry, representative_point, sample_points  # noqa: E402
from fetch_data import USER_AGENT, fetch_json, query_url  # noqa: E402
from build_place_names import load_display_names  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "tiger_cdp_2020.geojson"
AFN = ROOT / "data" / "processed" / "afn_tracts.geojson"
COMMUNITIES = ROOT / "data" / "sources" / "communities_by_island.csv"
OUT = ROOT / "data" / "sources" / "tract_communities.csv"
OUT_POP = ROOT / "data" / "sources" / "tract_cdp_population_2020.csv"
BLOCKS = ROOT / "data" / "raw" / "blocks"

BAF_URL = "https://www2.census.gov/geo/docs/maps-data/data/baf2020/BlockAssign_ST15_HI.zip"
BAF_MEMBER = "BlockAssign_ST15_HI_INCPLACE_CDP.txt"
PL_URL = ("https://www2.census.gov/programs-surveys/decennial/2020/data/"
          "01-Redistricting_File--PL_94-171/Hawaii/hi2020.pl.zip")
# 2020 PL geographic header (higeo2020.pl), pipe-delimited, 0-based field positions
GEO_SUMLEV, GEO_LOGRECNO, GEO_GEOCODE, GEO_PLACE, GEO_BASENAME, GEO_POP100 = 2, 7, 9, 29, 86, 90
SEG1_LOGRECNO, SEG1_P1_001N = 4, 5                 # hi000012020.pl
OUTSIDE = "outside CDPs"
SECOND_SHARE = 0.25               # second CDP named when it has >= 25% of the people
OUTSIDE_MAJORITY = 0.50           # "rural near ..." when > 50% live outside any CDP

CDP_LAYER = ("https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/"
             "tigerWMS_Census2020/MapServer/28")
CDP_WHERE = "STATE='15'"
NEAR_KM = 5.0
MIN_SHARE = 0.20                  # a CDP must cover at least 20% of the tract's area
GRID_POINTS = 400                 # sample grid per tract (about 20 x 20)
NIIHAU_WEST_OF = -160.0
NWHI_WEST_OF = -160.6                              # same cut as svgmap.MAIN_ISLANDS_WEST
KAHOOLAWE_BBOX = (-156.70, 20.49, -156.52, 20.61)  # lon0, lat0, lon1, lat1
FIELDS = ["tract_fips", "county", "tract_number", "community", "island", "tract_label",
          "label_main", "label_sub",
          "method", "pop_2020", "pop_share_top", "pop_share_second", "pop_outside_cdp",
          "pop_shares", "cdp_geoid", "cdp_name", "area_label", "area_shares", "distance_km",
          "point_lon", "point_lat", "source", "source_url"]
POP_FIELDS = ["tract_fips", "cdp_geoid", "cdp_name", "pop_2020", "tract_pop_2020",
              "share", "source", "source_url"]


def tract_number(fips: str) -> str:
    """'15009030800' -> '308'; '15009030903' -> '309.03'."""
    code = str(fips)[-6:]
    base, suffix = int(code[:4]), code[4:]
    return str(base) if suffix == "00" else f"{base}.{suffix}"


def census_area(fips: str) -> str:
    """Second line shown to readers: 'Census area 308'."""
    return f"Census area {tract_number(fips)}"


def tract_label(fips: str, community: str) -> str:
    """One-line label, community first: 'Waikapū / Waiheʻe-Waiehu · Census area 308'."""
    return f"{community} · {census_area(fips)}"


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


def overlap_shares(geom: dict, places: list, n: int = GRID_POINTS) -> list:
    """[(share, geoid, name)] of the tract area inside each CDP, largest first."""
    tb = bbox_of(geom)
    near = [p for p in places if not (p[3][2] < tb[0] or p[3][0] > tb[2]
                                      or p[3][3] < tb[1] or p[3][1] > tb[3])]
    pts = sample_points(geom, n)
    hits = {}
    for x, y in pts:
        for geoid, name, g, (x0, y0, x1, y1) in near:
            if x0 <= x <= x1 and y0 <= y <= y1 and point_in_geometry(x, y, g):
                hits[(geoid, name)] = hits.get((geoid, name), 0) + 1
                break                                   # CDPs do not overlap
    return sorted(((c / len(pts), gid, name) for (gid, name), c in hits.items()),
                  key=lambda s: (-s[0], s[2]))


def build(afn: dict, cdps: dict, islands: dict, display: dict | None = None) -> list:
    """display: CDP GEOID -> Hawaiian display spelling (build_place_names.py)."""
    display = display or {}
    places = []
    for f in cdps["features"]:
        p, g = f["properties"], f["geometry"]
        if g:
            places.append((p["GEOID"], display.get(p["GEOID"], p["BASENAME"]), g, bbox_of(g)))
    rows = []
    for f in afn["features"]:
        fips, county = f["properties"]["tract_fips"], f["properties"]["county"]
        lon, lat = representative_point(f["geometry"])
        shares = overlap_shares(f["geometry"], places)
        big = [s for s in shares if s[0] >= MIN_SHARE][:2]
        d = None
        if len(big) == 2:
            method, community = "area_2", f"{big[0][2]} / {big[1][2]}"
            _, geoid, name = big[0]
            name = community
        elif big:
            method, (_, geoid, name) = "area", big[0]
            community = name
        else:
            pad_lon = NEAR_KM / (111.32 * math.cos(math.radians(lat)))
            pad_lat = NEAR_KM / 110.574
            near = sorted((distance_km(lon, lat, g), n_, gid)
                          for gid, n_, g, (x0, y0, x1, y1) in places
                          if x0 - pad_lon <= lon <= x1 + pad_lon
                          and y0 - pad_lat <= lat <= y1 + pad_lat)
            if shares:                                   # touches a CDP, < 20% of its area
                _, geoid, name = shares[0]
                method, community, d = "near", f"near {name}", 0.0   # the CDP touches the tract
            elif near and near[0][0] <= NEAR_KM:
                d, name, geoid = near[0]
                method, community = "near", f"near {name}"
            else:
                method = "area_rural"
                same = [(math.hypot(lon - (b[0] + b[2]) / 2, lat - (b[1] + b[3]) / 2), n_, gid)
                        for gid, n_, _g, b in places if islands.get(gid, ("", ""))[1] == county]
                _, name, geoid = min(same)
        island = islands[geoid][0]
        if method == "area_rural":
            island = remote_island(county, lon, lat) or island
            community, name, geoid = f"rural {island}", "", ""
        rows.append({
            "tract_fips": fips, "county": county, "tract_number": tract_number(fips),
            "community": community, "island": island,
            "tract_label": tract_label(fips, community), "method": method,
            "cdp_geoid": geoid, "cdp_name": name if method != "area_rural" else "",
            "area_shares": "; ".join(f"{nm} {s:.2f}" for s, _g, nm in shares[:3]),
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


# ---------------------------------------------------------------- population weighting

def download_blocks() -> None:
    BLOCKS.mkdir(parents=True, exist_ok=True)
    for url in (BAF_URL, PL_URL):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=300) as r:
            (BLOCKS / url.rsplit("/", 1)[1]).write_bytes(r.read())


def read_blocks(blocks: Path = BLOCKS) -> dict:
    """Official files -> {'place': {block: placefp}, 'pop': {block: P1_001N},
    'pop100': {block: POP100}, 'names': {placefp: name}, 'tract_pop': {tract: P1_001N}}."""
    with zipfile.ZipFile(blocks / BAF_URL.rsplit("/", 1)[1]) as z:
        lines = io.TextIOWrapper(z.open(BAF_MEMBER), encoding="latin-1").read().splitlines()
    place = {}
    for line in lines[1:]:
        block, fp = line.split("|")
        if fp.strip():
            place[block] = fp.strip()
    with zipfile.ZipFile(blocks / PL_URL.rsplit("/", 1)[1]) as z:
        geo = [l.split("|") for l in
               io.TextIOWrapper(z.open("higeo2020.pl"), encoding="latin-1").read().splitlines()]
        seg1 = {}
        for l in io.TextIOWrapper(z.open("hi000012020.pl"), encoding="latin-1"):
            f = l.split("|")
            seg1[f[SEG1_LOGRECNO]] = int(f[SEG1_P1_001N])
    out = {"place": place, "pop": {}, "pop100": {}, "names": {}, "tract_pop": {}}
    for g in geo:
        lev, code = g[GEO_SUMLEV], g[GEO_GEOCODE]
        if lev == "750":
            out["pop"][code] = seg1[g[GEO_LOGRECNO]]
            out["pop100"][code] = int(g[GEO_POP100])
        elif lev == "160":
            out["names"][g[GEO_PLACE]] = g[GEO_BASENAME]
        elif lev == "140":
            out["tract_pop"][code] = seg1[g[GEO_LOGRECNO]]
    return out


def tract_cdp_population(b: dict) -> dict:
    """tract -> {placefp or OUTSIDE: people}."""
    out = {}
    for block, pop in b["pop"].items():
        key = b["place"].get(block, OUTSIDE)
        t = out.setdefault(block[:11], {})
        t[key] = t.get(key, 0) + pop
    return out


def population_label(pops: dict, names: dict) -> tuple:
    """(community or None if no people, method, top share, second share, outside share).
    'rural <island>' is completed by the caller, which knows the island."""
    total = sum(pops.values())
    if total == 0:
        return None, "", 0.0, 0.0, 0.0
    outside = pops.get(OUTSIDE, 0) / total
    ranked = sorted(((p / total, names[fp]) for fp, p in pops.items() if fp != OUTSIDE and p > 0),
                    key=lambda x: (-x[0], x[1]))
    top = ranked[0][0] if ranked else 0.0
    second = ranked[1][0] if len(ranked) > 1 else 0.0
    if outside > OUTSIDE_MAJORITY:
        return (f"rural near {ranked[0][1]}" if ranked else "rural"), "pop_rural", top, second, outside
    if second >= SECOND_SHARE:
        return f"{ranked[0][1]} / {ranked[1][1]}", "pop_2", top, second, outside
    return ranked[0][1], "pop", top, second, outside


def apply_population(rows: list, tract_pops: dict, names: dict, islands: dict,
                     display: dict | None = None) -> list:
    """Replace area labels by population-weighted labels where the tract has people.
    Islands are looked up by CDP code (names repeat: Kailua, Waimea)."""
    out = []
    for r in rows:
        pops = tract_pops.get(r["tract_fips"], {})
        total = sum(pops.values())
        shown = {fp: (display or {}).get("15" + fp, n) for fp, n in names.items()}
        community, method, top, second, outside = population_label(pops, shown)
        ranked = sorted(pops.items(), key=lambda kv: (-kv[1], kv[0]))
        r = {**r, "area_label": r["tract_label"], "pop_2020": total,
             "pop_share_top": round(top, 4), "pop_share_second": round(second, 4),
             "pop_outside_cdp": round(outside, 4) if total else "",
             "pop_shares": "; ".join(f"{shown.get(k, k)} {v / total:.2f}"
                                     for k, v in ranked[:4]) if total else ""}
        if community is not None:                       # else: area fallback, 0 people
            lead = next((k for k, v in ranked if k != OUTSIDE and v > 0), "")
            if not lead and r["method"] != "area_rural" and r["cdp_geoid"]:
                lead = r["cdp_geoid"][-5:]               # nearest CDP by geography
                community, method = f"near {shown[lead]}", "pop_near"
            island = islands.get("15" + lead, (r["island"],))[0] if lead else r["island"]
            if community == "rural":
                community = f"rural {island}"
            r.update({"community": community, "island": island, "method": method,
                      "tract_label": tract_label(r["tract_fips"], community),
                      "cdp_geoid": "15" + lead if lead else "",
                      "cdp_name": names.get(lead, ""), "distance_km": "",
                      "source": "2020 Census Block Assignment File (place/CDP) and 2020 PL "
                                "94-171 block population P1_001N; island from DBEDT Data "
                                "Book 2025 table 01.12",
                      "source_url": f"{BAF_URL} ; {PL_URL}"})
        out.append(r)
    return out


def population_rows(tract_pops: dict, names: dict) -> list:
    rows = []
    for tract in sorted(tract_pops):
        pops = tract_pops[tract]
        total = sum(pops.values())
        for k, v in sorted(pops.items(), key=lambda kv: (-kv[1], kv[0])):
            rows.append({"tract_fips": tract, "cdp_geoid": "" if k == OUTSIDE else "15" + k,
                         "cdp_name": names.get(k, OUTSIDE), "pop_2020": v,
                         "tract_pop_2020": total,
                         "share": round(v / total, 4) if total else "",
                         "source": "2020 Census Block Assignment File (INCPLACE_CDP) + "
                                   "2020 PL 94-171 block P1_001N",
                         "source_url": f"{BAF_URL} ; {PL_URL}"})
    return rows


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
        download_blocks()
    cdps = json.loads(RAW.read_text(encoding="utf-8"))
    afn = json.loads(AFN.read_text(encoding="utf-8"))
    islands = cdp_islands()
    blocks = read_blocks()
    tract_pops = tract_cdp_population(blocks)
    display = load_display_names()
    rows = apply_population(build(afn, cdps, islands, display), tract_pops, blocks["names"],
                            islands, display)
    for r in rows:
        r["label_main"], r["label_sub"] = r["community"], census_area(r["tract_fips"])
    for path, fields, data in ((OUT, FIELDS, rows),
                               (OUT_POP, POP_FIELDS, population_rows(tract_pops, blocks["names"]))):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
            w.writeheader()
            w.writerows(data)
    counts = {m: sum(r["method"] == m for r in rows)
              for m in ("pop", "pop_2", "pop_near", "pop_rural", "area", "area_2", "near",
                        "area_rural")}
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(rows)} tracts, {len(cdps['features'])} CDPs; "
          + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
