#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – State Hub reference layers: committed summary (Phase 0).

Reads data/raw/hub/ (fetch_hub_layers.py, free public data) and the walking answers in
data/raw/arcgis/ (fetch_stress_routes.py, paid), and writes data/sources/hub_layers_summary.json
(committed; per-area summaries and simplified outlines only, never raw ArcGIS answers):

  safe_zone_walk  per Census area with people in households without a car inside the
                  tsunami evacuation zone: walking minutes from a populated point inside the
                  zone to the nearest Tsunami Safe Zone edge on the same island (Esri ArcGIS
                  walking time); without an ArcGIS answer, the straight-line distance, labelled
  fire_risk       per Census area: share and number of people inside State Fire Risk Areas
                  rated High / Medium / Low (2020 block population, as the tsunami share);
                  county totals; comparison with the default NRI wildfire footprint
  flooded         Sea Level Rise 3.2 ft "flooded highway" segments per county (simplified)
  pdc             PDC 2009 shelters matched to the 2026 sites and DOE candidate schools by
                  name and location; capacity offered only as "2009 reference capacity
                  (may be outdated)". Phone and contact fields are never downloaded.
  overlays        simplified Tsunami Safe Zone and Fire Risk outlines per county for the map

Fails closed: a missing or partial data/raw/hub/ stops the build unless none of it exists,
in which case the committed summary is kept (the same rule as the other State layers).

Usage:  python3 scripts/build_hub_layers.py
"""
from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import block_shares  # noqa: E402
import fetch_arcgis as fa  # noqa: E402
import fetch_stress_routes as fsr  # noqa: E402
import svgmap  # noqa: E402
from geo import ZoneIndex, haversine_km  # noqa: E402
from raw_inputs import MissingInput, load_geojson, load_json, rel, require_all_or_none  # noqa: E402

ROOT = fa.ROOT
RAW = ROOT / "data" / "raw" / "hub"
OUT = ROOT / "data" / "sources" / "hub_layers_summary.json"
REQUIRED = ["safe_zones.geojson", "fire_risk.geojson", "flooded_highways.geojson",
            "pdc_shelters.geojson", "roads.geojson", "meta.json"]
WALK_MIN_PER_KM = 60 / 4.0          # straight-line fallback label only: never mixed with routed times
STATE_HIGH_SHARE = 0.5              # team assumption: an area is "high" in the State layer when at
                                    # least half its people live in a High fire risk area
OVERLAY_TOL = 0.0015                # degrees (~150 m), as the tsunami zone outline
SAFE_TOL = 0.003                    # degrees (~300 m): the safe zones cover most of each island
MIN_RING = 2e-6                     # square degrees (~0.025 km2): islets and slivers are not drawn
FLOOD_TOL = 0.001                   # display only: ~100 m, under a pixel on a county map
PDC_MATCH_M = 400                   # within 400 m AND a shared distinctive name word AND the
                                    # same school level (elementary/middle/intermediate/high)
COUNTY_OF_ISLE = fa.ISLE_COUNTY
SZ_COUNTY = {"KAUAI": "Kauai", "NIIHAU": "Kauai", "OAHU": "Honolulu", "MAUI": "Maui",
             "MOLOKAI": "Maui", "LANAI": "Maui", "KAHOOLAWE": "Maui", "MOLOKINI": "Maui",
             "HAWAII": "Hawaii"}
FR_COUNTY = {"Kauai": "Kauai", "Oahu": "Honolulu", "Maui": "Maui", "Molokai": "Maui",
             "Lanai": "Maui", "Hawaii": "Hawaii"}
MAUI_2013 = ("Tsunami Safe Zones for Maui, Molokaʻi and Lānaʻi date from 2013; the other "
             "counties' zones date from 2025. Check Maui County's current evacuation maps.")
RATINGS = ("High", "Medium", "Low")
WALK_LABEL = ("Walking time to the nearest Tsunami Safe Zone edge (Esri ArcGIS walking "
              "routing, normal conditions) from a populated point inside the area's tsunami "
              "evacuation zone")
STRAIGHT_LABEL = ("straight-line distance to the nearest Tsunami Safe Zone edge (no walking "
                  "route available): not a walking time")


def plain(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c) and c not in "ʻ'‘’`").lower()


ABBR = {"es": "elementary", "el": "elementary", "elem": "elementary", "hs": "high",
        "is": "intermediate", "int": "intermediate", "ms": "middle", "sch": "school",
        "ctr": "center", "cntr": "center", "comm": "community", "gym": "gymnasium",
        "dist": "district", "pk": "park", "hi": "high"}
STOP = {"school", "the", "and", "of", "&", "a", "at", "ii", "complex", "cafeteria", "gymnasium",
        "building", "bldg", "hall", "center", "community", "park", "district", "neighborhood",
        "elementary", "high", "intermediate", "middle", "recreation", "county"}


def tokens(name: str) -> set:
    words = re.findall(r"[a-z0-9]+", plain(name))
    return {ABBR.get(w, w) for w in words} - STOP


def kind_tokens(name: str) -> set:
    words = re.findall(r"[a-z0-9]+", plain(name))
    return {ABBR.get(w, w) for w in words} & {"elementary", "high", "intermediate", "middle"}


# ---------------------------------------------------------------- safe zones

def walk_answers() -> dict:
    """area -> [walk min or None, walk km or None] (nearest of the safe-zone edge points)."""
    data = fa.load_json(fa.RAW / "walk_safe_zones.json", {"results": {}})
    out = {}
    for key, v in data["results"].items():
        m = v.get("matrix") or {}
        names = m.get("costAttributeNames") or ["WalkTime", "Kilometers"]
        ti, ki = names.index("WalkTime"), names.index("Kilometers")
        best = min(((c[ti], c[ki]) for c in (m.get("1") or {}).values() if c[ti] is not None),
                   default=(None, None))
        out[v["origin"]] = [best[0], best[1]]
    return out


def safe_zone_walk(counties: dict) -> dict:
    plan = load_json(fa.RAW / "safe_zone_plan.json", "safe-zone walking plan (fetch_stress_routes.py)")
    ans = walk_answers()
    out = {}
    for a, p in sorted(plan.items()):
        straight = p["dests"][0][2] if p["dests"] else None
        mins, km = ans.get(a, [None, None])
        if p["inside"]:
            row = {"method": "inside", "walk_min": 0.0}
        elif mins is not None:
            row = {"method": "arcgis_walk", "walk_min": round(mins, 1), "walk_km": round(km, 2)}
        else:
            row = {"method": "straight_line", "walk_min": None}
        out[a] = {"county": counties.get(a, ""), "island": p["island"], "no_car": p["no_car"],
                  "straight_km": straight, **row}
    return out


# ---------------------------------------------------------------- fire risk

def fire_risk(afn: dict, blocks: dict | None) -> tuple[dict, dict]:
    fr = load_geojson(RAW / "fire_risk.geojson", "State Fire Risk Areas")
    idx = {r: ZoneIndex({"type": "FeatureCollection", "features": [
        f for f in fr["features"] if (f["properties"].get("risk_rating") or "").strip() == r
        and f.get("geometry")]}) for r in RATINGS}
    areas, county = {}, {}
    for f in afn["features"]:
        p = f["properties"]
        fips, pop = p["tract_fips"], p.get("population") or 0
        row = {"county": p["county"], "population": pop}
        for r in RATINGS:
            s = block_shares.share(blocks, fips, idx[r].contains)
            share = round(s if s is not None else idx[r].share_inside(f["geometry"], 100), 3)
            row[f"{r.lower()}_share"] = share
            row[f"{r.lower()}_people"] = round(pop * share)
            c = county.setdefault(p["county"], {"high": 0, "medium": 0, "low": 0})
            c[r.lower()] += round(pop * share)
        areas[fips] = row
    return areas, county


def nri_footprint() -> dict:
    """area -> share in the default (NRI) wildfire footprint (model_needs.py)."""
    out = {}
    with open(fa.NEEDS_BY_TRACT, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["hazard"] == "wildfire":
                out[r["tract_fips"]] = float(r["share_at_risk"])
    return out


def fire_compare(areas: dict) -> dict:
    """Per county: areas high in the State layer (>= STATE_HIGH_SHARE of people in High), in
    the NRI footprint (top 25% of the county's areas by NRI wildfire score), both, one only."""
    nri = nri_footprint()
    out = {}
    for fips, a in sorted(areas.items()):
        if not a["population"]:
            continue
        c = out.setdefault(a["county"], {"both": [], "state_only": [], "nri_only": [],
                                         "people_state_high": 0, "people_nri": 0,
                                         "people_both": 0})
        s_hi, n_hi = a["high_share"] >= STATE_HIGH_SHARE, fips in nri
        c["people_state_high"] += a["high_people"]
        c["people_nri"] += round(a["population"] * nri.get(fips, 0))
        if s_hi and n_hi:
            c["both"].append(fips)
            c["people_both"] += a["high_people"]
        elif s_hi:
            c["state_only"].append(fips)
        elif n_hi:
            c["nri_only"].append(fips)
    for c in out.values():
        n = len(c["both"]) + len(c["state_only"]) + len(c["nri_only"])
        c["agreement"] = round(len(c["both"]) / n, 3) if n else None
    return out


# ---------------------------------------------------------------- flooded highways

def chains(paths: list) -> list:
    """Join segments that touch end to end (rounded to ~10 m) into longer polylines."""
    key = lambda xy: (round(xy[0], 4), round(xy[1], 4))  # noqa: E731
    todo = [list(map(list, p)) for p in paths if len(p) >= 2]
    out = []
    while todo:
        cur = todo.pop(0)
        grown = True
        while grown:
            grown = False
            for i, p in enumerate(todo):
                if key(p[0]) == key(cur[-1]):
                    cur += p[1:]
                elif key(p[-1]) == key(cur[0]):
                    cur = p[:-1] + cur
                elif key(p[-1]) == key(cur[-1]):
                    cur += p[::-1][1:]
                elif key(p[0]) == key(cur[0]):
                    cur = p[::-1][:-1] + cur
                else:
                    continue
                todo.pop(i)
                grown = True
                break
        out.append(cur)
    return out


def flooded(island_county) -> dict:
    paths = load_json(RAW / "flooded_paths.json", "flooded highway paths (fetch_stress_routes.py)")
    load_geojson(RAW / "flooded_highways.geojson", "flooded highways")
    out = {}
    for isl, ps in sorted(paths.items()):
        c = island_county(isl)
        row = out.setdefault(c, {"segments": [], "km": 0.0, "islands": {}, "pieces": 0})
        row["km"] = round(row["km"] + sum(haversine_km(*a, *b) for p in ps for a, b in zip(p, p[1:])), 2)
        row["islands"][isl] = row["islands"].get(isl, 0) + len(ps)
        row["pieces"] += len(ps)
        for p in chains(ps):
            pts = svgmap.simplify(p, FLOOD_TOL) if len(p) > 2 else p
            flat = []
            for x, y in pts:                   # 3 decimals (~100 m): drop repeated points
                xy = [round(x, 3), round(y, 3)]
                if flat[-2:] != xy:
                    flat += xy
            if len(flat) == 2:
                flat += flat
            row["segments"].append(flat)
    return out


# ---------------------------------------------------------------- PDC 2009 shelters

def pdc_match() -> dict:
    """PDC 2009 shelters matched to the 2026 activated sites and to DOE candidate schools."""
    pdc = load_geojson(RAW / "pdc_shelters.geojson", "PDC Hawaii Emergency Shelters")["features"]
    for f in pdc:
        if {"PHONE", "CONTACT"} & set(f["properties"]):
            raise MissingInput("PDC shelter download holds phone/contact fields: re-run "
                               "fetch_hub_layers.py (they must never be stored).")
    sites = [{"key": f"{f['properties']['name']}|{f['properties']['county']}",
              "name": f["properties"]["name"], "kind": "site",
              "lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1]}
             for f in fa.load_json(fa.SHELTERS, {"features": []})["features"] if f.get("geometry")]
    schools = [{"key": f["properties"]["id"], "name": f["properties"]["name"], "kind": "school",
                "lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1]}
               for f in fa.load_json(fa.CANDIDATES, {"features": []})["features"] if f.get("geometry")]
    rows, matched_sites, matched_schools = [], {}, {}
    for f in pdc:
        p, g = f["properties"], f.get("geometry")
        if not g:
            continue
        lon, lat = g["coordinates"][:2]
        cap = int(p.get("CAPACITY") or 0)
        name = " ".join(str(p.get("BUSNAME") or "").split())
        best = None
        for t in sites + schools:
            d = haversine_km(lon, lat, t["lon"], t["lat"]) * 1000
            if d > PDC_MATCH_M:
                continue
            shared = tokens(name) & tokens(t["name"])
            k1, k2 = kind_tokens(name), kind_tokens(t["name"])
            kinds_ok = (k1 & k2) if (k1 or k2) else True    # a school only matches a school of that level
            ok = bool(shared) and bool(kinds_ok)
            if ok and (best is None or (t["kind"] == "site", -d) > (best[0]["kind"] == "site", -best[1])):
                best = (t, d)
        row = {"name": name.title() if name.isupper() else name, "place": p.get("PLACENAME") or "",
               "capacity": cap or None, "lon": round(lon, 4), "lat": round(lat, 4)}
        if best:
            t, d = best
            row.update(match_kind=t["kind"], match_key=t["key"], match_name=t["name"],
                       distance_m=round(d))
            if cap:
                (matched_sites if t["kind"] == "site" else matched_schools)[t["key"]] = {
                    "capacity": cap, "pdc_name": row["name"], "distance_m": round(d)}
        rows.append(row)
    return {"rows": rows, "with_capacity": sum(1 for r in rows if r["capacity"]),
            "matched": sum(1 for r in rows if "match_key" in r),
            "matched_with_capacity": len(matched_sites) + len(matched_schools),
            "site_capacity": matched_sites, "school_capacity": matched_schools,
            "fields_dropped": ["phone", "contact"]}


# ---------------------------------------------------------------- overlays

def ring_area(r: list) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(r, r[1:]))) / 2


def overlay(fc: dict, county_of, tol: float, keep=None, min_ring: float = 0.0) -> dict:
    out = {}
    for f in fc["features"]:
        if not f.get("geometry") or (keep and not keep(f["properties"])):
            continue
        c = county_of(f["properties"])
        if not c:
            continue
        for ring in svgmap.rings(f["geometry"]):
            if all(x < -160.6 for x, _ in ring) or ring_area(ring) < min_ring:   # Niʻihau; islets
                continue
            pts = svgmap.simplify(ring, tol)
            if len(pts) >= 4:
                out.setdefault(c, []).append([v for x, y in pts for v in (round(x, 4), round(y, 4))])
    return out


# ---------------------------------------------------------------- summary

def summarize() -> dict | None:
    if not require_all_or_none(RAW, REQUIRED, "raw State Hub layers"):
        return None
    meta = load_json(RAW / "meta.json", "State Hub layer sources")
    afn = load_geojson(fa.AFN, "Census areas (build_map.py)")
    counties = {f["properties"]["tract_fips"]: f["properties"]["county"] for f in afn["features"]}
    blocks = block_shares.load()
    method = "population" if blocks else "area"
    areas, county_fire = fire_risk(afn, blocks)
    sz = load_geojson(RAW / "safe_zones.geojson", "Tsunami Safe Zones")
    fr = load_geojson(RAW / "fire_risk.geojson", "State Fire Risk Areas")
    isle_county = lambda isl: COUNTY_OF_ISLE.get(isl, "")  # noqa: E731
    walk = safe_zone_walk(counties)
    over = {}
    for a in walk.values():
        c = over.setdefault(a["county"], {"areas": 0, "over_15": 0, "over_30": 0, "no_car": 0,
                                          "no_car_over_15": 0, "no_car_over_30": 0,
                                          "straight_line": 0})
        c["areas"] += 1
        c["no_car"] = round(c["no_car"] + a["no_car"], 1)
        if a["method"] == "straight_line":
            c["straight_line"] += 1
        m = a["walk_min"]
        if m is not None and m > 15:
            c["over_15"] += 1
            c["no_car_over_15"] = round(c["no_car_over_15"] + a["no_car"], 1)
        if m is not None and m > 30:
            c["over_30"] += 1
            c["no_car_over_30"] = round(c["no_car_over_30"] + a["no_car"], 1)
    return {
        "meta": {"sources": {k: {kk: v.get(kk) for kk in ("title", "url", "page", "metadata", "dates",
                                                           "fetched_at", "item_page", "fields_dropped")
                                 if v.get(kk)} for k, v in meta.items()},
                 "maui_2013_note": MAUI_2013, "walk_label": WALK_LABEL,
                 "straight_label": STRAIGHT_LABEL, "share_method": method,
                 "share_word": block_shares.WORD[method],
                 "state_high_share": STATE_HIGH_SHARE,
                 "walk_origin": "the populated 2020 Census block (internal point) inside the "
                                "tsunami evacuation zone nearest the population-weighted "
                                "centre of the area's in-zone blocks",
                 "redistribution": "Raw ArcGIS answers are not committed; this file holds "
                                   "rounded, per-area summaries only."},
        "safe_zone_walk": walk,
        "safe_zone_by_county": dict(sorted(over.items())),
        "fire_risk": areas,
        "fire_risk_by_county": dict(sorted(county_fire.items())),
        "fire_compare": fire_compare(areas),
        "flooded": flooded(isle_county),
        "pdc": pdc_match(),
        "overlays": {
            "safe_zones": overlay(sz, lambda p: SZ_COUNTY.get((p.get("island") or "").strip().upper()), SAFE_TOL,
                                  min_ring=MIN_RING),
            "fire_high": overlay(fr, lambda p: FR_COUNTY.get((p.get("island") or "").strip()), OVERLAY_TOL,
                                 lambda p: (p.get("risk_rating") or "").strip() == "High"),
            "fire_medium": overlay(fr, lambda p: FR_COUNTY.get((p.get("island") or "").strip()), OVERLAY_TOL,
                                   lambda p: (p.get("risk_rating") or "").strip() == "Medium"),
        },
    }


def load(path: Path = OUT) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def report(s: dict) -> str:
    out = ["safe-zone walk by county: " + json.dumps(s["safe_zone_by_county"])]
    out.append("fire risk people by county: " + json.dumps(s["fire_risk_by_county"]))
    for c, v in s["fire_compare"].items():
        out.append(f"  {c}: both {len(v['both'])}, State only {len(v['state_only'])}, NRI only "
                   f"{len(v['nri_only'])}, agreement {v['agreement']}; people State High "
                   f"{v['people_state_high']:,} vs NRI footprint {v['people_nri']:,}")
    out.append("flooded highways: " + ", ".join(f"{c} {len(v['segments'])} segments {v['km']} km"
                                                for c, v in s["flooded"].items()))
    p = s["pdc"]
    out.append(f"PDC 2009: {len(p['rows'])} rows, {p['with_capacity']} with capacity, {p['matched']} "
               f"matched, {p['matched_with_capacity']} matched with capacity "
               f"(sites {len(p['site_capacity'])}, schools {len(p['school_capacity'])})")
    return "\n".join(out)


def main() -> int:
    try:
        s = summarize()
    except MissingInput as e:
        print(e, file=sys.stderr)
        return 1
    if s is None:
        if not load(OUT):
            print(f"Build stopped: no raw State Hub layers in {rel(RAW)} and no committed "
                  f"{rel(OUT)}.", file=sys.stderr)
            return 1
        print(f"No raw State Hub layers in {rel(RAW)}: keeping the committed {rel(OUT)}")
        return 0
    OUT.write_text(json.dumps(s, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")
    print(report(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
