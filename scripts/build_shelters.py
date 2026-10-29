#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – "Map commonly used shelters" (DHS objective).

Hawaiʻi has no standing public shelter list: counties announce sites when they
open. This script turns those announcements (data/sources/county_shelter_activations.csv,
one row per site per event, each with its source URL) into one statewide layer:

  * one record per site, with how many 2026 events it was opened for
  * each county's own site type kept as-is (shelter / refuge area / evacuation point)
  * located by matching to the DOE public-schools layer, else by the cached
    U.S. Census geocode of its address (scripts/geocode_shelters.py);
    anything still unlocated is flagged needs_geocode
  * hazard context from the MAP layer (tract, NRI flood ratings, tsunami zone)
  * FEMA flood zone at the site (fld_zone, in_sfha) from the cache written by
    scripts/fetch_flood_zones.py; no network calls here

Usage:  python3 scripts/build_shelters.py   (after fetch_data.py and build_map.py)
"""
from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hawaii_time import now_hst  # noqa: E402
from geo import ZoneIndex  # noqa: E402
from fetch_data import COUNTIES, county_of  # noqa: E402
from fetch_flood_zones import load_cache, lookup  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "sources" / "county_shelter_activations.csv"
GEOCODES = ROOT / "data" / "sources" / "geocodes.csv"
OVERRIDES = ROOT / "data" / "sources" / "site_point_overrides.csv"
VERIFIED = "verified_manually"
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

OFFICIAL_DOMAINS = ("mauicounty.gov", "honolulu.gov", "kauai.gov", "hawaiicounty.gov",
                    "hawaii.gov")
STOPWORDS = {"school", "gym", "gymnasium", "cafeteria", "and", "the", "of"}
DISCLAIMER = ("Sites a county has opened in past events. Not every site opens in every "
              "emergency; always follow current county announcements.")


def norm_tokens(name: str) -> set:
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("ʻ", "").replace("‘", "").replace("’", "").replace("'", "")
    words = re.findall(r"[a-z0-9]+", s.lower())
    return {w for w in words if w not in STOPWORDS}


def is_official(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS)


def load_activations(path: Path = SRC) -> list:
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("name")]


def group_sites(rows: list) -> list:
    sites = {}
    for r in rows:
        key = (r["county"], frozenset(norm_tokens(r["name"])))
        s = sites.setdefault(key, {
            "county": r["county"], "name": r["name"], "address": "",
            "site_types": set(), "events": [], "pets": set(), "sources": set(),
        })
        s["address"] = s["address"] or r.get("address", "")
        s["site_types"].add(r["site_type"])
        s["events"].append((r["source_date"], r["event"]))
        if r.get("pets") and r["pets"] != "unknown":
            s["pets"].add(r["pets"])
        s["sources"].add(r["source_url"])
    return list(sites.values())


def match_school(site: dict, schools: list):
    """Return the DOE school feature whose name tokens are all in the site name,
    in the same county. Longest match wins."""
    want = norm_tokens(site["name"])
    best, best_len = None, 0
    for f in schools:
        p = f.get("properties") or {}
        g = f.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        toks = norm_tokens(str(p.get("sch_name", "")))
        if not toks or not toks <= want:
            continue
        if county_of(*g["coordinates"][:2]) != site["county"]:
            continue
        if len(toks) > best_len:
            best, best_len = f, len(toks)
    return best


def load_overrides(path: Path = OVERRIDES) -> dict:
    """site key -> row: points the team verified by hand (they win over every geocode)."""
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["site_key"]: r for r in csv.DictReader(fh)}


def location_note(o: dict) -> str:
    return (f"{o['point_source']}; {o['verified']} ({o['evidence']}) "
            f"Follow-up: {o['follow_up']}.")


def load_geocodes(path: Path = GEOCODES) -> dict:
    """address -> (lon, lat, method) for usable rows (Census match or manual entry)."""
    if not path.exists():
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            try:
                lon, lat = float(r["lon"]), float(r["lat"])
            except (TypeError, ValueError, KeyError):
                continue
            if r.get("status") == "match" or r.get("method") == "manual":
                out[r["address"].strip()] = (lon, lat, r.get("method") or "census")
    return out


def build(rows: list, schools: list, tracts=None, tsunami=None,
          geocodes: dict | None = None, flood: dict | None = None) -> dict:
    t_index = ZoneIndex(tsunami)
    tract_index = ZoneIndex(tracts)
    feats = []
    for s in group_sites(rows):
        hit = match_school(s, schools)
        geom, method = (hit["geometry"], "doe_school_match") if hit else (None, "")
        gc = (geocodes or {}).get(s["address"].strip()) if not hit else None
        if gc:
            geom = {"type": "Point", "coordinates": [gc[0], gc[1]]}
            method = gc[2]
        props = {
            "name": s["name"],
            "county": s["county"],
            "address": s["address"],
            "site_type": "/".join(sorted(s["site_types"])),
            "times_opened_2026": len(s["events"]),
            "events": "; ".join(f"{d} {e}" for d, e in sorted(s["events"])),
            "last_opened": max(d for d, _ in s["events"]),
            "pets": "/".join(sorted(s["pets"])) or "unknown",
            "official_source": any(is_official(u) for u in s["sources"]),
            "sources": sorted(s["sources"]),
            "location_method": method,
            "needs_geocode": geom is None,
            "capacity": None,          # not published; to be filled from county plans
            "disclaimer": DISCLAIMER,
            "fld_zone": None,
            "in_sfha": None,
        }
        if geom:
            lon, lat = geom["coordinates"][:2]
            props["in_tsunami_zone"] = t_index.contains(lon, lat)
            tract = tract_index.find(lon, lat)
            tp = (tract or {}).get("properties", {})
            props["tract_fips"] = tp.get("tract_fips", "")
            props["nri_inland_flood_rating"] = tp.get("nri_inland_flood_rating", "")
            props["nri_coastal_flood_rating"] = tp.get("nri_coastal_flood_rating", "")
            props["nri_hurricane_rating"] = tp.get("nri_hurricane_rating", "")
            props.update(lookup(flood or {}, lon, lat))
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    feats.sort(key=lambda f: (f["properties"]["county"], -f["properties"]["times_opened_2026"],
                              f["properties"]["name"]))
    return {"type": "FeatureCollection", "features": feats, "metadata": {
        "title": "Hawaiʻi shelters and refuge areas opened in 2026 events",
        "built_at": now_hst(),
        "source_table": "data/sources/county_shelter_activations.csv",
        "disclaimer": DISCLAIMER,
        "note": "Site types are kept as each county names them; counties define "
                "sheltering differently (DHS challenge pain point).",
    }}


def summary(fc: dict) -> dict:
    out = {}
    for c in COUNTIES:
        ps = [f["properties"] for f in fc["features"] if f["properties"]["county"] == c]
        out[c] = {"sites": len(ps),
                  "located": sum(1 for p in ps if not p["needs_geocode"]),
                  "needs_geocode": sum(1 for p in ps if p["needs_geocode"]),
                  "media_only": sum(1 for p in ps if not p["official_source"]),
                  "in_tsunami_zone": sum(1 for p in ps if p.get("in_tsunami_zone")),
                  "in_sfha": sum(1 for p in ps if p.get("in_sfha"))}
    return out


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def main() -> int:
    if not SRC.exists():
        print(f"Missing {SRC.relative_to(ROOT)}", file=sys.stderr)
        return 1
    schools = (_load(RAW / "schools.geojson") or {}).get("features", [])
    import build_access   # lazy: build_access -> fetch_arcgis -> geocode_shelters -> here
    # Census geocodes first; a site the Census could not locate may be located by ArcGIS
    geocodes = {**build_access.located_points(), **load_geocodes()}
    overrides = load_overrides()
    geocodes.update({o["address"].strip(): (float(o["lon"]), float(o["lat"]), VERIFIED)
                     for o in overrides.values()})
    fc = build(load_activations(), schools, _load(OUT / "afn_tracts.geojson"),
               _load(RAW / "tsunami_zone.geojson"), geocodes, load_cache())
    for f in fc["features"]:
        o = overrides.get(f"{f['properties']['name']}|{f['properties']['county']}")
        if o:
            f["properties"]["location_note"] = location_note(o)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "shelters_2026.geojson").write_text(json.dumps(fc, indent=1, ensure_ascii=False),
                                               encoding="utf-8")
    rows = [dict(f["properties"], sources=" ".join(f["properties"]["sources"]),
                 lon=(f["geometry"] or {}).get("coordinates", [None, None])[0],
                 lat=(f["geometry"] or {}).get("coordinates", [None, None])[1])
            for f in fc["features"]]
    if rows:
        keys = list(dict.fromkeys(k for r in rows for k in r))
        with open(OUT / "shelters_2026.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=keys)
            w.writeheader()
            w.writerows(rows)
    print(f"Wrote {len(rows)} sites -> data/processed/shelters_2026.geojson / .csv\n")
    print(f"{'County':<10}{'Sites':>6}{'Located':>9}{'Geocode':>9}{'Media only':>12}"
          f"{'Tsunami':>9}{'SFHA':>6}")
    for c, v in summary(fc).items():
        print(f"{c:<10}{v['sites']:>6}{v['located']:>9}{v['needs_geocode']:>9}"
              f"{v['media_only']:>12}{v['in_tsunami_zone']:>9}{v['in_sfha']:>6}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
