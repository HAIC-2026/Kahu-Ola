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
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fetch_arcgis as fa  # noqa: E402
from fetch_flood_zones import is_sfha, query_point  # noqa: E402
from geo import ZoneIndex  # noqa: E402
from model_needs import FLOOD, HAZARDS, site_status  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = fa.RAW
OUT = ROOT / "data" / "sources" / "arcgis_summary.json"
TSUNAMI = ROOT / "data" / "raw" / "tsunami_zone.geojson"
FLOOD_CACHE = RAW / "facility_flood.json"
DRIVE_LIMIT = 15                       # minutes
TYPE_LABEL = {"dialysis": "Dialysis facility", "nursing_home": "Nursing home",
              "hospital": "Hospital"}
SITE_STATUS_LABEL = {"confirmed": "Confirmed (2 sources)", "needs_review": "Needs review",
                     "located_arcgis": "Located (ArcGIS)", "single_source": "1 source",
                     "not_located": "Not located"}
SOURCE_TEXT = ("Site locations: U.S. Census Geocoder, checked against Esri ArcGIS World "
               "Geocoder. Travel times: Esri ArcGIS routing, normal traffic.")
ATTRIBUTION = "Powered by Esri. Geocoding and routing: Esri ArcGIS Location Services."
TIMES_NOTE = "normal traffic, not disaster conditions"
NO_WALK = "no walk time: over 12 km"
REQUIRED = ("geocode_sites.json", "geocode_facilities.json", "od_drive.json",
            "od_walk_near.json", "cms_facilities.json")
WALK_KM = fa.WALK_KM


KEEP_CAPS = {"SHC", "LLC", "USRC", "FMC", "DCI", "II", "III", "IV", "LTC", "ICF", "SNF", "HI", "UH"}


def tidy_name(name: str) -> str:
    """CMS names are ALL CAPS: 'KAPIOLANI MEDICAL CENTER' -> 'Kapiolani Medical Center'."""
    return " ".join(w if w.strip(".,()") in KEEP_CAPS else
                    "-".join(x.capitalize() for x in w.split("-")) for w in name.split())


def r1(v) -> float | None:
    return None if v is None else round(float(v), 1)


# ---------------------------------------------------------------- sites

def site_checks(island_of) -> dict:
    """Per site key: location check. A point placed earlier by ArcGIS itself is not a
    second source, so it is classified as if the Census point were missing."""
    sites = fa.load_sites()
    for s in sites:
        if s["method"] == "arcgis_world_geocoder":
            s["point"] = None
    esri = fa.load_json(RAW / "geocode_sites.json", {})
    out = {}
    for p in fa.site_points(sites, esri, island_of):
        e = p.get("esri") or {}
        row = {"status": p["status"], "label": SITE_STATUS_LABEL[p["status"]],
               "distance_m": p.get("distance_m"), "address": p["address"],
               "esri_score": e.get("score"), "esri_match_type": e.get("addr_type", "")}
        if p["status"] == "located_arcgis":
            row.update(lon=round(p["lon"], 4), lat=round(p["lat"], 4), island=p["island"])
        if p.get("reason"):
            row["reason"] = p["reason"]
        out[p["key"]] = row
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


def area_times(origins: list) -> dict:
    drive, walk = parse_od(RAW / "od_drive.json"), parse_od(RAW / "od_walk_near.json")
    out = {}
    for o in origins:
        d = drive.get(o["id"], {})
        sites = {k: [r1(v[0]), r1(v[1]), r1(walk.get(o["id"], {}).get(k, [None])[0])]
                 for k, v in sorted(d.items())}
        best = min((v[0] for v in sites.values() if v[0] is not None), default=None)
        out[o["id"]] = {"island": o["island"], "sites": sites, "min_drive": best,
                        "outside_15": best is None or best > DRIVE_LIMIT}
    return out


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
    tsunami = ZoneIndex(fa.load_json(TSUNAMI, None))
    tracts = ZoneIndex(fa.load_json(fa.AFN, None))
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
    if not all((RAW / f).exists() for f in REQUIRED):
        return None
    coast = ZoneIndex(fa.load_json(fa.COAST, None))
    from build_islands import island_of as _island_of
    island_of = (lambda x, y: _island_of(coast, x, y)) if coast else (lambda x, y: "")
    led = fa.load_json(fa.CREDITS, {"steps": {}})
    sa = led["steps"].get("service_areas", {})
    return {
        "meta": {"source_text": SOURCE_TEXT, "attribution": ATTRIBUTION,
                 "times_note": TIMES_NOTE, "no_walk": NO_WALK, "drive_limit_min": DRIVE_LIMIT,
                 "credits_total": fa.spent(led) if led["steps"] else None,
                 "service_areas": sa.get("note", ""),
                 "outside_15_method": "Drive-time matrix: no known site within "
                                      f"{DRIVE_LIMIT} minutes' drive on the same island.",
                 "redistribution": "Raw ArcGIS answers are not committed; this file holds "
                                   "rounded, derived summaries only."},
        "sites": site_checks(island_of),
        "areas": area_times(fa.populated_origins()),
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


def report(s: dict) -> str:
    from collections import Counter
    st = Counter(v["status"] for v in s["sites"].values())
    out = [f"sites: {dict(st)}"]
    for k, v in s["sites"].items():
        if v["status"] == "needs_review":
            out.append(f"  needs review: {k} ({v['distance_m']} m apart)")
    by = Counter()
    county = {r["id"]: r["county"] for r in __import__("csv").DictReader(
        open(fa.ISLANDS, encoding="utf-8")) if r["kind"] == "area"}
    for a, v in s["areas"].items():
        if v["outside_15"]:
            by[county.get(a, "?")] += 1
    out.append(f"areas outside a {DRIVE_LIMIT}-minute drive: {dict(by)} of {len(s['areas'])}")
    fz = Counter((f["county"], h) for f in s["facilities"] for h, z in f["zones"].items() if z)
    out.append(f"facilities: {len(s['facilities'])}; in hazard zones: "
               + ", ".join(f"{c} {h} {n}" for (c, h), n in sorted(fz.items())))
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Summaries of the build-time ArcGIS answers")
    ap.add_argument("--offline", action="store_true", help="cached flood zones only")
    args = ap.parse_args(argv)
    s = summarize(args.offline)
    if s is None:
        print(f"No raw ArcGIS answers in {RAW.relative_to(ROOT)}: "
              + (f"keeping {OUT.relative_to(ROOT)}" if OUT.exists() else
                 "no summary; app and PDFs use straight-line distances"))
        return 0
    OUT.write_text(json.dumps(s, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                   encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size / 1024:.0f} KB)")
    print(report(s))
    return 0


if __name__ == "__main__":
    sys.exit(main())
