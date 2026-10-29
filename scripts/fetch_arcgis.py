#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – Esri ArcGIS Online calls, at BUILD TIME ONLY.

The web app never calls ArcGIS: this script runs once on a developer machine, stores the
answers locally, and build_access.py turns them into small per-area summaries for the app.

Steps (paid steps print an estimate first and stop if the run would pass the budget):
  1a geocode_sites       World Geocoding Service, forStorage=true, 30 shelter sites
  1b geocode_facilities  same, CMS dialysis facilities, nursing homes and hospitals (HI)
  2  od_drive            Origin-destination cost matrix, driving time: populated Census areas'
                         land points -> located sites on the same island
  3  od_walk_near        walking time, per site, for areas within 12 km (straight line); the
                         first island-wide walk run (od_walk) returned no times: walking mode
                         rejects inputs more than 27 miles apart
  3b od_schools          driving time, per Census area, to the 5 nearest DOE candidate schools
                         usable for each hazard on the same island (straight-line pre-filter)
  4  service_areas       15-minute drive polygon per located site, only if the budget allows

Token: environment variable ARCGIS_TOKEN only (a temporary OAuth app token). It is sent in
POST bodies, never in URLs, and never written to any file or log. If it is missing the
script exits with a message; the rest of the build still works (straight-line fallback).
If it expires mid-run (498/499, "Invalid token"), progress is saved and the script stops;
run it again with a fresh token and it resumes without repeating paid calls.

No hosted layers are created (no storage charges). Raw answers stay in data/raw/arcgis/
(gitignored). Credits per step are logged to data/processed/arcgis_credits.json.

Usage:  ARCGIS_TOKEN=... python3 scripts/fetch_arcgis.py           # all steps
        python3 scripts/fetch_arcgis.py --estimate                  # counts only, no paid calls
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from geo import ZoneIndex, haversine_km  # noqa: E402
from geocode_shelters import plain  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "arcgis"
CREDITS = ROOT / "data" / "processed" / "arcgis_credits.json"
SHELTERS = ROOT / "data" / "processed" / "shelters_2026.geojson"
AFN = ROOT / "data" / "processed" / "afn_tracts.geojson"
ISLANDS = ROOT / "data" / "sources" / "islands.csv"
COAST = ROOT / "data" / "raw" / "coastline.geojson"

BUDGET = 22.0                     # credits; 3 more are kept in reserve and never planned
RATE = {"geocode": 0.04,          # stored geocode (forStorage=true): 40 credits per 1,000
        "od_pair": 0.0005,        # origin-destination cost matrix: per input pair
        "service_area": 0.5}      # per facility per break
RATE_SOURCES = [
    "https://doc.arcgis.com/en/arcgis-online/administer/credits.htm",
    "https://pro.arcgis.com/en/pro-app/latest/help/analysis/networks/"
    "credit-consumption-and-analysis-limits.htm"]
GEOCODE_URL = ("https://geocode-api.arcgis.com/arcgis/rest/services/World/GeocodeServer/"
               "findAddressCandidates")
OD_BASE = ("https://route-api.arcgis.com/arcgis/rest/services/World/OriginDestinationCostMatrix/"
           "NAServer/OriginDestinationCostMatrix_World")
SA_URL = ("https://route-api.arcgis.com/arcgis/rest/services/World/ServiceAreas/NAServer/"
          "ServiceArea_World/solveServiceArea")
CMS = {  # CMS Provider Data Catalog (public, facility level)
    "dialysis": ("23ew-n7w9", "Dialysis Facility – Listing by Facility"),
    "nursing_home": ("4pq5-n9py", "Nursing Homes – Provider Information"),
    "hospital": ("xubh-q36u", "Hospital General Information"),
}
CMS_URL = "https://data.cms.gov/provider-data/api/1/datastore/query/{}/0"
ISLE_COUNTY = {"Oʻahu": "Honolulu", "Hawaiʻi": "Hawaii", "Maui": "Maui", "Molokaʻi": "Maui",
               "Lānaʻi": "Maui", "Kahoʻolawe": "Maui", "Kauaʻi": "Kauai", "Niʻihau": "Kauai"}
GOOD_TYPES = {"PointAddress", "StreetAddress", "POI", "Subaddress"}
UA = "HAIC2026-KahuOla-ESF6/1.0 (+https://github.com/HAIC-2026/Kahu-Ola)"
CONFIRM_M = 300                   # metres
OD_CHUNK = 50                     # origins per request: the service allows at most 50
                                  # (pairs, and credits, are unchanged by chunking)
WALK_KM = 12                      # walk times only for areas within 12 km (straight line) of a
                                  # site; walking mode rejects inputs > 27 miles (43 km) apart
SCHOOLS_K = 5                     # nearest candidate schools per hazard (straight line)
CANDIDATES = ROOT / "data" / "processed" / "candidates.geojson"
NEEDS_BY_TRACT = ROOT / "data" / "processed" / "needs_by_tract.csv"
OVERRIDES = ROOT / "data" / "sources" / "site_point_overrides.csv"
STEPS = ["geocode_sites", "geocode_facilities", "od_drive", "od_walk_near", "od_schools",
         "od_drive_refresh", "od_walk_refresh", "service_areas"]


class TokenExpired(Exception):
    pass


class OverBudget(Exception):
    pass


# ---------------------------------------------------------------- small helpers

def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def token_error(data) -> bool:
    err = data.get("error") if isinstance(data, dict) else None
    if not err:
        return False
    text = (str(err.get("message", "")) + " " + " ".join(map(str, err.get("details") or []))).lower()
    return err.get("code") in (498, 499) or "invalid token" in text or "token required" in text


def post(url: str, params: dict, token: str, retries: int = 4, timeout: int = 120) -> dict:
    """POST form data (token in the body, never in the URL). Retries network errors and 5xx."""
    body = urllib.parse.urlencode({**params, "f": "json", "token": token}).encode()
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=body, headers={
                "User-Agent": UA,
                "Content-Type": "application/x-www-form-urlencoded"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (498, 499):
                raise TokenExpired(f"HTTP {e.code}") from None
            last = f"HTTP {e.code}"
            if e.code < 500 and e.code != 429:
                break
        except (OSError, json.JSONDecodeError) as e:
            last = type(e).__name__
        else:
            if token_error(data):
                raise TokenExpired(str(data["error"].get("code")))
            err = data.get("error") if isinstance(data, dict) else None
            if err and int(err.get("code") or 0) >= 500:
                last = f"service error {err.get('code')}"
            else:
                return data
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"request failed after {retries} tries: {last}")


def scrub(obj, token: str):
    """Defence in depth: make sure the token string never reaches a file."""
    text = json.dumps(obj, ensure_ascii=False)
    if token and token in text:
        text = text.replace(token, "[removed]")
        return json.loads(text)
    return obj


# ---------------------------------------------------------------- credits ledger

def ledger() -> dict:
    return load_json(CREDITS, {"budget": BUDGET, "reserve": 3, "rates": RATE,
                               "rate_sources": RATE_SOURCES, "steps": {}})


def spent(led: dict) -> float:
    return round(sum(s.get("credits_actual", 0) for s in led["steps"].values()), 4)


def guard(led: dict, step: str, units: int, rate: float, unit_name: str) -> float:
    """Print the estimate for one paid step; raise OverBudget if it would pass the budget."""
    est = round(units * rate, 4)
    total = round(spent(led) + est, 4)
    print(f"[estimate] {step}: {units} {unit_name} x {rate} = {est} credits "
          f"(spent so far {spent(led)}, after this step {total} of {BUDGET})")
    if total > BUDGET:
        raise OverBudget(f"{step}: estimate {est} would bring the total to {total} > {BUDGET}")
    return est


def record(led: dict, step: str, units: int, rate: float, unit_name: str, est: float,
           note: str = "") -> None:
    prev = led["steps"].get(step, {})
    units_total = prev.get("units_billed", 0) + units
    led["steps"][step] = {
        "unit": unit_name, "units_billed": units_total, "rate": rate,
        "credits_estimate": round(prev.get("credits_estimate", 0) + est, 4),
        "credits_actual": round(units_total * rate, 4),
        "actual_method": "billed units returned by the service x published rate",
        "note": note or prev.get("note", ""), "updated": now()}
    save_json(CREDITS, led)


# ---------------------------------------------------------------- inputs

def site_key(p: dict) -> str:
    return f"{p['name']}|{p['county']}"


def load_sites() -> list:
    out = []
    for f in load_json(SHELTERS, {"features": []})["features"]:
        p, g = f["properties"], f.get("geometry")
        out.append({"key": site_key(p), "name": p["name"], "county": p["county"],
                    "address": p.get("address", ""),
                    "point": g["coordinates"][:2] if g else None,
                    "method": p.get("location_method") or ""})
    return out


def fetch_cms(kind: str) -> list:
    """Hawaiʻi facilities from one CMS file (free; addresses only, no patient data)."""
    ds, _title = CMS[kind]
    q = urllib.parse.urlencode({"conditions[0][property]": "state",
                                "conditions[0][value]": "HI",
                                "conditions[0][operator]": "=", "limit": 500})
    req = urllib.request.Request(CMS_URL.format(ds) + "?" + q, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        rows = json.loads(r.read().decode("utf-8"))["results"]
    out = []
    for r in rows:
        if kind == "dialysis":
            name, addr = r["facility_name"], r["address_line_1"]
            ident = r["cms_certification_number_ccn"]
        elif kind == "nursing_home":
            name, addr = r["provider_name"], r["provider_address"]
            ident = r["cms_certification_number_ccn"]
        else:
            name, addr = r["facility_name"], r["address"]
            ident = r["facility_id"]
        out.append({"id": f"{kind}:{ident}", "type": kind, "name": name.strip(),
                    "address": addr.strip(), "city": r["citytown"].strip(),
                    "zip": str(r["zip_code"]).strip()[:5],
                    "cms_county": r.get("countyparish", "").strip(),
                    "source": f"CMS Provider Data Catalog, {CMS[kind][1]} ({ds})",
                    "source_url": f"https://data.cms.gov/provider-data/dataset/{ds}"})
    return out


def load_facilities(refresh: bool = False) -> list:
    path = RAW / "cms_facilities.json"
    if refresh or not path.exists():
        rows = [f for k in CMS for f in fetch_cms(k)]
        save_json(path, {"fetched": now(), "rows": rows})
    return load_json(path, {})["rows"]


def populated_origins() -> list:
    pop = {f["properties"]["tract_fips"]: f["properties"].get("population") or 0
           for f in load_json(AFN, {"features": []})["features"]}
    with open(ISLANDS, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return [{"id": r["id"], "island": r["island"], "lon": float(r["lon"]),
             "lat": float(r["lat"])} for r in rows
            if r["kind"] == "area" and pop.get(r["id"], 0) > 0 and r["island"] in ISLE_COUNTY]


# ---------------------------------------------------------------- geocoding

def query_text(address: str, city: str = "", zipc: str = "") -> str:
    q = plain(address).strip().rstrip(",")
    tail = ", ".join(x for x in (plain(city), "HI " + zipc if zipc else "HI") if x)
    return f"{q}, {tail}"


def geocode(single_line: str, token: str) -> dict:
    data = post(GEOCODE_URL, {
        "SingleLine": single_line, "forStorage": "true", "maxLocations": 1,
        "sourceCountry": "USA", "outSR": 4326,
        "outFields": "Score,Addr_type,Match_addr,Subregion,Region,City"}, token)
    c = (data.get("candidates") or [])
    if not c:
        return {"status": "no_match"}
    a, loc = c[0].get("attributes", {}), c[0].get("location", {})
    return {"status": "match", "lon": round(loc["x"], 6), "lat": round(loc["y"], 6),
            "score": a.get("Score", c[0].get("score")), "addr_type": a.get("Addr_type", ""),
            "match_addr": a.get("Match_addr", c[0].get("address", "")),
            "subregion": a.get("Subregion", ""), "region": a.get("Region", "")}


def run_geocodes(step: str, items: list, cache_path: Path, token: str, led: dict,
                 pause: float = 1.0) -> dict:
    """items = [{"key", "query"}]. Cached keys are never looked up again."""
    cache = load_json(cache_path, {})
    todo = [it for it in items if it["key"] not in cache]
    if not todo:
        print(f"[skip] {step}: all {len(items)} already geocoded")
        return cache
    est = guard(led, step, len(todo), RATE["geocode"], "geocodes")
    done = 0
    try:
        for it in todo:
            res = geocode(it["query"], token)
            cache[it["key"]] = {"query": it["query"], **res, "geocoded": now()}
            done += 1
            print(f"  [{res['status']}] {it['key']}  score={res.get('score', '')} "
                  f"type={res.get('addr_type', '')}")
            if done % 10 == 0:
                save_json(cache_path, scrub(cache, token))
            time.sleep(pause)
    finally:
        save_json(cache_path, scrub(cache, token))
        record(led, step, done, RATE["geocode"], "geocodes",
               round(done * RATE["geocode"], 4) if done < len(todo) else est)
    return cache


def county_of_subregion(sub: str) -> str:
    s = plain(sub).lower()
    for c in ("honolulu", "hawaii", "maui", "kauai", "kalawao"):
        if c in s:
            return {"kalawao": "Maui"}.get(c, c.capitalize())
    return ""


def classify_site(site: dict, esri: dict | None, island_of) -> dict:
    """Compare one site's existing point with the ArcGIS point.
    <= 300 m: confirmed (2 sources). > 300 m: needs review (keep existing point).
    No existing point: located (ArcGIS) only if score >= 90, a precise match type,
    the right county and the same island; otherwise not located."""
    pt = site.get("point")
    ok_esri = bool(esri and esri.get("status") == "match")
    if pt and ok_esri:
        d = haversine_km(pt[0], pt[1], esri["lon"], esri["lat"]) * 1000
        status = "confirmed" if d <= CONFIRM_M else "needs_review"
        return {"status": status, "distance_m": round(d), "lon": pt[0], "lat": pt[1],
                "point_source": site.get("method") or "existing"}
    if pt:
        return {"status": "single_source", "distance_m": None, "lon": pt[0], "lat": pt[1],
                "point_source": site.get("method") or "existing"}
    if not ok_esri:
        return {"status": "not_located", "distance_m": None, "lon": None, "lat": None,
                "point_source": ""}
    island = island_of(esri["lon"], esri["lat"])
    reasons = []
    if (esri.get("score") or 0) < 90:
        reasons.append(f"score {esri.get('score')} < 90")
    if esri.get("addr_type") not in GOOD_TYPES:
        reasons.append(f"match type {esri.get('addr_type')}")
    if county_of_subregion(esri.get("subregion", "")) != site["county"]:
        reasons.append(f"county {esri.get('subregion')}")
    if ISLE_COUNTY.get(island) != site["county"] or (
            site.get("island") and island != site["island"]):
        reasons.append(f"island {island or 'none'}")
    if reasons:
        return {"status": "not_located", "distance_m": None, "lon": None, "lat": None,
                "point_source": "", "reason": "; ".join(reasons)}
    return {"status": "located_arcgis", "distance_m": None, "lon": esri["lon"],
            "lat": esri["lat"], "point_source": "arcgis_world_geocoder", "island": island}


# ---------------------------------------------------------------- network analysis

def travel_modes(token: str) -> dict:
    path = RAW / "travel_modes.json"
    if not path.exists():
        data = post(OD_BASE + "/retrieveTravelModes", {}, token)
        save_json(path, scrub(data, token))
    data = load_json(path, {})
    return {m["name"]: m for m in data.get("supportedTravelModes", [])}


def features(points: list) -> str:
    return json.dumps({"features": [{"geometry": {"x": p["lon"], "y": p["lat"],
                                                  "spatialReference": {"wkid": 4326}},
                                     "attributes": {"Name": p["id"]}} for p in points]})


def od_pairs(origins: list, dests: dict) -> list:
    """[(island, origin chunk, destinations)] for same-island pairs only."""
    jobs = []
    for isl in sorted({o["island"] for o in origins}):
        ds = dests.get(isl, [])
        if not ds:
            continue
        os_ = [o for o in origins if o["island"] == isl]
        for i in range(0, len(os_), OD_CHUNK):
            jobs.append((isl, os_[i:i + OD_CHUNK], ds))
    return jobs


def od_failure(data: dict) -> str:
    """Error text when the service answered without solving (e.g. too many origins)."""
    m = data.get("odCostMatrix") or {}
    if any(row for k, row in m.items() if k.isdigit()):
        return ""
    errs = [x.get("description", "") for x in data.get("messages", []) if x.get("type") == 100]
    return "; ".join(errs) or "empty matrix"


def walk_jobs(origins: list, dests: dict) -> list:
    """[(site id, origin chunk, [site])]: per site, same-island areas within WALK_KM."""
    jobs = []
    for isl in sorted(dests):
        for d in sorted(dests[isl], key=lambda x: x["id"]):
            near = [o for o in origins if o["island"] == isl
                    and haversine_km(o["lon"], o["lat"], d["lon"], d["lat"]) <= WALK_KM]
            for i in range(0, len(near), OD_CHUNK):
                jobs.append((d["id"], near[i:i + OD_CHUNK], [d]))
    return jobs


def candidate_schools(island_of) -> list:
    """DOE candidate schools with island and the hazards each is usable for (the same
    rule as model_needs.usable_sites: tsunami -> outside the evacuation zone; others ->
    site_status 'ok' with the county's footprint)."""
    from model_needs import HAZARDS, site_status
    foot = {}
    with open(NEEDS_BY_TRACT, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            foot.setdefault((r["county"], r["hazard"]), set()).add(r["tract_fips"])
    out = []
    for f in load_json(CANDIDATES, {"features": []})["features"]:
        g, p = f.get("geometry"), f["properties"]
        if not g:
            continue
        lon, lat = g["coordinates"][:2]
        ok = [h for h in HAZARDS if (not p.get("hazard_excluded") if h == "tsunami" else
              site_status(p, h, foot.get((p["county"], h), set()))[0] == "ok")]
        out.append({"id": p["id"], "name": p["name"], "county": p["county"], "lon": lon,
                    "lat": lat, "island": island_of(lon, lat), "usable": ok})
    return out


def school_jobs(origins: list, schools: list) -> list:
    """[(area id, [area], schools)]: per area, the SCHOOLS_K nearest (straight line)
    candidate schools usable for each hazard on the same island, as one set."""
    from model_needs import HAZARDS
    jobs = []
    for o in origins:
        same = [s for s in schools if s["island"] == o["island"]]
        pick = {}
        for h in HAZARDS:
            ranked = sorted((s for s in same if h in s["usable"]),
                            key=lambda s: (haversine_km(o["lon"], o["lat"], s["lon"], s["lat"]), s["id"]))
            for s in ranked[:SCHOOLS_K]:
                pick[s["id"]] = s
        if pick:
            jobs.append((o["id"], [o], [pick[k] for k in sorted(pick)]))
    return jobs


def refreshed_sites() -> set:
    """Site keys whose point was corrected after the first matrices (verified by hand)."""
    if not OVERRIDES.exists():
        return set()
    with open(OVERRIDES, newline="", encoding="utf-8") as fh:
        return {r["site_key"] for r in csv.DictReader(fh)}


def refresh_jobs(origins: list, dests: dict, walk: bool) -> list:
    """Drive (all same-island areas) or walk (areas within WALK_KM) jobs for the
    corrected sites only (saved in their own files, read after the first run)."""
    keys = refreshed_sites()
    moved = {isl: [d for d in ds if d["id"] in keys] for isl, ds in dests.items()}
    moved = {isl: ds for isl, ds in moved.items() if ds}
    return walk_jobs(origins, moved) if walk else od_pairs(origins, moved)


def run_od(step: str, mode_name: str, time_attr: str, origins: list, dests: dict,
           token: str, led: dict) -> dict:
    path = RAW / f"{step}.json"
    out = load_json(path, {"mode": mode_name, "results": {}})
    plan = (walk_jobs(origins, dests) if step == "od_walk_near" else
            school_jobs(origins, dests["_schools"]) if step == "od_schools" else
            refresh_jobs(origins, dests, step == "od_walk_refresh") if step.endswith("_refresh") else
            od_pairs(origins, dests))
    jobs = [j for j in plan if f"{j[0]}|{j[1][0]['id']}" not in out["results"]]
    if not jobs:
        print(f"[skip] {step}: all requests already done")
        return out
    pairs = sum(len(o) * len(d) for _i, o, d in jobs)
    est = guard(led, step, pairs, RATE["od_pair"], "OD pairs")
    mode = travel_modes(token).get(mode_name)
    if not mode:
        raise RuntimeError(f"travel mode {mode_name!r} not offered by the service")
    billed = 0
    try:
        for isl, os_, ds in jobs:
            data = post(OD_BASE + "/solveODCostMatrix", {
                "origins": features(os_), "destinations": features(ds),
                "travelMode": json.dumps(mode), "outputType": "esriNAODOutputSparseMatrix",
                "accumulateAttributeNames": f"Kilometers,{time_attr}",
                "impedanceAttributeName": time_attr, "returnEmptyResults": "true"}, token)
            if "error" in data:
                raise RuntimeError(f"{step} {isl}: {data['error'].get('message')}")
            failed = od_failure(data)
            if failed:          # HTTP 200 with no matrix: not solved, not saved, not billed
                raise RuntimeError(f"{step} {isl}: {failed}")
            billed += len(os_) * len(ds)
            out["results"][f"{isl}|{os_[0]['id']}"] = {
                "island": isl, "origins": [o["id"] for o in os_],
                "destinations": [d["id"] for d in ds], "matrix": data.get("odCostMatrix"),
                "messages": data.get("messages", [])}
            save_json(path, scrub(out, token))
            print(f"  {step} {isl}: {len(os_)} x {len(ds)}")
    finally:
        save_json(path, scrub(out, token))
        record(led, step, billed, RATE["od_pair"], "OD pairs",
               est if billed == pairs else round(billed * RATE["od_pair"], 4))
    return out


def run_service_areas(sites: list, token: str, led: dict) -> dict:
    path = RAW / "service_areas.json"
    out = load_json(path, {"results": {}})
    todo = [s for s in sites if s["id"] not in out["results"]]
    if not todo:
        return out
    est = guard(led, "service_areas", len(todo), RATE["service_area"], "service areas")
    mode = travel_modes(token).get("Driving Time")
    billed = 0
    try:
        for s in todo:
            data = post(SA_URL, {
                "facilities": features([s]), "defaultBreaks": "15",
                "travelMode": json.dumps(mode), "outputPolygons": "esriNAOutputPolygonSimplified",
                "outSR": 4326, "trimOuterPolygon": "true", "trimPolygonDistance": 100,
                "trimPolygonDistanceUnits": "esriMeters"}, token)
            if "error" in data:
                raise RuntimeError(f"service area {s['id']}: {data['error'].get('message')}")
            billed += 1
            out["results"][s["id"]] = data.get("saPolygons")
            save_json(path, scrub(out, token))
    finally:
        save_json(path, scrub(out, token))
        record(led, "service_areas", billed, RATE["service_area"], "service areas",
               est if billed == len(todo) else billed * RATE["service_area"])
    return out


# ---------------------------------------------------------------- orchestration

def site_points(sites: list, esri_cache: dict, island_of) -> list:
    out = []
    isl = {}
    if ISLANDS.exists():
        with open(ISLANDS, newline="", encoding="utf-8") as fh:
            isl = {r["id"]: r["island"] for r in csv.DictReader(fh) if r["kind"] == "site"}
    for s in sites:
        s = {**s, "island": isl.get(s["key"], "")}
        c = classify_site(s, esri_cache.get(s["key"]), island_of)
        out.append({**s, **c, "esri": esri_cache.get(s["key"]),
                    "island": c.get("island") or s["island"] or
                    (island_of(c["lon"], c["lat"]) if c["lon"] is not None else "")})
    return out


def plan_counts(sites: list, facilities: list, origins: list, located: list,
                island_of=lambda x, y: "") -> dict:
    dests = {}
    for s in located:
        dests.setdefault(s["island"], []).append(s)
    pairs = sum(len(o) * len(d) for _i, o, d in od_pairs(origins, dests))
    walk = sum(len(o) for _i, o, _d in walk_jobs(origins, dests))
    schools = sum(len(d) for _i, _o, d in school_jobs(origins, candidate_schools(island_of)))
    return {"geocode_sites": len(sites), "geocode_facilities": len(facilities),
            "od_drive": pairs, "od_walk_near": walk, "od_schools": schools,
            "service_areas": len(located)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build-time ArcGIS Online calls (paid)")
    ap.add_argument("--estimate", action="store_true", help="print counts, make no paid calls")
    ap.add_argument("--steps", default=",".join(STEPS), help="comma-separated subset")
    args = ap.parse_args(argv)
    steps = [s for s in args.steps.split(",") if s]

    coast = ZoneIndex(load_json(COAST, None))
    from build_islands import island_of as _island_of  # noqa: E402
    island_of = (lambda x, y: _island_of(coast, x, y)) if coast else (lambda x, y: "")
    sites, facilities = load_sites(), load_facilities()
    origins = populated_origins()
    esri_sites = load_json(RAW / "geocode_sites.json", {})
    pts = site_points(sites, esri_sites, island_of)
    # Before step 1a, plan with existing points + Pukalani if it gets located
    located = [{"id": p["key"], "lon": p["lon"], "lat": p["lat"], "island": p["island"]}
               for p in pts if p["lon"] is not None and p["island"]]
    counts = plan_counts(sites, facilities, origins, located, island_of)
    led = ledger()
    print("Planned units:", json.dumps(counts))
    total = (counts["geocode_sites"] + counts["geocode_facilities"]) * RATE["geocode"] \
        + (counts["od_drive"] + counts["od_walk_near"] + counts["od_schools"]) * RATE["od_pair"] + counts["service_areas"] * RATE["service_area"]
    print(f"Full plan estimate: {round(total, 3)} credits (budget {BUDGET}); "
          f"already spent {spent(led)}")
    if args.estimate:
        return 0

    token = os.environ.get("ARCGIS_TOKEN", "").strip()
    if not token:
        print("ARCGIS_TOKEN is not set: no ArcGIS calls made. The build still works "
              "(straight-line distances).", file=sys.stderr)
        return 2
    RAW.mkdir(parents=True, exist_ok=True)
    try:
        if "geocode_sites" in steps:
            esri_sites = run_geocodes("geocode_sites", [
                {"key": s["key"], "query": query_text(s["address"])} for s in sites],
                RAW / "geocode_sites.json", token, led)
        if "geocode_facilities" in steps:
            run_geocodes("geocode_facilities", [
                {"key": f["id"], "query": query_text(f["address"], f["city"], f["zip"])}
                for f in facilities], RAW / "geocode_facilities.json", token, led)
        pts = site_points(sites, esri_sites, island_of)
        located = [{"id": p["key"], "lon": p["lon"], "lat": p["lat"], "island": p["island"]}
                   for p in pts if p["lon"] is not None and p["island"]]
        dests = {}
        for s in located:
            dests.setdefault(s["island"], []).append(s)
        if "od_drive" in steps:
            run_od("od_drive", "Driving Time", "TravelTime", origins, dests, token, led)
        if "od_walk_near" in steps:
            run_od("od_walk_near", "Walking Time", "WalkTime", origins, dests, token, led)
        if "od_drive_refresh" in steps:
            run_od("od_drive_refresh", "Driving Time", "TravelTime", origins, dests, token, led)
        if "od_walk_refresh" in steps:
            run_od("od_walk_refresh", "Walking Time", "WalkTime", origins, dests, token, led)
        if "od_schools" in steps:
            run_od("od_schools", "Driving Time", "TravelTime", origins,
                   {"_schools": candidate_schools(island_of)}, token, led)
        if "service_areas" in steps:
            need = len([s for s in located
                        if s["id"] not in load_json(RAW / "service_areas.json",
                                                    {"results": {}})["results"]])
            if spent(led) + need * RATE["service_area"] > BUDGET:
                msg = (f"skipped: {need} service areas x {RATE['service_area']} = "
                       f"{need * RATE['service_area']} credits would pass the budget "
                       f"({spent(led)} spent of {BUDGET}). The 'outside 15-minute drive' "
                       f"layer uses the drive-time matrix instead.")
                print("[skip] service_areas:", msg)
                led["steps"]["service_areas"] = {"unit": "service areas", "units_billed": 0,
                                                 "rate": RATE["service_area"],
                                                 "credits_estimate": need * RATE["service_area"],
                                                 "credits_actual": 0, "note": msg,
                                                 "updated": now()}
                save_json(CREDITS, led)
            else:
                run_service_areas(located, token, led)
    except TokenExpired as e:
        print(f"\nTOKEN EXPIRED or invalid ({e}). Progress saved in data/raw/arcgis/. "
              f"Refresh ARCGIS_TOKEN and run this script again: it resumes without repeating "
              f"finished paid calls.", file=sys.stderr)
        return 3
    except OverBudget as e:
        print(f"\nSTOPPED (budget): {e}", file=sys.stderr)
        return 4
    led["total_credits_actual"] = spent(led)
    save_json(CREDITS, led)
    print(f"\nCredits used: {spent(led)} of {BUDGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
