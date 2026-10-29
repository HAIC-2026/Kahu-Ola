#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – summaries of the build-time ArcGIS answers (fetch_arcgis.py).

Reads the raw ArcGIS answers in data/raw/arcgis/ (gitignored, never committed) and writes
data/sources/arcgis_summary.json (committed), the only ArcGIS-derived file the app and the
PDF playbooks read:
  sites       per shelter site: confirmed (2 sources) / needs review / located (ArcGIS) /
              not located, with the distance between the Census and ArcGIS points
  areas       per populated Census area: drive minutes, drive km and walk minutes to every
              known site on the SAME island (rounded), and "outside a 15-minute drive"
  facilities  CMS dialysis facilities, nursing homes and hospitals: display point (4
              decimals, as for sites), island, county, Census area, and the zone it is in for
              each hazard (State tsunami evacuation zone; FEMA flood zone A/AE/V/VE)

Raw answers are not redistributed (Esri terms): only these rounded, derived summaries are.
Without data/raw/arcgis/ the committed summary is kept as is; without the summary the app
and the PDFs fall back to straight-line distances and leave the new layers out.

Usage:  python3 scripts/build_access.py             (queries FEMA flood zones for new points)
        python3 scripts/build_access.py --offline   (rebuild step: cached flood zones only)
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_arcgis as fa  # noqa: E402
from fetch_flood_zones import is_sfha, load_cache, lookup, query_point  # noqa: E402
from geo import ZoneIndex, haversine_km  # noqa: E402
from hawaii_time import now_hst  # noqa: E402
from model_needs import FLOOD, HAZARDS, site_status  # noqa: E402
from raw_inputs import MissingInput, rel, load_geojson, require, require_all_or_none  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = fa.RAW
OUT = ROOT / "data" / "sources" / "arcgis_summary.json"
TSUNAMI = ROOT / "data" / "raw" / "tsunami_zone.geojson"
FLOOD_CACHE = RAW / "facility_flood.json"
DRIVE_LIMIT = 15                       # minutes
TYPE_LABEL = {"dialysis": "Dialysis facility", "nursing_home": "Nursing home",
              "hospital": "Hospital"}
SITE_STATUS_LABEL = {"confirmed": "Confirmed (2 sources)", "needs_review": "Needs review",
                     "confirmed_doe_arcgis": "Confirmed (DOE + ArcGIS)",
                     "confirmed_doe_census": "Confirmed (DOE + Census)",
                     "verified_manually": "Verified manually",
                     "located_arcgis": "Located (ArcGIS)", "single_source": "1 source",
                     "not_located": "Not located"}
SOURCE_TEXT = ("Site locations: U.S. Census Geocoder, checked against Esri ArcGIS World "
               "Geocoder. Travel times: Esri ArcGIS routing, normal traffic.")
ATTRIBUTION = "Powered by Esri. Geocoding and routing: Esri ArcGIS Location Services."
TIMES_NOTE = "normal traffic, not disaster conditions"
NO_WALK = "no walk time: over 12 km"
REQUIRED = ("geocode_sites.json", "geocode_facilities.json", "od_drive.json",
            "od_walk_near.json", "od_schools.json", "cms_facilities.json")
DOE_CHECKS = ROOT / "data" / "sources" / "doe_school_checks.csv"
DOE_FIELDS = ["site_key", "doe_school", "doe_address", "doe_lon", "doe_lat", "census_status",
              "census_lon", "census_lat", "census_matched_address", "queried_at"]
SCHOOLS_RAW = ROOT / "data" / "raw" / "schools.geojson"
SITE_FLOOD_CACHE = RAW / "site_flood.json"
REVIEW_DOC = ROOT / "docs" / "site_review.md"
CONFIRM_M = fa.CONFIRM_M
NO_ACTIVATED = "No 2026 activated site within a 15-minute drive (normal traffic)"
NOT_NO_SHELTER = ("This is not a statement that the area has no shelter: counties designate "
                  "and open shelters for each event, and many public buildings are not on "
                  "the 2026 list.")
WALK_KM = fa.WALK_KM


KEEP_CAPS = {"SHC", "LLC", "USRC", "FMC", "DCI", "II", "III", "IV", "LTC", "ICF", "SNF", "HI", "UH"}


def tidy_name(name: str) -> str:
    """CMS names are ALL CAPS: 'KAPIOLANI MEDICAL CENTER' -> 'Kapiolani Medical Center'."""
    return " ".join(w if w.strip(".,()") in KEEP_CAPS else
                    "-".join(x.capitalize() for x in w.split("-")) for w in name.split())


def r1(v) -> float | None:
    return None if v is None else round(float(v), 1)


# ---------------------------------------------------------------- sites

def load_doe_checks(path: Path = DOE_CHECKS) -> dict:
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["site_key"]: r for r in csv.DictReader(fh)}


def doe_checks(offline: bool = False) -> dict:
    """School sites (point from the DOE schools layer): the DOE street address, geocoded
    with the free U.S. Census Geocoder, as an independent check of the DOE point. Cached in
    data/sources/doe_school_checks.csv; offline runs read the cache only."""
    from build_shelters import match_school
    from geocode_shelters import census_lookup, to_query
    cache = load_doe_checks()
    schools = load_geojson(SCHOOLS_RAW, "Hawaiʻi DOE schools")["features"]
    changed = False
    for s in fa.load_sites():
        if s["method"] != "doe_school_match" or s["key"] in cache or offline:
            continue
        f = match_school({"name": s["name"], "county": s["county"]}, schools)
        if not f:
            continue
        p = f["properties"]
        addr = f"{p['address']}, {p['city']}, HI {p['zip']}"
        res = census_lookup(to_query(addr))
        lon, lat = f["geometry"]["coordinates"][:2]
        cache[s["key"]] = {"site_key": s["key"], "doe_school": p["sch_name"], "doe_address": addr,
                           "doe_lon": round(lon, 6), "doe_lat": round(lat, 6),
                           "census_status": res["status"], "census_lon": res.get("lon", ""),
                           "census_lat": res.get("lat", ""),
                           "census_matched_address": res.get("matched_address", ""),
                           "queried_at": now_hst()}
        changed = True
    if changed:
        with open(DOE_CHECKS, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=DOE_FIELDS)
            w.writeheader()
            w.writerows(cache[k] for k in sorted(cache))
    return cache


def doe_status(site: dict, p: dict, doe: dict | None) -> dict:
    """Third source for school sites. The site point IS the DOE point; it is confirmed by
    ArcGIS (when the county release gave a street address, so ArcGIS had a real query) or
    by the Census geocode of the DOE street address, whichever agrees within 300 m."""
    if not doe:
        return {}
    d_arc = p.get("distance_m") if site["address"].strip() else None
    d_cen = None
    if doe.get("census_status") == "match":
        d_cen = round(haversine_km(float(doe["doe_lon"]), float(doe["doe_lat"]),
                                   float(doe["census_lon"]), float(doe["census_lat"])) * 1000)
    out = {"doe_school": doe["doe_school"], "doe_address": doe["doe_address"],
           "doe_census_distance_m": d_cen, "arcgis_query_valid": d_arc is not None}
    if d_arc is not None and d_arc <= CONFIRM_M:
        out["status"] = "confirmed_doe_arcgis"
    elif d_cen is not None and d_cen <= CONFIRM_M:
        out["status"] = "confirmed_doe_census"
    return out


def census_point(address: str) -> tuple | None:
    with open(ROOT / "data" / "sources" / "geocodes.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["address"].strip() == address.strip() and r["status"] == "match":
                return float(r["lon"]), float(r["lat"]), r["matched_address"], r["method"]
    return None


def review_distance(o: dict) -> int | None:
    c = census_point(o["address"])
    return round(haversine_km(c[0], c[1], float(o["lon"]), float(o["lat"])) * 1000) if c else None


def site_checks(island_of, offline: bool = False) -> dict:
    """Per site key: location check. A point placed earlier by ArcGIS itself is not a
    second source, so it is classified as if the Census point were missing."""
    sites = fa.load_sites()
    for s in sites:
        if s["method"] == "arcgis_world_geocoder":
            s["point"] = None
    by_key = {s["key"]: s for s in sites}
    esri = fa.load_json(RAW / "geocode_sites.json", {})
    doe = doe_checks(offline)
    from build_shelters import load_overrides
    overrides = load_overrides()
    out = {}
    for p in fa.site_points(sites, esri, island_of):
        e = p.get("esri") or {}
        row = {"status": p["status"], "distance_m": p.get("distance_m"), "address": p["address"],
               "esri_score": e.get("score"), "esri_match_type": e.get("addr_type", "")}
        if by_key[p["key"]]["method"] == "doe_school_match":
            row.update(doe_status(by_key[p["key"]], p, doe.get(p["key"])))
        o = overrides.get(p["key"])
        if o:           # the point is the one the team verified; distance is to the Census point
            row.update(status="verified_manually", verified=o["verified"], evidence=o["evidence"],
                       follow_up=o["follow_up"], point_source=o["point_source"],
                       distance_m=review_distance(o))
        row["label"] = SITE_STATUS_LABEL[row["status"]] + (
            f" ({row['verified'].removeprefix('verified ')})"
            if row["status"] == "verified_manually" else "")
        if p["status"] == "located_arcgis":
            row.update(lon=round(p["lon"], 4), lat=round(p["lat"], 4), island=p["island"])
        if p.get("reason"):
            row["reason"] = p["reason"]
        out[p["key"]] = row
    return out


def footprints() -> dict:
    """(county, hazard) -> Census areas in the hazard footprint (model_needs.py)."""
    foot = {}
    with open(fa.NEEDS_BY_TRACT, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            foot.setdefault((r["county"], r["hazard"]), set()).add(r["tract_fips"])
    return foot


def site_reviews(checks: dict, offline: bool) -> dict:
    """Non-school sites that need review: both candidate points and the hazard statuses
    that would change between them. The current (Census or manual) point is kept."""
    tsunami = ZoneIndex(fa.load_json(TSUNAMI, None))
    tracts = ZoneIndex(fa.load_json(fa.AFN, None))
    foot = footprints()
    esri = fa.load_json(RAW / "geocode_sites.json", {})
    geocodes = {}
    with open(ROOT / "data" / "sources" / "geocodes.csv", newline="", encoding="utf-8") as fh:
        geocodes = {r["address"].strip(): r for r in csv.DictReader(fh)}
    shelters = {f["properties"]["name"] + "|" + f["properties"]["county"]: f
                for f in fa.load_json(fa.SHELTERS, {"features": []})["features"]}
    cache = fa.load_json(SITE_FLOOD_CACHE, {})
    out = {}
    try:
        for key, c in checks.items():
            if c["status"] not in ("needs_review", "verified_manually"):
                continue
            f = shelters[key]
            prop, (lon, lat) = f["properties"], f["geometry"]["coordinates"][:2]
            e = esri[key]
            here = {**prop}
            method = prop["location_method"]
            if c["status"] == "verified_manually":      # candidate 1 is the Census point
                lon, lat, _m, method = census_point(prop["address"])
                here = {"in_tsunami_zone": tsunami.contains(lon, lat),
                        "fld_zone": lookup(load_cache(), lon, lat)["fld_zone"],
                        "tract_fips": ((tracts.find(lon, lat) or {}).get("properties")
                                       or {}).get("tract_fips", "")}
                here["in_sfha"] = is_sfha(here["fld_zone"])
            there = {"in_tsunami_zone": tsunami.contains(e["lon"], e["lat"]),
                     "fld_zone": flood_zone(e["lon"], e["lat"], cache, offline),
                     "tract_fips": ((tracts.find(e["lon"], e["lat"]) or {}).get("properties")
                                    or {}).get("tract_fips", "")}
            there["in_sfha"] = is_sfha(there["fld_zone"])
            g = geocodes.get(prop["address"].strip(), {})
            changes = {}
            for h in HAZARDS:
                fp = foot.get((prop["county"], h), set())
                a, b = site_status(here, h, fp), site_status(there, h, fp)
                if a[0] != b[0]:
                    changes[h] = [a[0], b[0]]
            out[key] = {
                "distance_m": c["distance_m"],
                "current": {"lon": round(lon, 6), "lat": round(lat, 6),
                            "method": method,
                            "matched_address": g.get("matched_address", ""),
                            "in_tsunami_zone": bool(here.get("in_tsunami_zone")),
                            "fld_zone": here.get("fld_zone")},
                **({"resolution": {"chosen": "arcgis", "verified": c["verified"],
                                   "evidence": c["evidence"], "follow_up": c["follow_up"]}}
                   if c["status"] == "verified_manually" else {}),
                "arcgis": {"lon": round(e["lon"], 6), "lat": round(e["lat"], 6),
                           "matched_address": e.get("match_addr", ""), "score": e.get("score"),
                           "match_type": e.get("addr_type", ""),
                           "in_tsunami_zone": there["in_tsunami_zone"],
                           "fld_zone": there["fld_zone"]},
                "status_changes": changes}
    finally:
        fa.save_json(SITE_FLOOD_CACHE, cache)
    return out


# ---------------------------------------------------------------- travel times

def parse_od(path: Path) -> dict:
    """{area: {site_key: [minutes, km]}} from the sparse OD matrices."""
    data = fa.load_json(path, {"results": {}})
    out = {}
    for job in data["results"].values():
        m = job.get("matrix") or {}
        names = m.get("costAttributeNames") or []
        t_i, k_i = (0, 1) if not names or names[0] != "Kilometers" else (1, 0)
        for oi, row in m.items():
            if not oi.isdigit():
                continue
            area = job["origins"][int(oi) - 1]
            for di, cost in row.items():
                site = job["destinations"][int(di) - 1]
                out.setdefault(area, {})[site] = [cost[t_i], cost[k_i]]
    return out


def site_usable() -> dict:
    """site key -> hazards the 2026 activated site is usable for (model_needs.site_status)."""
    foot = footprints()
    out = {}
    for f in fa.load_json(fa.SHELTERS, {"features": []})["features"]:
        p = f["properties"]
        if f.get("geometry"):
            out[f"{p['name']}|{p['county']}"] = [
                h for h in HAZARDS if site_status(p, h, foot.get((p["county"], h), set()))[0] == "ok"]
    return out


def area_times(origins: list, island_of) -> dict:
    """Per area: times to every activated site on the island, and per hazard the shortest
    drive to (1) a 2026 activated site usable for it and (2) that or a DOE candidate school
    usable for it (the 5 nearest per hazard by straight line)."""
    drive, walk = parse_od(RAW / "od_drive.json"), parse_od(RAW / "od_walk_near.json")
    moved = fa.refreshed_sites()            # corrected points: times from the refresh runs only
    for table, path in ((drive, "od_drive_refresh.json"), (walk, "od_walk_refresh.json")):
        for row in table.values():
            for k in moved:
                row.pop(k, None)
        for area, row in parse_od(RAW / path).items():
            table.setdefault(area, {}).update(row)
    school_drive = parse_od(RAW / "od_schools.json")
    usable = site_usable()
    school_ok = {s["id"]: s["usable"] for s in fa.candidate_schools(island_of)}
    out = {}
    for o in origins:
        d = drive.get(o["id"], {})
        sites = {k: [r1(v[0]), r1(v[1]), r1(walk.get(o["id"], {}).get(k, [None])[0])]
                 for k, v in sorted(d.items())}
        hz = {}
        for h in HAZARDS:
            a = min((v[0] for k, v in sites.items() if v[0] is not None and h in usable.get(k, [])),
                    default=None)
            b = min((v[0] for k, v in school_drive.get(o["id"], {}).items()
                     if v[0] is not None and h in school_ok.get(k, [])), default=None)
            both = min((x for x in (a, b) if x is not None), default=None)
            hz[h] = [a, r1(both)]
        out[o["id"]] = {"island": o["island"], "sites": sites, "drive_by_hazard": hz}
    return out


def outside(v: float | None) -> bool:
    return v is None or v > DRIVE_LIMIT


# ---------------------------------------------------------------- care facilities

def flood_zone(lon: float, lat: float, cache: dict, offline: bool) -> str | None:
    k = f"{lon:.4f},{lat:.4f}"
    if k not in cache and not offline:
        cache[k] = query_point(lon, lat)[0]
    return cache.get(k)


def hazard_zones(p: dict) -> dict:
    """hazard -> zone text when the facility is inside that hazard's zone, else ""
    (same screens as shelter sites: tsunami zone; FEMA Special Flood Hazard Area, A/AE/V/VE).
    FEMA zone D (flood risk not mapped) is not a hazard zone: callers count it separately."""
    out = {}
    for h in HAZARDS:
        st, _why = site_status(p, h)
        if h == "tsunami" and st == "exclude":
            out[h] = "Tsunami evacuation zone"
        elif h in FLOOD and st == "check":
            out[h] = f"FEMA flood zone {p['fld_zone']}"
        else:
            out[h] = ""
    return out


def facilities(island_of, offline: bool) -> list:
    tsunami = ZoneIndex(load_geojson(TSUNAMI, "State tsunami evacuation zones"))
    tracts = ZoneIndex(load_geojson(fa.AFN, "Census areas (build_map.py)"))
    if offline:          # offline runs read flood zones from the cache only
        require(FLOOD_CACHE, "cached FEMA flood zones for care facilities")
    geo = fa.load_json(RAW / "geocode_facilities.json", {})
    cache = fa.load_json(FLOOD_CACHE, {})
    out = []
    try:
        for f in fa.load_facilities():
            g = geo.get(f["id"]) or {}
            if g.get("status") != "match":
                continue
            lon, lat = round(g["lon"], 4), round(g["lat"], 4)
            island = island_of(lon, lat)
            tract = ((tracts.find(lon, lat) or {}).get("properties") or {})
            zone = flood_zone(lon, lat, cache, offline)
            p = {"in_tsunami_zone": tsunami.contains(lon, lat), "fld_zone": zone,
                 "in_sfha": is_sfha(zone)}
            out.append({"id": f["id"], "type": f["type"], "type_label": TYPE_LABEL[f["type"]],
                        "name": tidy_name(f["name"]),
                        "address": tidy_name(f"{f['address']}, {f['city']}"),
                        "lon": lon, "lat": lat, "island": island,
                        "county": fa.ISLE_COUNTY.get(island) or tract.get("county", ""),
                        "tract": tract.get("tract_fips", ""),
                        "in_tsunami_zone": p["in_tsunami_zone"], "fld_zone": zone,
                        "zones": hazard_zones(p), "source": f["source"],
                        "source_url": f["source_url"]})
    finally:
        fa.save_json(FLOOD_CACHE, cache)
    return sorted(out, key=lambda x: (x["county"], x["type"], x["name"]))


# ---------------------------------------------------------------- summary

def summarize(offline: bool = False) -> dict | None:
    """None when data/raw/arcgis/ is absent (documented fallback: the committed summary is
    kept, see main). A partial or empty download, or a missing coastline, tsunami or
    schools layer, raises MissingInput."""
    if not require_all_or_none(RAW, REQUIRED, "raw ArcGIS answers"):
        return None
    coast = ZoneIndex(load_geojson(fa.COAST, "State coastline (island outlines)"))
    from build_islands import island_of as _island_of
    island_of = lambda x, y: _island_of(coast, x, y)  # noqa: E731
    led = fa.load_json(fa.CREDITS, {"steps": {}})
    sa = led["steps"].get("service_areas", {})
    return {
        "meta": {"source_text": SOURCE_TEXT, "attribution": ATTRIBUTION,
                 "times_note": TIMES_NOTE, "no_walk": NO_WALK, "drive_limit_min": DRIVE_LIMIT,
                 "credits_total": fa.spent(led) if led["steps"] else None,
                 "service_areas": sa.get("note", ""),
                 "no_activated": NO_ACTIVATED, "not_no_shelter": NOT_NO_SHELTER,
                 "outside_15_method": "Drive-time matrix, per hazard: shortest drive from "
                                      "the area's land point to a 2026 activated site usable "
                                      "for that hazard on the same island; scenario 2 adds "
                                      "the 5 nearest DOE candidate schools usable for it.",
                 "redistribution": "Raw ArcGIS answers are not committed; this file holds "
                                   "rounded, derived summaries only."},
        "sites": (checks := site_checks(island_of, offline)),
        "site_reviews": site_reviews(checks, offline),
        "areas": area_times(fa.populated_origins(), island_of),
        "facilities": facilities(island_of, offline),
    }


def load(path: Path = OUT) -> dict | None:
    """The committed summary, or None (callers fall back to straight-line behaviour)."""
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def located_points(path: Path = OUT) -> dict:
    """address -> (lon, lat, method) for sites located by ArcGIS only (build_shelters.py)."""
    s = load(path) or {}
    return {v["address"].strip(): (v["lon"], v["lat"], "arcgis_world_geocoder")
            for v in s.get("sites", {}).values() if v["status"] == "located_arcgis"}


def area_counties() -> dict:
    with open(fa.ISLANDS, newline="", encoding="utf-8") as fh:
        return {r["id"]: r["county"] for r in csv.DictReader(fh) if r["kind"] == "area"}


def outside_counts(s: dict, counties: dict | None = None) -> dict:
    """(county, hazard) -> [areas outside scenario 1, outside scenario 2, populated areas]."""
    counties = counties or area_counties()
    out = {}
    for a, v in s["areas"].items():
        for h, (d1, d2) in v["drive_by_hazard"].items():
            row = out.setdefault((counties.get(a, "?"), h), [0, 0, 0])
            row[0] += outside(d1)
            row[1] += outside(d2)
            row[2] += 1
    return out


def report(s: dict) -> str:
    from collections import Counter
    st = Counter(v["status"] for v in s["sites"].values())
    out = [f"sites: {dict(st)}"]
    for k, v in s["sites"].items():
        if v["status"] in ("needs_review", "confirmed_doe_census", "verified_manually"):
            out.append(f"  {v['label']}: {k} (ArcGIS {v['distance_m']} m"
                       + (f"; DOE vs Census {v['doe_census_distance_m']} m" if "doe_school" in v else "")
                       + ")")
    for k, r in s["site_reviews"].items():
        out.append(f"  review {k}: status changes if moved to ArcGIS point: {r['status_changes'] or 'none'}")
    out.append(f"areas outside a {DRIVE_LIMIT}-minute drive (activated / + candidate schools / areas):")
    for (c, h), v in sorted(outside_counts(s).items()):
        out.append(f"  {c:<9} {h:<14} {v[0]:>4} / {v[1]:>4} / {v[2]:>4}")
    fz = Counter((f["county"], h) for f in s["facilities"] for h, z in f["zones"].items() if z)
    out.append(f"facilities: {len(s['facilities'])}; in hazard zones: "
               + ", ".join(f"{c} {h} {n}" for (c, h), n in sorted(fz.items())))
    return "\n".join(out)


STATUS_WORDS = {"ok": "usable", "exclude": "excluded (tsunami zone)", "check": "check flood zone",
                "check (tract-level)": "check flood zone (tract level)",
                "undetermined": "flood risk not mapped (zone D)"}


def review_doc(s: dict) -> str:
    """docs/site_review.md: the non-school sites whose two points are > 300 m apart."""
    def zone(p):
        return (("inside" if p["in_tsunami_zone"] else "outside") + " tsunami evacuation zone; "
                f"FEMA flood zone {p['fld_zone'] or 'not available'}")
    lines = ["# Shelter sites to review: two candidate points", "",
             "Generated by `scripts/build_access.py` from `data/sources/arcgis_summary.json`. "
             "For each site the county address was located twice: by the U.S. Census Geocoder "
             "(or by hand, where noted) and by the Esri ArcGIS World Geocoder. The two points "
             "are more than 300 m apart. **The current point is kept until the team confirms "
             "the right one.** Hazard statuses use the same rules as the plan (tsunami "
             "evacuation zone; FEMA flood zone, State DFIRM).", ""]
    method = {"census_onelineaddress": "U.S. Census Geocoder", "manual": "entered by hand",
              "doe_school_match": "DOE schools layer"}
    reviews = sorted(s["site_reviews"].items(), key=lambda kv: ("resolution" in kv[1], kv[0]))
    resolved_header = False
    for key, r in reviews:
        cur, arc = r["current"], r["arcgis"]
        name, county = key.split("|")
        if "resolution" in r and not resolved_header:
            lines += ["# Resolved", "", "Sites whose point the team has verified. The chosen "
                      "point is now the site's point, and every hazard status was re-run.", ""]
            resolved_header = True
        title = f"## {name} ({county})"
        if "resolution" in r:
            res = r["resolution"]
            lines += [title, "",
                      f"**Resolved: the ArcGIS point is correct – verified manually ({res['verified']}).** "
                      f"{res['evidence']} The site now uses the ArcGIS point.", "",
                      f"**Follow-up:** {res['follow_up']}.", ""]
            title = None
        lines += ([title, ""] if title else []) + [
                  f"Address in the county release: {s['sites'][key]['address']}. "
                  f"Distance between the two points: **{r['distance_m']:,} m**.", "",
                  ("| | Census point (not used) | ArcGIS point (used) |" if "resolution" in r
                   else "| | Current point (kept) | ArcGIS point |"), "|---|---|---|",
                  f"| Source | {method.get(cur['method'], cur['method'])} | Esri ArcGIS World Geocoder |",
                  f"| Latitude, longitude | {cur['lat']}, {cur['lon']} | {arc['lat']}, {arc['lon']} |",
                  f"| Matched address | {cur['matched_address'] or '–'} | {arc['matched_address']} |",
                  f"| Score / match type | – (Census Geocoder gives no score) | {arc['score']} / {arc['match_type']} |",
                  f"| Zones | {zone(cur)} | {zone(arc)} |", ""]
        if r["status_changes"] and "resolution" in r:
            lines.append("**Hazard statuses that changed (Census point → ArcGIS point):**")
            lines += [f"- {h.replace('_', ' ')}: {STATUS_WORDS.get(a, a)} → {STATUS_WORDS.get(b, b)}"
                      for h, (a, b) in r["status_changes"].items()]
        elif r["status_changes"]:
            lines.append("**Hazard statuses that would change if the ArcGIS point were used:**")
            lines += [f"- {h.replace('_', ' ')}: {STATUS_WORDS.get(a, a)} → {STATUS_WORDS.get(b, b)}"
                      for h, (a, b) in r["status_changes"].items()]
        else:
            lines.append("No hazard status would change between the two points.")
        lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Summaries of the build-time ArcGIS answers")
    ap.add_argument("--offline", action="store_true", help="cached flood zones only")
    args = ap.parse_args(argv)
    try:
        s = summarize(args.offline)
    except MissingInput as e:
        print(e, file=sys.stderr)
        return 1
    if s is None:      # paid answers are not re-fetched: the committed summary is the fallback
        if not load(OUT):
            print(f"Build stopped: no raw ArcGIS answers in {rel(RAW)} and no "
                  f"committed {rel(OUT)}.", file=sys.stderr)
            return 1
        print(f"No raw ArcGIS answers in {rel(RAW)}: "
              f"keeping the committed {rel(OUT)}")
        return 0
    REVIEW_DOC.write_text(review_doc(s), encoding="utf-8")
    OUT.write_text(json.dumps(s, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")
    print(report(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
