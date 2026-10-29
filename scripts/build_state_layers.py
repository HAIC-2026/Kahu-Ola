#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – summaries of three public State layers (fetch_state_layers.py).

Reads data/raw/state_layers/ (gitignored) and writes data/sources/state_layers_summary.json
(committed), which the app and the PDF playbooks read:
  childcare  centre-based sites only (licensed group child care, public pre-K, charter
             pre-K); family child care homes / home-based providers are never kept. Island,
             county, Census area, and the zone per hazard (same screens as shelter sites:
             tsunami evacuation zone; FEMA flood zone A/AE/V/VE; zone D listed separately)
  sirens     permanent outdoor warning sirens: point, island, Census area; counts per Census
             area and county (no live status)
  dams       share of each Census area inside any dam evacuation zone (100 grid points, the
             same method as the tsunami share), people = share x population; county totals;
             shelter sites inside a dam evacuation zone ("Check dam zone")

Without data/raw/state_layers/ the committed summary is kept as is.

Usage:  python3 scripts/build_state_layers.py             (queries FEMA flood zones for new points)
        python3 scripts/build_state_layers.py --offline   (rebuild step: cached flood zones only)
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_access as ba  # noqa: E402
import fetch_arcgis as fa  # noqa: E402
from fetch_flood_zones import is_sfha  # noqa: E402
from geo import ZoneIndex, haversine_km, point_in_geometry  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "state_layers"
OUT = ROOT / "data" / "sources" / "state_layers_summary.json"
FLOOD_CACHE = RAW / "childcare_flood.json"
SNAP_KM = 3                                    # shoreline points: nearest Census area land point
SNAP_ISLAND_KM = 10                            # ... when the island is known
SAMPLES = 100                                  # grid points per Census area (as tsunami)
CENTRE_TYPES = {"Licensed Group Child Care (Preschools) - PATCH": "Licensed group child care",
                "EOEL": "Public pre-K (EOEL)", "Charter": "Charter school pre-K"}
HOME_BASED = re.compile(r"family\s+child\s*care|\bfcc\b|in-home|home-based|\bhome\b", re.I)
CHILDCARE_LABEL = "Childcare centre"
NO_SIRENS = "prioritise WEA, radio and trusted messengers"
DAM_LINE = "People in dam evacuation zones"
DAM_DETAIL = "State dam evacuation zones"
CHECK_DAM = "Check dam zone"


def land_points() -> list:
    with open(fa.ISLANDS, newline="", encoding="utf-8") as fh:
        return [(r["id"], float(r["lon"]), float(r["lat"]), r["island"], r["county"])
                for r in csv.DictReader(fh) if r["kind"] == "area" and r["island"] in fa.ISLE_COUNTY]


def locate(lon: float, lat: float, island_of, tracts, land: list) -> tuple[str, dict]:
    """(island, Census area properties) for a point. Shoreline points just off the
    simplified coast or Census outlines take the island of their Census area, or the
    nearest Census area land point on the same island (10 km), or on any island (3 km)."""
    island = island_of(lon, lat)
    tract = (tracts.find(lon, lat) or {}).get("properties") or {}
    by_id = {a[0]: a for a in land}
    if tract and not island and tract.get("tract_fips") in by_id:
        island = by_id[tract["tract_fips"]][3]
    if not tract:
        pool = [a for a in land if a[3] == island] if island else land
        near = min(pool, key=lambda a: haversine_km(lon, lat, a[1], a[2]), default=None)
        if near and haversine_km(lon, lat, near[1], near[2]) <= (SNAP_ISLAND_KM if island else SNAP_KM):
            island, tract = near[3], {"tract_fips": near[0], "county": near[4]}
    return island, tract


def is_centre(p: dict) -> bool:
    """Centre-based sites only: a known centre type and nothing that marks a home."""
    text = f"{p.get('name') or ''} {p.get('notes') or ''}"
    return p.get("site_type") in CENTRE_TYPES and not HOME_BASED.search(text)


def childcare(feats: list, island_of, tracts, tsunami, offline: bool) -> tuple[list, dict]:
    cache = fa.load_json(FLOOD_CACHE, {})
    land = land_points()
    out, dropped = [], {"not a centre type": 0, "home-based": 0}
    try:
        for f in feats:
            p = f["properties"]
            if p.get("site_type") not in CENTRE_TYPES:
                dropped["not a centre type"] += 1
                continue
            if not is_centre(p):
                dropped["home-based"] += 1
                continue
            lon, lat = (round(c, 4) for c in f["geometry"]["coordinates"][:2])
            island, tract = locate(lon, lat, island_of, tracts, land)
            zone = ba.flood_zone(lon, lat, cache, offline)
            z = {"in_tsunami_zone": tsunami.contains(lon, lat), "fld_zone": zone,
                 "in_sfha": is_sfha(zone)}
            out.append({"name": " ".join(str(p["name"]).split()), "type": "childcare",
                        "type_label": CHILDCARE_LABEL, "kind": CENTRE_TYPES[p["site_type"]],
                        "address": " ".join(f"{p.get('street_address') or ''}, {p.get('city') or ''}".split()),
                        "lon": lon, "lat": lat, "island": island,
                        "county": fa.ISLE_COUNTY.get(island) or tract.get("county", ""),
                        "tract": tract.get("tract_fips", ""), "in_tsunami_zone": z["in_tsunami_zone"],
                        "fld_zone": zone, "zones": ba.hazard_zones(z)})
    finally:
        fa.save_json(FLOOD_CACHE, cache)
    return sorted(out, key=lambda x: (x["county"], x["name"])), dropped


def sirens(feats: list, island_of, tracts) -> list:
    land = land_points()
    out = []
    for f in feats:
        p = f["properties"]
        if (p.get("Permanent_Mobile") or "").strip().lower() != "permanent" or not f.get("geometry"):
            continue
        lon, lat = (round(c, 4) for c in f["geometry"]["coordinates"][:2])
        island, tract = locate(lon, lat, island_of, tracts, land)
        out.append({"id": p.get("Siren_Iden") or "", "name": p.get("Location") or "",
                    "lon": lon, "lat": lat, "island": island,
                    "county": fa.ISLE_COUNTY.get(island) or tract.get("county", ""),
                    "tract": tract.get("tract_fips", "")})
    return sorted(out, key=lambda x: (x["county"], x["id"]))


def summarize(offline: bool = False) -> dict | None:
    need = ["childcare.geojson", "sirens.geojson", "dams.geojson", "meta.json"]
    if not all((RAW / n).exists() for n in need):
        return None
    load = lambda n: json.loads((RAW / n).read_text(encoding="utf-8"))  # noqa: E731
    meta = load("meta.json")
    coast = ZoneIndex(fa.load_json(fa.COAST, None))
    from build_islands import island_of as _island_of
    island_of = lambda x, y: _island_of(coast, x, y)  # noqa: E731
    afn = fa.load_json(fa.AFN, {"features": []})
    tracts = ZoneIndex(afn)
    tsunami = ZoneIndex(fa.load_json(ba.TSUNAMI, None))
    dams = ZoneIndex(load("dams.geojson"))
    with open(fa.ISLANDS, newline="", encoding="utf-8") as fh:
        island = {r["id"]: r["island"] for r in csv.DictReader(fh) if r["kind"] == "area"}

    cc, dropped = childcare(load("childcare.geojson")["features"], island_of, tracts, tsunami, offline)
    sv = sirens(load("sirens.geojson")["features"], island_of, tracts)
    per_tract = {}
    for s in sv:
        per_tract[s["tract"]] = per_tract.get(s["tract"], 0) + 1

    areas, county_dam = {}, {}
    for f in afn["features"]:
        p = f["properties"]
        fips, pop = p["tract_fips"], p.get("population") or 0
        share = round(dams.share_inside(f["geometry"], SAMPLES), 3)
        people = round(pop * share)
        areas[fips] = {"county": p["county"], "island": island.get(fips, ""), "population": pop,
                       "sirens": per_tract.get(fips, 0), "dam_share": share, "dam_people": people}
        county_dam[p["county"]] = county_dam.get(p["county"], 0) + people

    site_dam = {}                    # shelter site -> dam evacuation zones it is inside
    for f in fa.load_json(fa.SHELTERS, {"features": []})["features"]:
        g = f.get("geometry")
        if not g:
            continue
        lon, lat = g["coordinates"][:2]
        hits = sorted({feat["properties"].get("dam_name") or "unnamed dam"
                       for (x0, y0, x1, y1), geom, _k, feat in dams.items
                       if x0 <= lon <= x1 and y0 <= lat <= y1 and point_in_geometry(lon, lat, geom)})
        if hits:
            site_dam[f"{f['properties']['name']}|{f['properties']['county']}"] = hits

    sirens_county = {}
    for s in sv:
        sirens_county[s["county"]] = sirens_county.get(s["county"], 0) + 1
    zero = {fips: a for fips, a in areas.items()
            if a["population"] > 0 and a["sirens"] == 0 and a["island"] in fa.ISLE_COUNTY}
    return {
        "meta": {"sources": {k: meta[k] for k in ("childcare", "sirens", "dams")},
                 "siren_radius": meta["siren_radius"], "childcare_dropped": dropped,
                 "childcare_label": CHILDCARE_LABEL, "no_sirens_text": NO_SIRENS,
                 "dam_line": DAM_LINE, "dam_detail": DAM_DETAIL, "check_dam": CHECK_DAM,
                 "dam_method": f"share of {SAMPLES} grid points of each Census area inside any "
                               "dam evacuation zone, times the area's population (the same "
                               "method as the tsunami share)"},
        "childcare": cc,
        "sirens": sv,
        "sirens_by_county": dict(sorted(sirens_county.items())),
        "areas": areas,
        "zero_siren_areas": sorted(zero),
        "dam_people_by_county": dict(sorted(county_dam.items())),
        "site_dam_zones": site_dam,
    }


def load(path: Path = OUT) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def report(s: dict) -> str:
    from collections import Counter
    out = [f"childcare centres: {len(s['childcare'])} (dropped {s['meta']['childcare_dropped']})"]
    fz = Counter((f["county"], h) for f in s["childcare"] for h, z in f["zones"].items() if z)
    out.append("  in hazard zones: " + ", ".join(f"{c} {h} {n}" for (c, h), n in sorted(fz.items())))
    zd = Counter(f["county"] for f in s["childcare"] if (f["fld_zone"] or "").upper() == "D")
    out.append(f"  FEMA zone D: {dict(zd)}")
    out.append(f"sirens (permanent): {s['sirens_by_county']}")
    zc = Counter(s["areas"][f]["county"] for f in s["zero_siren_areas"])
    pop = Counter()
    for f, a in s["areas"].items():
        if a["population"] > 0 and a["island"] in fa.ISLE_COUNTY:
            pop[a["county"]] += 1
    out.append("populated areas with 0 sirens: " + ", ".join(f"{c} {zc[c]} of {pop[c]}" for c in sorted(pop)))
    out.append(f"people in dam evacuation zones: {s['dam_people_by_county']}")
    out.append(f"shelter sites in a dam zone: {s['site_dam_zones'] or 'none'}")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Summaries of three public State layers")
    ap.add_argument("--offline", action="store_true", help="cached flood zones only")
    args = ap.parse_args(argv)
    s = summarize(args.offline)
    if s is None:
        print(f"No raw State layers in {RAW.relative_to(ROOT)}: "
              + (f"keeping {OUT.relative_to(ROOT)}" if OUT.exists() else "no summary"))
        return 0
    OUT.write_text(json.dumps(s, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")
    print(report(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
