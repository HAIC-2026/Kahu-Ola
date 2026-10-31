#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – paid ArcGIS routing for the stress tests, at BUILD TIME ONLY.

Steps (each prints its estimate first and stops if the run would pass the 22-credit budget,
counting every credit already spent, including the 10.10 of the first routing work):
  walk_safe_zones     walking time from a populated point inside each area's tsunami
                      evacuation zone to the 3 nearest edge points of a Tsunami Safe Zone on
                      the same island (areas with people in households without a car only)
  od_closures_drive   driving time with a road closed (polyline barrier along ~0.8 km of the
                      highway): affected areas -> 2026 activated sites on the island + the
                      DOE candidate schools already in the baseline matrix for that area
  od_closures_walk    walking time with the same closures: areas -> activated sites within
                      12 km (the same pairs as the baseline walk matrix)
  od_flooded_drive    driving time with every "flooded highway" segment of the island
                      (Sea Level Rise 3.2 ft) closed at once, for areas within 5 km of one

One request per origin area, so only the pairs that are needed are billed. Token: env
ARCGIS_TOKEN only, sent in POST bodies, never written anywhere (fetch_arcgis.scrub). Raw
answers stay in data/raw/arcgis/ (gitignored); build_stress_tests.py keeps per-area
summaries only. If the token expires (498/499) progress is saved and the script stops;
running it again resumes without repeating paid calls.

Usage:  python3 scripts/fetch_stress_routes.py --estimate     (no paid calls)
        ARCGIS_TOKEN=... python3 scripts/fetch_stress_routes.py [--steps a,b]
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import block_shares  # noqa: E402
import fetch_arcgis as fa  # noqa: E402
from geo import ZoneIndex, haversine_km  # noqa: E402
from raw_inputs import load_geojson, load_json  # noqa: E402

ROOT = fa.ROOT
HUB = ROOT / "data" / "raw" / "hub"
ROADS_CFG = ROOT / "config" / "stress_roads.json"
TSUNAMI = ROOT / "data" / "raw" / "tsunami_zone.geojson"
STEPS = ["walk_safe_zones", "od_closures_drive", "od_closures_walk", "od_flooded_drive"]
SAFE_K = 3                  # safe-zone edge points per origin
SAFE_SPACING_KM = 0.4       # ... at least this far apart
SAFE_MAX_KM = 12            # walking mode: straight line pre-filter, as the site walk times
FLOOD_NEAR_KM = 5
SZ_ISLAND = {"KAUAI": "Kauaʻi", "OAHU": "Oʻahu", "MOLOKAI": "Molokaʻi", "LANAI": "Lānaʻi",
             "MAUI": "Maui", "HAWAII": "Hawaiʻi"}
HPMS_ISLAND = {"Maui": "Maui", "Oahu": "Oʻahu", "Kauai": "Kauaʻi", "Hawaii": "Hawaiʻi",
               "Molokai": "Molokaʻi", "Lanai": "Lānaʻi"}


# ---------------------------------------------------------------- geometry helpers

def _xy(lon: float, lat: float, lat0: float) -> tuple[float, float]:
    return lon * 111.320 * math.cos(math.radians(lat0)), lat * 110.574


def nearest_on_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L))
    return ax + t * dx, ay + t * dy


def rings(geom: dict):
    if geom["type"] == "Polygon":
        yield from geom["coordinates"]
    elif geom["type"] == "MultiPolygon":
        for poly in geom["coordinates"]:
            yield from poly


def lines(geom: dict):
    if geom["type"] == "LineString":
        yield geom["coordinates"]
    elif geom["type"] == "MultiLineString":
        yield from geom["coordinates"]


def edge_points(lon: float, lat: float, polys: list, k: int = SAFE_K,
                spacing_km: float = SAFE_SPACING_KM, max_km: float = SAFE_MAX_KM) -> list:
    """Up to k points on the safe-zone boundary nearest to (lon, lat), at least spacing_km
    apart (straight line), within max_km. Each is [lon, lat, km]."""
    lat0 = lat
    px, py = _xy(lon, lat, lat0)
    pad = max_km / 100.0
    cands = []
    for g in polys:
        for ring in rings(g):
            for (ax, ay), (bx, by) in zip(ring, ring[1:]):
                if (max(ax, bx) < lon - pad or min(ax, bx) > lon + pad or
                        max(ay, by) < lat - pad or min(ay, by) > lat + pad):
                    continue
                x1, y1 = _xy(ax, ay, lat0)
                x2, y2 = _xy(bx, by, lat0)
                qx, qy = nearest_on_segment(px, py, x1, y1, x2, y2)
                d = math.hypot(qx - px, qy - py)
                if d <= max_km:
                    cands.append((d, qx, qy))
    cands.sort()
    out = []
    for d, qx, qy in cands:
        if all(math.hypot(qx - ox, qy - oy) >= spacing_km for _d, ox, oy in out):
            out.append((d, qx, qy))
        if len(out) == k:
            break
    k_lon = 111.320 * math.cos(math.radians(lat0))
    return [[round(qx / k_lon, 6), round(qy / 110.574, 6), round(d, 3)] for d, qx, qy in out]


# ---------------------------------------------------------------- inputs

def tsunami_no_car() -> dict:
    """area -> people in households without a car inside the tsunami evacuation zone
    (model_needs.py, tsunami rows)."""
    out = {}
    with open(fa.NEEDS_BY_TRACT, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["hazard"] == "tsunami":
                out[r["tract_fips"]] = float(r["T_no_vehicle_persons_at_risk"] or 0)
    return out


def zone_points(origins: list, tsunami: ZoneIndex, blocks: dict) -> dict:
    """area -> [lon, lat, people] : the populated 2020 block (internal point) inside the
    tsunami evacuation zone closest to the population-weighted centre of the area's in-zone
    blocks (a real, populated, in-zone point; the mean itself can fall in the sea)."""
    out = {}
    for o in origins:
        rows = [(x, y, p) for x, y, p in blocks["blocks"].get(o["id"], []) if tsunami.contains(x, y)]
        if not rows:
            continue
        tot = sum(p for *_xy_, p in rows)
        cx = sum(x * p for x, _y, p in rows) / tot
        cy = sum(y * p for _x, y, p in rows) / tot
        x, y, _p = min(rows, key=lambda r: (haversine_km(cx, cy, r[0], r[1]), r[0], r[1]))
        out[o["id"]] = [round(x, 6), round(y, 6), tot]
    return out


def safe_zone_polys() -> dict:
    """island -> [geometry] of the Tsunami Safe Zones."""
    out = {}
    for f in load_geojson(HUB / "safe_zones.geojson", "Tsunami Safe Zones")["features"]:
        isl = SZ_ISLAND.get((f["properties"].get("island") or "").strip().upper())
        if isl and f.get("geometry"):
            out.setdefault(isl, []).append(f["geometry"])
    return out


def in_any(lon, lat, polys) -> bool:
    from geo import point_in_geometry
    return any(point_in_geometry(lon, lat, g) for g in polys)


def safe_zone_plan(origins: list) -> dict:
    """area -> {"origin": [lon, lat], "island", "inside": bool, "dests": [[lon, lat, km]]}."""
    tsunami = ZoneIndex(load_geojson(TSUNAMI, "State tsunami evacuation zones"))
    blocks = block_shares.load()
    if not blocks:
        raise SystemExit("2020 Census blocks are needed (python3 scripts/block_shares.py)")
    nocar = tsunami_no_car()
    polys = safe_zone_polys()
    pts = zone_points([o for o in origins if nocar.get(o["id"], 0) > 0], tsunami, blocks)
    plan = {}
    for o in origins:
        if o["id"] not in pts:
            continue
        lon, lat, _p = pts[o["id"]]
        sz = polys.get(o["island"], [])
        inside = in_any(lon, lat, sz)
        plan[o["id"]] = {"origin": [lon, lat], "island": o["island"], "inside": inside,
                         "no_car": round(nocar[o["id"]], 1),
                         "dests": [] if inside else edge_points(lon, lat, sz)}
    return plan


def road_cfg() -> list:
    return load_json(ROADS_CFG, "road-closure stress test settings")["closures"]


def route_lines(island: str, route: str) -> list:
    out = []
    for f in load_geojson(HUB / "roads.geojson", "HPMS road centrelines")["features"]:
        p = f["properties"]
        if p["route_id"] == route and HPMS_ISLAND.get(p["island"]) == island and f.get("geometry"):
            out += list(lines(f["geometry"]))
    return out


def barrier_paths(c: dict) -> list:
    """Polyline barrier(s): for each anchor, the route's centreline vertices within
    c['half_km'] of the route point nearest the anchor (contiguous runs only)."""
    paths = []
    ls = route_lines(c["island"], c["route"])
    if not ls:
        raise SystemExit(f"{c['id']}: route {c['route']} not found in the HPMS download")
    for ax, ay in c["anchors"]:
        best = min(((haversine_km(ax, ay, x, y), i, j) for i, l in enumerate(ls)
                    for j, (x, y) in enumerate(l)))
        _d, i, j = best
        line = ls[i]
        sx, sy = line[j]
        run = [j]
        for step in (-1, 1):
            k = j + step
            while 0 <= k < len(line) and haversine_km(sx, sy, *line[k]) <= c["half_km"]:
                run.append(k)
                k += step
        run.sort()
        path = [[round(line[k][0], 6), round(line[k][1], 6)] for k in run]
        if len(path) < 2:           # a single vertex: add its neighbour so it is a line
            nb = j + 1 if j + 1 < len(line) else j - 1
            path = sorted([path[0], [round(line[nb][0], 6), round(line[nb][1], 6)]])
        paths.append(path)
    return paths


def circle(lon: float, lat: float, radius_m: float, n: int = 16) -> list:
    """Closed ring of n points, radius_m around (lon, lat)."""
    k_lon = 111320 * math.cos(math.radians(lat))
    ring = [[round(lon + radius_m * math.cos(2 * math.pi * i / n) / k_lon, 6),
             round(lat + radius_m * math.sin(2 * math.pi * i / n) / 110574, 6)] for i in range(n)]
    return ring + [ring[0]]


def barrier(c: dict) -> dict:
    """{"lines": [...], "polygons": [...]} for one closure. "polygon" closures use a small
    circle around a surveyed Hawaiʻi DOT mile-marker point (where the HPMS centreline is too
    generalised for a line barrier to land on the road network)."""
    if c.get("barrier") == "polygon":
        return {"lines": [], "polygons": [circle(x, y, c["radius_m"]) for x, y in c["anchors"]]}
    return {"lines": barrier_paths(c), "polygons": []}


def flooded_paths() -> dict:
    """island -> [[lon, lat], ...] paths of the 3.2 ft flooded highway segments."""
    coast = ZoneIndex(load_geojson(fa.COAST, "State coastline (island outlines)"))
    from build_islands import island_of
    out = {}
    for f in load_geojson(HUB / "flooded_highways.geojson", "flooded highways")["features"]:
        if not f.get("geometry"):
            continue
        for l in lines(f["geometry"]):
            mid = l[len(l) // 2]
            isl = island_of(coast, mid[0], mid[1])
            if not isl:          # just off the simplified coast: nearest vertex on land
                isl = next((island_of(coast, x, y) for x, y in l if island_of(coast, x, y)), "")
            if isl:
                out.setdefault(isl, []).append([[round(x, 6), round(y, 6)] for x, y in l])
    return out


def destinations(island_of) -> tuple[dict, dict, dict]:
    """(activated sites by island, schools by id, baseline school ids per area)."""
    sites = fa.load_sites()
    pts = fa.site_points(sites, fa.load_json(fa.RAW / "geocode_sites.json", {}), island_of)
    by_isl = {}
    for p in pts:
        if p["lon"] is not None and p["island"]:
            by_isl.setdefault(p["island"], []).append(
                {"id": p["key"], "lon": p["lon"], "lat": p["lat"]})
    schools = {s["id"]: s for s in fa.candidate_schools(island_of)}
    base = fa.load_json(fa.RAW / "od_schools.json", {"results": {}})["results"]
    per_area = {v["origins"][0]: v["destinations"] for v in base.values()}
    return by_isl, schools, per_area


def near_any(lon, lat, paths, km) -> bool:
    return any(haversine_km(lon, lat, x, y) <= km for p in paths for x, y in p)


def closure_jobs(origins: list, by_isl: dict, schools: dict, per_area: dict, walk: bool,
                 flooded: dict | None = None) -> list:
    """[(job key, scenario id, origin, [dest], barrier paths)] — one per origin area."""
    jobs = []
    scenarios = ([{"id": f"flooded_{fa.plain(isl).lower()}", "island": isl, "paths": p,
                   "radius_km": FLOOD_NEAR_KM, "near_paths": True}
                  for isl, p in sorted((flooded or {}).items())] if flooded is not None else
                 [{**c, "barrier": barrier(c)} for c in road_cfg()])
    for sc in scenarios:
        for o in origins:
            if o["island"] != sc["island"]:
                continue
            if sc.get("near_paths"):
                if not near_any(o["lon"], o["lat"], sc["paths"], sc["radius_km"]):
                    continue
            elif min(haversine_km(o["lon"], o["lat"], x, y) for x, y in sc["anchors"]) > sc["radius_km"]:
                continue
            ds = list(by_isl.get(o["island"], []))
            if walk:
                ds = [d for d in ds if haversine_km(o["lon"], o["lat"], d["lon"], d["lat"]) <= fa.WALK_KM]
            else:
                ds += [{"id": s, "lon": schools[s]["lon"], "lat": schools[s]["lat"]}
                       for s in per_area.get(o["id"], []) if s in schools]
            if ds:
                jobs.append((f"{sc['id']}|{o['id']}", sc["id"], o, ds,
                             sc.get("barrier") or {"lines": sc["paths"], "polygons": []}))
    return jobs


def barriers_json(paths: list) -> str:
    return json.dumps({"features": [{"geometry": {"paths": [p], "spatialReference": {"wkid": 4326}},
                                     "attributes": {"Name": f"closure {i + 1}", "BarrierType": 0}}
                                    for i, p in enumerate(paths)]})


def polygons_json(polys: list) -> str:
    return json.dumps({"features": [{"geometry": {"rings": [r], "spatialReference": {"wkid": 4326}},
                                     "attributes": {"Name": f"closure {i + 1}", "BarrierType": 0}}
                                    for i, r in enumerate(polys)]})


# ---------------------------------------------------------------- paid runs

def run_jobs(step: str, mode_name: str, time_attr: str, jobs: list, token: str, led: dict,
             barriers: bool = True) -> dict:
    path = fa.RAW / f"{step}.json"
    out = fa.load_json(path, {"mode": mode_name, "results": {}})
    todo = [j for j in jobs if j[0] not in out["results"]]
    if not todo:
        print(f"[skip] {step}: all {len(jobs)} requests already done")
        return out
    pairs = sum(len(j[3]) for j in todo)
    est = fa.guard(led, step, pairs, fa.RATE["od_pair"], "OD pairs")
    mode = fa.travel_modes(token).get(mode_name)
    if not mode:
        raise RuntimeError(f"travel mode {mode_name!r} not offered by the service")
    billed = 0
    try:
        for key, scen, o, ds, bar in todo:
            params = {"origins": fa.features([o]), "destinations": fa.features(ds),
                      "travelMode": json.dumps(mode),
                      "outputType": "esriNAODOutputSparseMatrix",
                      "accumulateAttributeNames": f"Kilometers,{time_attr}",
                      "impedanceAttributeName": time_attr, "returnEmptyResults": "true"}
            if barriers and bar.get("lines"):
                params["polylineBarriers"] = barriers_json(bar["lines"])
            if barriers and bar.get("polygons"):
                params["polygonBarriers"] = polygons_json(bar["polygons"])
            data = fa.post(fa.OD_BASE + "/solveODCostMatrix", params, token)
            if "error" in data:
                raise RuntimeError(f"{step} {key}: {data['error'].get('message')} "
                                   f"{data['error'].get('details')}")
            billed += len(ds)
            m = data.get("odCostMatrix") or {}
            out["results"][key] = {"scenario": scen, "origin": o["id"], "island": o["island"],
                                   "destinations": [d["id"] for d in ds], "matrix": m,
                                   "messages": [x.get("description", "") for x in
                                                data.get("messages", [])][:5]}
            if len(out["results"]) % 10 == 0:
                fa.save_json(path, fa.scrub(out, token))
            print(f"  {step} {key}: 1 x {len(ds)}")
    finally:
        fa.save_json(path, fa.scrub(out, token))
        fa.record(led, step, billed, fa.RATE["od_pair"], "OD pairs",
                  est if billed == pairs else round(billed * fa.RATE["od_pair"], 4))
    return out


def safe_zone_jobs(plan: dict, origins: list) -> list:
    by_id = {o["id"]: o for o in origins}
    jobs = []
    for a, p in sorted(plan.items()):
        if p["inside"] or not p["dests"]:
            continue
        o = {**by_id[a], "lon": p["origin"][0], "lat": p["origin"][1]}
        ds = [{"id": f"sz{i}", "lon": x, "lat": y} for i, (x, y, _km) in enumerate(p["dests"])]
        jobs.append((a, "safe_zone", o, ds, {}))
    return jobs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Paid ArcGIS routing for the stress tests")
    ap.add_argument("--estimate", action="store_true", help="print counts, make no paid calls")
    ap.add_argument("--steps", default=",".join(STEPS))
    args = ap.parse_args(argv)
    steps = [s for s in args.steps.split(",") if s]

    coast = ZoneIndex(load_geojson(fa.COAST, "State coastline (island outlines)"))
    from build_islands import island_of as _island_of
    island_of = lambda x, y: _island_of(coast, x, y)  # noqa: E731
    origins = fa.populated_origins()
    by_isl, schools, per_area = destinations(island_of)

    plan = safe_zone_plan(origins)
    fa.save_json(fa.RAW / "safe_zone_plan.json", plan)            # free, needed by the build
    flooded = flooded_paths()
    fa.save_json(HUB / "flooded_paths.json", flooded)
    jobs = {"walk_safe_zones": safe_zone_jobs(plan, origins),
            "od_closures_drive": closure_jobs(origins, by_isl, schools, per_area, walk=False),
            "od_closures_walk": closure_jobs(origins, by_isl, schools, per_area, walk=True),
            "od_flooded_drive": closure_jobs(origins, by_isl, schools, per_area, walk=False,
                                             flooded=flooded)}
    led = fa.ledger()
    total = 0.0
    for s in STEPS:
        done = fa.load_json(fa.RAW / f"{s}.json", {"results": {}})["results"]
        todo = [j for j in jobs[s] if j[0] not in done]
        pairs = sum(len(j[3]) for j in todo)
        total += pairs * fa.RATE["od_pair"]
        print(f"[plan] {s}: {len(jobs[s])} requests, {len(todo)} to do, {pairs} OD pairs, "
              f"{round(pairs * fa.RATE['od_pair'], 4)} credits")
    print(f"[plan] all steps: {round(total, 4)} credits; spent so far {fa.spent(led)}; "
          f"after {round(fa.spent(led) + total, 4)} of {fa.BUDGET}")
    print(f"[plan] safe zones: {len(plan)} areas with people without a car in the tsunami "
          f"zone; {sum(1 for p in plan.values() if p['inside'])} already inside a safe zone; "
          f"{sum(1 for p in plan.values() if not p['inside'] and not p['dests'])} with no edge "
          f"within {SAFE_MAX_KM} km")
    if args.estimate:
        return 0

    token = os.environ.get("ARCGIS_TOKEN", "").strip()
    if not token:
        print("ARCGIS_TOKEN is not set: no ArcGIS calls made.", file=sys.stderr)
        return 2
    try:
        for s in STEPS:
            if s not in steps:
                continue
            mode = ("Walking Time", "WalkTime") if "walk" in s else ("Driving Time", "TravelTime")
            run_jobs(s, mode[0], mode[1], jobs[s], token, led, barriers=s != "walk_safe_zones")
    except fa.TokenExpired as e:
        print(f"\nTOKEN EXPIRED or invalid ({e}). Progress saved in data/raw/arcgis/. Refresh "
              f"ARCGIS_TOKEN and run again: it resumes without repeating paid calls.",
              file=sys.stderr)
        return 3
    except fa.OverBudget as e:
        print(f"\nSTOPPED (budget): {e}", file=sys.stderr)
        return 4
    led["total_credits_actual"] = fa.spent(led)
    fa.save_json(fa.CREDITS, led)
    print(f"\nCredits used: {fa.spent(led)} of {fa.BUDGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
