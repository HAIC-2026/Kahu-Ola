#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – DHS ESF-6 AFN planning framework.

Step 1: download open, de-identified public data for all four counties
and build the candidate shelter layer.

- Python 3.9+ standard library only.
- Every record keeps its source URL and fetch date.
- Shelter output is a planning aid, NOT a list of official or open shelters.

Usage:
    python3 scripts/fetch_data.py            # download everything + build shelters
    python3 scripts/fetch_data.py --offline  # rebuild from data/raw only
    python3 scripts/fetch_data.py --only svi nri
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hawaii_time import now_hst  # noqa: E402
from geo import ZoneIndex  # noqa: E402
from fetch_flood_zones import load_cache, lookup  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

HAWAII_BBOX = (-160.6, 18.8, -154.7, 22.4)

# Only verified, public ArcGIS REST layers.
SOURCES = {
    "schools": {
        "url": "https://geodata.hawaii.gov/arcgis/rest/services/Infrastructure/MapServer/7",
        "label": "Hawaii DOE Public Schools (Statewide GIS, Nov 2024)",
        "where": "1=1",
    },
    "tsunami_zone": {
        "url": "https://geodata.hawaii.gov/arcgis/rest/services/Hazards/MapServer/2",
        "label": "Tsunami Evacuation Zones (Statewide GIS)",
        "where": "1=1",
    },
    "tsunami_extreme": {
        "url": "https://geodata.hawaii.gov/arcgis/rest/services/Hazards/MapServer/12",
        "label": "Extreme Tsunami Evacuation Zones (Statewide GIS)",
        "where": "1=1",
    },
    "fema_open_shelters": {
        "url": "https://gis.fema.gov/arcgis/rest/services/NSS/OpenShelters/FeatureServer/0",
        "label": "FEMA Open Shelters (ESF6-SS)",
        "where": "1=1",
        "bbox": HAWAII_BBOX,
    },
    "svi": {
        "url": "https://onemap.cdc.gov/onemapservices/rest/services/SVI/"
               "CDC_ATSDR_Social_Vulnerability_Index_2022_USA/FeatureServer/2",
        "label": "CDC/ATSDR Social Vulnerability Index 2022, census tracts",
        "where": "ST_ABBR='HI'",
    },
    "empower_county": {
        "url": "https://services2.arcgis.com/ZQ4jTQn6k7VPXEwO/arcgis/rest/services/"
               "HHS_emPOWER_REST_Service_Public/FeatureServer/2",
        "label": "HHS emPOWER – electricity-dependent DME, county level",
        "where": "State_FIPS_Code='15'",
    },
}

# FEMA National Risk Index v1.20 (Dec 2025, 2020 tract boundaries): one layer per hazard.
# Field names per hazard code: {CODE}_RISKR (rating), _RISKS (score), _RISKV (value).
NRI_HAZARD_LAYERS = {
    "hurricane": ("HRCN", "Hurricane"),
    "wildfire": ("WFIR", "Wildfire"),
    "tsunami": ("TSUN", "Tsunami"),
    "inland_flood": ("IFLD", "Inland_Flooding"),
    "coastal_flood": ("CFLD", "Coastal_Flooding"),
}
for _hz, (_code, _name) in NRI_HAZARD_LAYERS.items():
    SOURCES[f"nri_{_hz}"] = {
        "url": "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
               f"National_Risk_Index_Census_Tract_{_name}_Hazard_Type_Risk_Index_Rating"
               "/FeatureServer/0",
        "label": f"FEMA National Risk Index v1.20, census tracts – {_name.replace('_', ' ')}",
        "where": "STATEFIPS='15'",
    }

DISCLAIMER = (
    "Candidate facility for planning only. Not an official shelter designation. "
    "Shelters open only when announced by county emergency management."
)

PAGE_SIZE = 1000
USER_AGENT = "HAIC2026-KahuOla-ESF6/0.3 (long@kahuola.org)"

# FIPS county codes for Hawaii. Kalawao is grouped with Maui for planning.
COUNTY_FIPS = {"15001": "Hawaii", "15003": "Honolulu", "15005": "Maui",
               "15007": "Kauai", "15009": "Maui"}
COUNTIES = ("Kauai", "Honolulu", "Maui", "Hawaii")


# ---------------------------------------------------------------- download

def query_url(base: str, where: str, offset: int, bbox=None) -> str:
    params = {
        "where": where,
        "outFields": "*",
        "outSR": "4326",
        "f": "geojson",
        "resultOffset": str(offset),
        "resultRecordCount": str(PAGE_SIZE),
    }
    if bbox:
        params.update({
            "geometry": ",".join(str(v) for v in bbox),
            "geometryType": "esriGeometryEnvelope",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
        })
    return f"{base}/query?{urllib.parse.urlencode(params)}"


def fetch_json(url: str, retries: int = 3) -> dict:
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Failed after {retries} tries: {url}\n{last}")


def download_layer(key: str, src: dict) -> dict:
    features, offset = [], 0
    while True:
        page = fetch_json(query_url(src["url"], src["where"], offset, src.get("bbox")))
        if "error" in page:
            raise RuntimeError(f"{key}: server error {page['error']}")
        batch = page.get("features", [])
        features.extend(batch)
        exceeded = page.get("exceededTransferLimit") or page.get(
            "properties", {}).get("exceededTransferLimit")
        if not batch or (len(batch) < PAGE_SIZE and not exceeded):
            break
        offset += len(batch)
    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "source": src["label"],
            "source_url": src["url"],
            "fetched_at": now_hst(),
            "count": len(features),
        },
    }


def load_layers(keys, offline: bool) -> dict:
    RAW.mkdir(parents=True, exist_ok=True)
    layers = {}
    for key in keys:
        src = SOURCES[key]
        path = RAW / f"{key}.geojson"
        if not offline:
            try:
                fc = download_layer(key, src)
                path.write_text(json.dumps(fc), encoding="utf-8")
                print(f"[ok]   {key}: {fc['metadata']['count']} features")
            except Exception as e:
                print(f"[warn] {key}: download failed ({e})", file=sys.stderr)
        if path.exists():
            layers[key] = json.loads(path.read_text(encoding="utf-8"))
        else:
            layers[key] = None
            print(f"[warn] {key}: no data available", file=sys.stderr)
    return layers


# ---------------------------------------------------------------- county

def county_of(lon: float, lat: float) -> str:
    """Approximate county from island bounding boxes (fallback only)."""
    if lon < -159.0:
        return "Kauai"
    if lon < -157.5:
        return "Honolulu"
    if lat < 20.3 and lon > -156.1:
        return "Hawaii"
    return "Maui"


def county_from_fips(fips: str) -> str:
    return COUNTY_FIPS.get(str(fips)[:5], "")


# ---------------------------------------------------------------- shelters

def prop(p: dict, *names, default=""):
    lower = {k.lower(): v for k, v in p.items()}
    for n in names:
        v = lower.get(n.lower())
        if v not in (None, "", " "):
            return v
    return default


def build_candidates(layers: dict, tracts: ZoneIndex | None = None,
                     flood: dict | None = None) -> dict:
    """flood: cached FEMA flood zones (fetch_flood_zones.load_cache); never fetched here."""
    tsunami = ZoneIndex(layers.get("tsunami_zone"))
    extreme = ZoneIndex(layers.get("tsunami_extreme"))
    out = []

    def add(kind: str, f: dict, meta: dict, name: str, address: str):
        g = f.get("geometry") or {}
        if g.get("type") != "Point":
            return
        lon, lat = g["coordinates"][:2]
        in_t = tsunami.contains(lon, lat)
        in_x = extreme.contains(lon, lat)
        tract = tracts.find(lon, lat) if tracts else None
        fips = str((tract or {}).get("properties", {}).get("FIPS", ""))
        flags = []
        if not name:
            flags.append("missing_name")
        if not tsunami:
            flags.append("tsunami_layer_missing")
        out.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
            "properties": {
                "id": f"{kind}-{len(out) + 1:05d}",
                "name": name or "(unnamed)",
                "facility_type": kind,
                "county": county_from_fips(fips) or county_of(lon, lat),
                "tract_fips": fips,
                "address": address,
                "in_tsunami_zone": in_t,
                "in_extreme_tsunami_zone": in_x,
                "hazard_excluded": in_t or in_x,
                **lookup(flood or {}, lon, lat),
                "needs_review": bool(flags),
                "review_flags": flags,
                "source": meta.get("source", ""),
                "source_url": meta.get("source_url", ""),
                "source_fetched_at": meta.get("fetched_at", ""),
                "disclaimer": DISCLAIMER,
            },
        })

    sch = layers.get("schools")
    if sch:
        for f in sch["features"]:
            p = f.get("properties") or {}
            addr = ", ".join(str(v) for v in (
                prop(p, "address"), prop(p, "city"), prop(p, "zip")) if v)
            add("public_school", f, sch["metadata"], str(prop(p, "sch_name")), addr)

    fema = layers.get("fema_open_shelters")
    if fema:
        for f in fema["features"]:
            p = f.get("properties") or {}
            addr = ", ".join(str(v) for v in (
                prop(p, "address", "address_1"), prop(p, "city"), prop(p, "zip")) if v)
            add("fema_listed_shelter", f, fema["metadata"],
                str(prop(p, "shelter_name", "name")), addr)

    return {
        "type": "FeatureCollection",
        "features": out,
        "metadata": {
            "title": "Hawaiʻi ESF-6 candidate shelter facilities",
            "built_at": now_hst(),
            "disclaimer": DISCLAIMER,
            "sources": [l["metadata"] for k, l in layers.items()
                        if l and k in ("schools", "fema_open_shelters",
                                       "tsunami_zone", "tsunami_extreme")],
        },
    }


def summarize_shelters(fc: dict) -> str:
    rows = {}
    for f in fc["features"]:
        p = f["properties"]
        r = rows.setdefault(p["county"], [0, 0, 0])
        r[0] += 1
        r[1] += p["hazard_excluded"]
        r[2] += p["needs_review"]
    lines = [f"{'County':<10}{'Total':>7}{'In tsunami zone':>17}{'Needs review':>14}"]
    for c in COUNTIES:
        t, x, rv = rows.get(c, [0, 0, 0])
        lines.append(f"{c:<10}{t:>7}{x:>17}{rv:>14}")
    return "\n".join(lines)


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Download open data and build shelter layer")
    ap.add_argument("--offline", action="store_true", help="rebuild from data/raw only")
    ap.add_argument("--only", nargs="*", choices=list(SOURCES), help="limit downloads")
    args = ap.parse_args(argv)

    keys = args.only or list(SOURCES)
    layers = load_layers(keys, args.offline)
    for k in SOURCES:
        if k not in layers:
            p = RAW / f"{k}.geojson"
            layers[k] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None

    OUT.mkdir(parents=True, exist_ok=True)
    tracts = ZoneIndex(layers.get("svi"))
    fc = build_candidates(layers, tracts or None, load_cache())
    out = OUT / "candidates.geojson"
    out.write_text(json.dumps(fc, indent=1), encoding="utf-8")
    print(f"\nWrote {len(fc['features'])} shelter candidates -> {out.relative_to(ROOT)}\n")
    print(summarize_shelters(fc))
    print("\nNext: python3 scripts/build_map.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
