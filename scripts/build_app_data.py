#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – data bundle for the offline web app (app/).

Writes app/data/bundle.json (compact: simplified tract outlines, sites with per-hazard
status, scenarios, needs x partners, decision points, outreach tracts, languages) and
app/data/version.json (version hash + "data as of"), copies the 20 PDF playbooks into
app/playbooks/, and regenerates the generated blocks in app/sw.js (precache list) and
app/index.html (static PDF links shown if the data cannot load).

Aggregate data only: tract counts, public facility names and addresses. No individual
records. Offline: reads local files only.

app/playbooks/ is a build artifact (gitignored): the PDFs are committed once, in playbooks/.

Usage:  python3 scripts/build_app_data.py    (after build_playbooks.py; needs data/raw/)
        python3 scripts/build_app_data.py --copy-only [--allow-missing-raw]
            (app-only step, e.g. after a change in app/ or before deploying: copies
            playbooks/*.pdf into app/playbooks/ and refreshes the service worker VERSION and
            precache list from the committed bundle. Never regenerates data.)

The full build fails closed: a missing or empty input in data/raw/ (tsunami zones, ...) or
a missing committed summary stops it with a message (scripts/raw_inputs.py) instead of
writing a bundle without that layer. --allow-missing-raw is accepted only with --copy-only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import message_library  # noqa: E402
import svgmap  # noqa: E402
from geo import area_centroid  # noqa: E402
import build_islands  # noqa: E402
import build_access  # noqa: E402
import build_state_layers as bsl  # noqa: E402
import build_hub_layers as bhl  # noqa: E402
import stress_text  # noqa: E402
import whatif  # noqa: E402
from raw_inputs import MissingInput, load_geojson  # noqa: E402
from build_playbooks import (AFN_PARTS, CMIST, COL, COUNTY_LABEL, COUNTY_LINE_LABEL,  # noqa: E402
                             DETAIL_KEYS, DISCLAIMER, KALAWAO_NOTE, SERVICE_ANIMALS, WHO_ELSE,
                             results_data, NO_FACILITY_SCREEN, FACILITY_ZONE_D, LAHAINA_NOTE, LAHAINA_SUMMARY,
                             all_languages, MESSAGES_LINE, TOO_FEW, LOW_RELIABILITY, CV_LIMIT,
                             FOOTPRINT_TEXT, HAZARD_LABEL, HURRICANE_SCOPE_NOTE, PROV_NUMBERS,
                             PROV_SHELTERS, RATE_NOTE,
                             SITE_KEY_STATUS, SOURCE, area_label, lang_label, partner_names,
                             partner_text, plain_reason,
                             KAUAI_MAUI_NOTE, STATUS_LABEL, largest_communities, load_inputs,
                             scenario, sites_for, slug, tract_rows)
from fetch_data import COUNTIES  # noqa: E402
from match import select_languages  # noqa: E402
from model_needs import HAZARDS  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
DATA = APP / "data"
PLAYBOOKS = ROOT / "playbooks"
TOL = 0.0008                  # degrees (~80 m) for outline simplification
SHELL = ["./", "index.html", "app.js", "whatif.js", "styles.css", "manifest.webmanifest", "icon.svg",
         "icon-180.png", "icon-192.png", "icon-512.png"]
SCENARIO_FIELDS = ("at_risk_pop", "shelter_demand_low", "shelter_demand_central",
                   "shelter_demand_high", "rate_low", "rate_central", "rate_high",
                   "C_lep_at_risk", "M_power_dependent_at_risk", "I_disability_at_risk",
                   "I_age65_at_risk", "T_no_vehicle_persons_at_risk", "tracts_at_risk",
                   "footprint_rule", "scope", "known_sites_usable", "known_sites_check_flood",
                   "known_sites_flood_undetermined", "candidate_schools_usable",
                   "candidate_schools_flood_undetermined", "at_risk_pop_extreme_zone",
                   "highrise_units_at_risk", "C_hearing_at_risk", "C_vision_at_risk",
                   "I_cognitive_at_risk", "S_age65_alone_at_risk")
PROC = ROOT / "data" / "processed"


def r4(v: float) -> float:
    return round(v, 4)


# Census-area counts for the detail panel (whole area; the app multiplies by the share in
# the risk area, people at risk / population, the same way model_needs.py does)
AREA_FIELDS = [("lep", "C_limited_english"), ("power", "M_power_dependent_est"),
               ("disability", "I_disability"), ("age65", "I_age_65_plus"),
               ("no_car", "T_no_car_persons"), ("hearing", "C_hearing_difficulty"),
               ("vision", "C_vision_difficulty"), ("cognitive", "I_cognitive_difficulty"),
               ("age65_alone", "S_age65_living_alone")]
OVERLAY_TOL = 0.0015          # degrees (~150 m) for the tsunami zone outline
ISLAND_COUNTY = {"OAHU": "Honolulu", "HAWAII": "Hawaii", "MAUI": "Maui", "MOLOKAI": "Maui",
                 "LANAI": "Maui", "KAUAI": "Kauai", "NIIHAU": "Kauai"}
OFFICIAL_MAP = {"label": "Open official State map",
                "url": "https://geoportal.hawaii.gov/",
                "source": "Hawaiʻi Statewide GIS Geoportal"}


def area_counts(p: dict) -> list:
    """Whole-area counts in AREA_FIELDS order (people)."""
    pop, hh = p.get("population") or 0, p.get("households") or 0
    vals = {**p, "T_no_car_persons": (p.get("T_households_no_vehicle") or 0) * (pop / hh if hh else 0)}
    return [pop] + [round(vals.get(src) or 0, 1) for _k, src in AREA_FIELDS]


TSUNAMI_COUNTIES = ("Honolulu", "Hawaii", "Maui", "Kauai")     # Kalawao has no State zone


def tsunami_overlay(path: Path = ROOT / "data" / "raw" / "tsunami_zone.geojson") -> dict:
    """State tsunami evacuation zone outline, simplified, by county (build time only).
    Fails closed: a missing or empty file, or a county without any zone, stops the build."""
    out = {}
    for f in load_geojson(path, "State tsunami evacuation zones")["features"]:
        county = ISLAND_COUNTY.get(str(f["properties"].get("island", "")).upper())
        if not county:
            continue
        for ring in svgmap.rings(f["geometry"]):
            pts = svgmap.simplify(ring, OVERLAY_TOL)
            if len(pts) < 4:
                continue
            flat = []
            for x, y in pts:
                flat += [r4(x), r4(y)]
            out.setdefault(county, []).append(flat)
    missing = [c for c in TSUNAMI_COUNTIES if not out.get(c)]
    if missing:
        raise MissingInput(f"Build stopped: no tsunami evacuation zone for {', '.join(missing)} "
                           f"in {path.name}; the download looks incomplete.")
    return out


def require_summaries() -> None:
    """The committed summaries the full build reads (data/sources/). Missing = error: without
    them the app would quietly drop islands, travel times, care facilities and sirens."""
    for name, value, script in (("islands.csv", ISLANDS, "build_islands.py"),
                                ("arcgis_summary.json", ACCESS, "build_access.py"),
                                ("state_layers_summary.json", STATE, "build_state_layers.py")):
        if not value:
            raise MissingInput(f"Build stopped: data/sources/{name} is missing or empty. "
                               f"Run python3 scripts/{script} first.")
    if not STATE.get("sirens") or not STATE.get("areas"):
        raise MissingInput("Build stopped: data/sources/state_layers_summary.json has no "
                           "sirens or Census areas.")
    if not HUB or not HUB.get("overlays") or not HUB.get("safe_zone_walk"):
        raise MissingInput("Build stopped: data/sources/hub_layers_summary.json is missing or "
                           "empty. Run python3 scripts/build_hub_layers.py first.")
    if not ACCESS.get("facilities") or not ACCESS.get("areas"):
        raise MissingInput("Build stopped: data/sources/arcgis_summary.json has no care "
                           "facilities or travel times.")


STRESS_JSON = PROC / "stress_tests.json"
HUB = bhl.load()                      # data/sources/hub_layers_summary.json (build_hub_layers.py)
STRESS_SHOW = ("1", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15", "16",
               "17", "18", "19", "20", "21", "22", "23a", "23b", "24", "25")


def stress_bundle(sites: dict) -> dict:
    """Stress tests for the app: every finding that affects someone, needs county data, or
    counts facilities (two-site losses only when they add people beyond either site alone or
    leave an island without a usable site); plain-word evidence lines for each county's and
    each hazard's top 10. Rows: [id, test, scenario, county, hazard, people (null = needs
    county data), measure, rank, county rank, summary, source ids, assumption ids, areas,
    site ids, evidence lines (top 10 only)]. Rows: [id, test, scenario, county, hazard, people
    (null = needs county data), rank, county rank, summary extra, source ids, assumption ids,
    areas, site ids, evidence lines or 0]; the measure is per test ("measures")."""
    if not STRESS_JSON.exists():
        raise MissingInput("Build stopped: data/processed/stress_tests.json is missing. "
                           "Run python3 scripts/build_stress_tests.py first.")
    st = json.loads(STRESS_JSON.read_text(encoding="utf-8"))
    F = st["findings"]
    if not F:
        raise MissingInput("Build stopped: data/processed/stress_tests.json has no findings.")
    keep = []
    for f in F:
        e = f["evidence"]
        if f["test"] == "2":
            if e["more_than_worst_single_loss"] > 0 or e["areas_left_with_no_usable_site_on_island"] > 0:
                keep.append(f)
        elif f["people_affected"] or f["people_affected"] is None or f["unit"] != "people":
            keep.append(f)
    tops = {}
    for c in COUNTIES:
        tops[c] = {"all": [f["id"] for f in stress_text.top(F, c)]}
        for h in HAZARDS:
            tops[c][h] = [f["id"] for f in stress_text.top(F, c, h)]
    detail = {i for t in tops.values() for ids in t.values() for i in ids}
    keep_ids = {f["id"] for f in keep}
    keep += [f for f in F if f["id"] in detail and f["id"] not in keep_ids]
    srcs, asms, rows = [], [], []
    idx = lambda lst, v: lst.index(v) if v in lst else (lst.append(v) or len(lst) - 1)  # noqa: E731
    for f in sorted(keep, key=lambda f: f["rank"]):
        county = f["county"] if f["county"] != "Statewide" else "|".join(["Statewide", *f["evidence"]["counties"]])
        rows.append([f["id"], f["test"], f["scenario"], county, f["hazard"], f["people_affected"],
                     f["rank"], f["county_rank"], stress_text.extra(f),
                     [idx(srcs, x) for x in f["sources"]],
                     [idx(asms, f"{a['text']}: {a['value']} (team assumption)") for a in f["assumptions"]],
                     f["areas"][:3], [sites[k] for k in f["sites"] if k in sites][:6],
                     stress_text.evidence_lines(f) + ([["Note", f["evidence"]["note"]]] if "note" in f["evidence"] else [])
                     if f["id"] in detail else 0])
    tested = {c: sum(1 for f in F if stress_text.in_county(f, c)) for c in COUNTIES}
    import build_stress_tests
    return {"label": stress_text.LABEL, "method": st["method"], "tests": st["tests"],
            "measures": build_stress_tests.MEASURE, "needs_data": stress_text.NEEDS_DATA,
            "questions": stress_text.QUESTIONS, "sources": srcs, "assumptions": asms, "rows": rows,
            "top": tops, "tested": tested, "per_test": stress_text.PER_TEST,
            "not_no_shelter": build_access.NOT_NO_SHELTER}


def hub_bundle(hub: dict, sites: dict) -> dict:
    """Map overlays (Tsunami Safe Zones, State Fire Risk, flooded highways) and the PDC 2009
    reference capacity of matched 2026 sites (offered in the what-if panel, never the default)."""
    m = hub["meta"]
    pdc = hub["pdc"]
    return {"safe_zones": hub["overlays"]["safe_zones"], "fire_high": hub["overlays"]["fire_high"],
            "fire_medium": hub["overlays"]["fire_medium"],
            "flooded": {c: v["segments"] for c, v in hub["flooded"].items()},
            "flooded_km": {c: v["km"] for c, v in hub["flooded"].items()},
            "maui_2013": m["maui_2013_note"],
            "pdc_sites": {str(sites[k]): [v["capacity"], v["pdc_name"]] for k, v in pdc["site_capacity"].items() if k in sites},
            "pdc_schools": len(pdc["school_capacity"]), "pdc_with_capacity": pdc["with_capacity"],
            "pdc_note": "2009 reference capacity (American Red Cross Hawaiʻi State Chapter, via the "
                        "Pacific Disaster Center, ground condition October 2009): may be outdated. "
                        "Use only as a starting point; confirm with the county.",
            "sources": {"safe_zones": "Tsunami Safe Zones (Hawaiʻi Statewide GIS; Hawaiʻi Island, "
                                      "Oʻahu and Kauaʻi zones 2025, Maui County zones 2013), simplified outline.",
                        "fire": "State Fire Risk Areas (DLNR Division of Forestry and Wildlife, 2007; "
                                "boundaries confirmed 2022, via Hawaiʻi Statewide GIS), simplified outline. "
                                "The plan's wildfire numbers use the FEMA National Risk Index; this layer is a comparison.",
                        "flooded": "Potential flooded highways with 3.2 ft of sea level rise (Hawaiʻi Sea "
                                   "Level Rise Viewer, PacIOOS, via Hawaiʻi Statewide GIS). Chronic flooding "
                                   "later this century, not an event forecast."}}


WHATIF_HOW = {
    "people_in_shelter": "People in the risk area × shelter-seeking rate.",
    "cots": "One cot per person in shelter (rounded up).",
    "floor_sqft": "20 sq ft per person for stays up to 3 days, 40 sq ft beyond (Florida DEM 2010; past 14 days a team assumption).",
    "water": "1 gallon per person per day (Florida DEM 2010) × days of stay.",
    "meals": "2 meals per person per day (Florida DEM 2010) × days of stay.",
    "toilets": "1 per 40 people for stays up to 3 days, 1 per 20 beyond (Florida DEM 2010).",
    "outlets": "1 outlet per power-dependent person in shelter (HHS emPOWER-based estimate; team assumption). During a power outage: 1 charge a day for every power-dependent resident in the risk area, if that is more (team assumption, upper bound).",
    "staff": "Florida DEM (2010) ratios per shift: registration 1 per 165, dormitory 1 per 100, meals 1 per 110, mental health 1 per 250, health 1 per 200, security 1 per 100, sanitation 1 per 200 (each at least 1); children's area 1 per 12 children.",
    "interpreters": "People with limited English in shelter × each language's share of limited-English speakers (ACS PUMS 2019–2023). Each person may need an interpreter; it is not a count of interpreters.",
    "support": "People in shelter × the share needing support. Plan default: the share of people in shelter with a disability (ACS via CDC SVI).",
    "trips": "People in households without a car in the risk area ÷ people per vehicle trip, rounded up (an upper bound: not all will need a ride).",
    "pets": "Households in shelter × 44.6% with a dog and 26% with a cat (AVMA, 2020 data).",
    "allocation": "Each Census area's people in shelter go to the nearest usable 2026 site on the same island by drive time (Esri ArcGIS, normal traffic). Capacity is compared only when you enter it.",
}


def whatif_bundle(inp: dict) -> dict:
    cfg = json.loads((ROOT / "config" / "planning_factors.json").read_text(encoding="utf-8"))
    scfg = json.loads((ROOT / "config" / "stress_tests.json").read_text(encoding="utf-8"))
    langs = {c: [[lang_label(l["language"]), l["share_of_area_lep"]]
                 for l in select_languages(inp["languages"].get(c, []), inp["comm"])] for c in COUNTIES}
    agg = whatif.aggregates(inp["afn"], inp.get("labels") or {}, inp["shelters"]["features"],
                            inp["candidates"]["features"], cfg, langs)
    w = scfg["whatif"]
    return {"label": stress_text.WHATIF_LABEL, "factors": whatif.factors(cfg, scfg),
            "defaults": {"stay_days": w["stay_days"]["value"], "outage_days": w["outage_days"]["value"],
                         "people_per_trip": w["people_per_trip"]["value"]},
            "limits": {"rate": [w["rate"]["min"], w["rate"]["max"]], "stay": [w["stay_days"]["min"], w["stay_days"]["max"]],
                       "outage": [w["outage_days"]["min"], w["outage_days"]["max"]],
                       "trip": [w["people_per_trip"]["min"], w["people_per_trip"]["max"]],
                       "support": [w["support_share"]["min"], w["support_share"]["max"]]},
            "assumptions": {"people_per_trip": f"{w['people_per_trip']['value']} people per vehicle trip (team assumption: the plan gives no value)",
                            "stay": "3 days = the plan's 72-hour shelter factors",
                            "outage": "0 days = the plan: outlets for people in shelter only"},
            "staff_labels": {"client_registration": "Registration", "dormitory_management": "Dormitory",
                             "meal_service": "Meal service", "mental_health": "Mental health",
                             "public_health_medical": "Health and medical", "security": "Security",
                             "sanitation": "Sanitation", "children_area": "Children's area"},
            "how": WHATIF_HOW, "scenarios": agg}


ISLANDS = build_islands.load()        # data/sources/islands.csv (build_islands.py)
ACCESS = build_access.load()          # data/sources/arcgis_summary.json, or None (fallback)
STATE = bsl.load()                    # data/sources/state_layers_summary.json, or None


def area_access(fips: str, site_ids: dict, access: dict | None) -> dict:
    """Per Census area: "a" = [[site id, drive min, drive km, walk min]] to every known site
    on the same island, nearest drive first; "o" = {hazard: 1 or 2} when no 2026 activated
    site usable for that hazard is within a 15-minute drive (2: no DOE candidate school
    either). Empty without the ArcGIS summary (straight-line fallback)."""
    a = (access or {}).get("areas", {}).get(fips)
    if not a:
        return {}
    rows = sorted(([site_ids[k], *v] for k, v in a["sites"].items() if k in site_ids),
                  key=lambda r: (r[1] is None, r[1] or 0, r[0]))
    o = {h: build_access.outside(d1) + build_access.outside(d2)
         for h, (d1, d2) in a["drive_by_hazard"].items() if build_access.outside(d1)}
    return {"a": rows, **({"o": o} if o else {})}


def facilities_bundle(access: dict | None, state: dict | None = None) -> list:
    """Care facilities (CMS) and childcare centres (Ready Keiki): name, type, county, island,
    Census area, point, zone per hazard ("d": FEMA zone D, listed separately)."""
    return [{"n": f["name"], "t": f["type"], "c": f["county"], "i": f["island"], "f": f["tract"],
             "x": f["lon"], "y": f["lat"], "z": {h: z for h, z in f["zones"].items() if z},
             **({"d": 1} if (f["fld_zone"] or "").upper() == "D" else {})}
            for f in (access or {}).get("facilities", []) + (state or {}).get("childcare", [])]


def state_bundle(state: dict | None, labels: dict) -> dict:
    """Sirens (points, permanent only), the official audible radius, populated Census areas
    with no siren per county, and the "Check dam zone" wording. Empty without the summary."""
    if not state:
        return {}
    low, outside, sirens = {}, {}, {}
    for f in state["low_siren_coverage"]:
        low.setdefault(state["areas"][f]["county"], []).append(f)
    for f in state["outside_siren_range"]:
        outside[state["areas"][f]["county"]] = outside.get(state["areas"][f]["county"], 0) + 1
    for x in state["sirens"]:
        sirens.setdefault(x["county"], []).append([x["lon"], x["lat"]])
    r = state["meta"]["siren_radius"]
    return {"sirens": sirens, "radius_m": r["metres"], "radius_ft": r["feet"],
            "low": {c: sorted(v, key=lambda f: labels.get(f, {}).get("tract_label", f))
                    for c, v in low.items()},
            "outside": outside, "outside_text": bsl.OUTSIDE_RANGE,
            "low_text": state["meta"].get("low_range_text", bsl.LOW_RANGE),
            "share_word": state["meta"].get("share_word", "of people"),
            "dam_note": bsl.DAM_NOTE,
            "no_sirens": bsl.NO_SIRENS, "check_dam": bsl.CHECK_DAM}


def access_meta(access: dict | None) -> dict:
    if not access:
        return {}
    m = access["meta"]
    return {"source": m["source_text"], "attribution": m["attribution"],
            "times_note": m["times_note"], "no_walk": m["no_walk"], "limit": m["drive_limit_min"],
            "outside_method": m["outside_15_method"],
            "types": {**build_access.TYPE_LABEL, "childcare": bsl.CHILDCARE_LABEL},
            "no_activated": m["no_activated"], "not_no_shelter": m["not_no_shelter"],
            "outside_counts": {f"{c}|{h}": v for (c, h), v in
                               sorted(build_access.outside_counts(access).items())},
            "no_screen": NO_FACILITY_SCREEN, "zone_d": FACILITY_ZONE_D}


def tract_geometry(afn: dict, labels: dict | None = None, site_ids: dict | None = None,
                   access: dict | None = None) -> list:
    labels = labels or {}
    out = []
    for f in afn["features"]:
        rings = []
        for ring in svgmap.rings(f["geometry"]):
            if all(x < svgmap.MAIN_ISLANDS_WEST for x, _ in ring):
                continue
            flat = []
            for x, y in svgmap.simplify(ring, TOL):
                flat += [r4(x), r4(y)]
            rings.append(flat)
        if rings:
            fips = f["properties"]["tract_fips"]
            cx, cy = area_centroid(f["geometry"])
            out.append({"f": fips, "c": f["properties"]["county"],
                        "l": labels.get(fips, {}).get("tract_label", fips), "g": rings,
                        "p": [r4(cx), r4(cy)], "n": area_counts(f["properties"]),
                        "i": ISLANDS.get(("area", fips), ""),
                        **area_access(fips, site_ids or {}, access),
                        **({"sd": STATE["areas"][fips]["nearest_siren_ft"],
                            "sc": STATE["areas"][fips]["siren_share"]}
                           if STATE and fips in STATE["areas"] else {})})
    return out


def site_check(key: str) -> str:
    """Location check label: "Confirmed (2 sources)", "Needs review (546 m apart)", ..."""
    c = (ACCESS or {}).get("sites", {}).get(key)
    if not c:
        return ""
    return c["label"] + (f" ({c['distance_m']:,} m apart)" if c["status"] == "needs_review" else "")


def build(inp: dict) -> dict:
    require_summaries()
    match = {(s["county"], s["hazard"]): s for s in inp["match"]["scenarios"]}
    partners = partner_names(inp["partners"])
    sites, scenarios = {}, {}
    for c in COUNTIES:
        for h in HAZARDS:
            key = f"{c}|{h}"
            sc = scenario(inp, c, h)
            rows = tract_rows(inp, c, h)
            rates = inp["needs"]["planning_factors"]["shelter_seeking_rate"][h]
            ms = match[(c, h)]
            for s in sites_for(inp, c, h):
                site = sites.setdefault(s["name"] + "|" + c, {
                    "id": len(sites) + 1, "name": s["name"], "address": s["address"],
                    "county": c, "site_type": s["site_type"],
                    "times_opened_2026": s["times_opened_2026"],
                    "island": ISLANDS.get(("site", f"{s['name']}|{c}"), ""),
                    "lon": s["lon"] and r4(s["lon"]), "lat": s["lat"] and r4(s["lat"]),
                    "status": {}, "loc": site_check(s["name"] + "|" + c),
                    **({"dam": STATE["site_dam_zones"][s["name"] + "|" + c]}
                       if STATE and s["name"] + "|" + c in STATE["site_dam_zones"] else {})})
                site["status"][h] = [s["status"], plain_reason(s["reason"])]
            scenarios[key] = {
                "summary": {k: sc.get(k) for k in SCENARIO_FIELDS if k in sc},
                "tracts": {r["tract_fips"]: [round(float(r["at_risk_pop"])),
                                             round(float(r["shelter_demand"]), 1),
                                             round(sum(float(r[k]) for k in AFN_PARTS), 1)]
                           for r in rows},
                "largest": [{k: (round(v) if isinstance(v, float) else v) for k, v in x.items()}
                            for x in largest_communities(rows, rates)],
                "needs": [[lang_label(l["need"]), l["quantity"], l["unit"],
                           partner_text(l["lead_partner_types"], partners),
                           partner_text(l["support_partner_types"], partners),
                           l["pledged_capacity"],
                           "confirm with partner" if l["gap"].startswith("unknown") else l["gap"]]
                          for l in ms["needs"]],
                "priority_tracts": ms["priority_tracts"],
                "playbook": f"playbooks/{slug(c, h)}.pdf",
            }
    languages = {}
    for c in COUNTIES:
        sel = select_languages(inp["languages"].get(c, []), inp["comm"])
        languages[c] = {"area": area_label(sel[0]["area"]) if sel else "",
                        # every language in the PUMS summary: [label, people or null
                        # (too few to estimate), MOE or null, 1 = low reliability]
                        "all": [[lang_label(l["language"]), l["people"], l["moe"], int(l["low"])]
                                for l in all_languages(sel[0]["area"])] if sel else [],
                        "note": KAUAI_MAUI_NOTE if c in ("Kauai", "Maui") else "",
                        "rows": [[lang_label(l["language"]), l["speak_english_less_than_very_well"],
                                  l["moe_90"]] for l in sel]}
    decisions = {h: [[d["timing"], d["trigger"], d["issuer"], d["action"], d["owner_name"],
                      partner_text(d["support"], partners)] for d in inp["match"]["decision_points"][h]]
                 for h in HAZARDS}
    bundle = {
        "meta": {"data_as_of": inp["data_as_of"], "disclaimer": DISCLAIMER,
                 "decision_status": "Proposed – supports, does not replace, county plans.",
                 "role_status": "Proposed – to be confirmed with partner.",
                 "hurricane_scope_note": HURRICANE_SCOPE_NOTE,
                 "cols": COL, "cmist": CMIST, "rate_note": RATE_NOTE,
                 "footprint_text": FOOTPRINT_TEXT, "sources": SOURCE,
                 "site_key_status": SITE_KEY_STATUS, "need_names": svgmap.need_names(5),
                 "detail_keys": DETAIL_KEYS, "service_animals": SERVICE_ANIMALS,
                 "kalawao_note": KALAWAO_NOTE, "who_else": WHO_ELSE,
                 "lahaina_note": LAHAINA_NOTE, "lahaina_summary": LAHAINA_SUMMARY,
                 "messages_line": MESSAGES_LINE, "too_few": TOO_FEW,
                 "low_reliability": LOW_RELIABILITY, "cv_limit": CV_LIMIT,
                 "no_island_site": "No known usable site on this island for this hazard. The "
                                   "county designates shelters; follow county announcements.",
                 "niihau_note": dict(WHO_ELSE)["Niʻihau"],
                 "privacy": "Counts for whole Census areas and public facility names only. "
                            "No individual records."},
        "counties": [[c, COUNTY_LABEL[c]] for c in COUNTIES],
        "hazards": [[h, HAZARD_LABEL[h]] for h in HAZARDS],
        "status_labels": STATUS_LABEL,
        "tracts": tract_geometry(inp["afn"], inp.get("labels"),
                                 {k: v["id"] for k, v in sites.items()}, ACCESS),
        "facilities": facilities_bundle(ACCESS, STATE),
        "state": state_bundle(STATE, inp.get("labels") or {}),
        "access": access_meta(ACCESS),
        "sites": sorted(sites.values(), key=lambda s: s["id"]),
        "scenarios": scenarios,
        "decision_points": decisions,
        "languages": languages,
        # Every message row from data/sources/messages/, with a neutral review status
        "messages": message_library.bundle_messages(),
        "message_counts": message_library.message_counts(message_library.load_messages()),
        "message_languages": {c: [l["language"] for l in select_languages(
            inp["languages"].get(c, []), inp["comm"])] for c in COUNTIES},
        "reach": reach(inp),
        "county_lines": [{**r, "label": COUNTY_LINE_LABEL.get(r["line"], r["line"]),
                          "value": int(r["value"])} for r in inp["county_lines"]],
        "results": app_results(),
        "tsunami_zone": tsunami_overlay(),
        "area_fields": [k for k, _s in AREA_FIELDS],
        "official_map": OFFICIAL_MAP,
        "stress": stress_bundle({k: v["id"] for k, v in sites.items()}),
        "hub": hub_bundle(HUB, {k: v["id"] for k, v in sites.items()}),
        "whatif": whatif_bundle(inp),
        "provenance": {"numbers": PROV_NUMBERS, "shelters": PROV_SHELTERS,
                       "sources_url": message_library.SOURCES_URL},
    }
    body = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    h = hashlib.sha256(body.encode())
    for page in sorted(PLAYBOOKS.glob("*.html")):     # printable playbooks are planning data too
        h.update(page.name.encode())                   # (HTML: the PDFs carry a creation date)
        h.update(page.read_bytes().replace(b"\r\n", b"\n"))
    bundle["meta"]["version"] = h.hexdigest()[:12]
    return bundle


def app_results() -> dict:
    """Results shown in the app: Coverage and Backtest. The rebuild time and its baseline
    are quoted in PLAN.md §6 only, so they are not shipped in the bundle."""
    r = results_data()
    r = {k: v for k, v in r.items() if k not in ("rebuild", "baseline")}
    r["sources"] = {k: v for k, v in r["sources"].items() if k not in ("rebuild", "baseline")}
    return r


def reach(inp: dict) -> dict:
    """How to reach residents: channels and accessible formats (config/communication.json)."""
    names = partner_names(inp["partners"])
    owner = lambda o: ("County Emergency Management (each county)" if o == "county_em"  # noqa: E731
                       else names.get(o, o))
    return {"channels": [[c["description"], owner(c["owner"]),
                          partner_text("; ".join(c["support"]), names)]
                         for c in inp["comm"]["channels"]],
            "formats": inp["comm"].get("accessible_formats", {}).get("formats", [])}


def replace_block(text: str, start: str, end: str, new: str) -> str:
    pat = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pat.search(text):
        raise ValueError(f"marker {start!r} not found")
    return pat.sub(lambda _: f"{start}\n{new}\n{end}", text)


BINARY = (".pdf", ".png", ".ico")      # hashed as is; text files are hashed with LF endings


def precache_file(rel: str, app: Path = APP, playbooks: Path = PLAYBOOKS) -> Path:
    """The file behind a precache entry. PDFs are hashed from playbooks/ (the committed
    originals; app/playbooks/ holds identical copies and is gitignored)."""
    if rel == "./":
        return app / "index.html"
    if rel.startswith("playbooks/"):
        return playbooks / rel.split("/", 1)[1]
    return app / rel


def cache_version(precache: list, app: Path = APP, playbooks: Path = PLAYBOOKS) -> str:
    """Hash of every pre-cached file, so any change (data, PDF, app shell) gives the
    service worker a new cache. The generated index.html block is part of the hash.
    Text files are hashed with CRLF -> LF, so a Windows checkout gives the same VERSION
    as macOS and Linux (.gitattributes keeps LF in the repo)."""
    h = hashlib.sha256()
    for rel in precache:
        data = precache_file(rel, app, playbooks).read_bytes()
        if not rel.lower().endswith(BINARY):
            data = data.replace(b"\r\n", b"\n")
        h.update(rel.encode())
        h.update(data)
    return h.hexdigest()[:12]


def precache_list(app: Path = APP, playbooks: Path = PLAYBOOKS) -> list:
    """App shell + app/data/* + one entry per committed PDF playbook."""
    data_files = sorted(f"data/{p.name}" for p in (app / "data").iterdir() if p.is_file())
    return SHELL + data_files + [f"playbooks/{p.name}" for p in sorted(playbooks.glob("*.pdf"))]


def write_sw(app: Path = APP, playbooks: Path = PLAYBOOKS) -> tuple[list, str]:
    """Regenerate the VERSION and PRECACHE block in app/sw.js (written with LF endings)."""
    precache = precache_list(app, playbooks)
    version = cache_version(precache, app, playbooks)
    path = app / "sw.js"
    sw = path.read_bytes().decode("utf-8").replace("\r\n", "\n")
    sw = replace_block(sw, "// BEGIN GENERATED", "// END GENERATED",
                       f"const VERSION = {json.dumps(version)};\n"
                       f"const PRECACHE = {json.dumps(precache, indent=2)};")
    path.write_bytes(sw.encode("utf-8"))
    return precache, version


def sw_version(app: Path = APP) -> str:
    """The VERSION currently written in app/sw.js."""
    m = re.search(r'const VERSION = "([0-9a-f]+)";', (app / "sw.js").read_text(encoding="utf-8"))
    return m.group(1) if m else ""


def copy_playbooks(src: Path = PLAYBOOKS, app: Path = APP) -> list:
    """Copy the committed PDF playbooks into the app (build artifact, not committed)."""
    (app / "playbooks").mkdir(parents=True, exist_ok=True)
    for old in (app / "playbooks").glob("*.pdf"):
        old.unlink()
    pdfs = sorted(src.glob("*.pdf"))
    for p in pdfs:
        shutil.copy2(p, app / "playbooks" / p.name)
    return pdfs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the offline app data bundle")
    ap.add_argument("--copy-only", action="store_true",
                    help="app-only step: copy playbooks/*.pdf into app/playbooks and refresh "
                         "the service worker VERSION from the committed bundle (no data/raw/)")
    ap.add_argument("--allow-missing-raw", action="store_true",
                    help="only with --copy-only: state that data/raw/ may be absent")
    args = ap.parse_args(argv)
    if args.allow_missing_raw and not args.copy_only:
        ap.error("--allow-missing-raw is only for --copy-only; the full build needs data/raw/")
    if args.copy_only:
        for name in ("bundle.json", "version.json"):
            if not (DATA / name).is_file():
                print(f"Missing committed app/data/{name}; --copy-only never regenerates data.",
                      file=sys.stderr)
                return 1
        pdfs = copy_playbooks()
        precache, version = write_sw()
        print(f"Copied {len(pdfs)} PDF playbooks -> app/playbooks/; "
              f"app/sw.js VERSION {version} ({len(precache)} files, committed bundle reused)")
        return 0
    try:
        inp = load_inputs()
        bundle = build(inp)
    except MissingInput as e:
        print(e, file=sys.stderr)
        return 1
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "bundle.json").write_text(json.dumps(bundle, ensure_ascii=False,
                                                 separators=(",", ":")), encoding="utf-8")
    version = {"version": bundle["meta"]["version"], "data_as_of": inp["data_as_of"]}
    (DATA / "version.json").write_text(json.dumps(version), encoding="utf-8")

    pdfs = copy_playbooks()

    links = "\n".join(
        f'<li>{escape(COUNTY_LABEL[c])}: ' + " · ".join(
            f'<a href="playbooks/{slug(c, h)}.pdf">{escape(HAZARD_LABEL[h])}</a>'
            for h in HAZARDS) + "</li>" for c in COUNTIES)
    idx = (APP / "index.html").read_text(encoding="utf-8")
    for marker in ("PDF LINKS", "FOOTER PDF LINKS"):       # <noscript> list and footer list
        idx = replace_block(idx, f"<!-- BEGIN GENERATED {marker} -->",
                            f"<!-- END GENERATED {marker} -->", f"<ul>\n{links}\n</ul>")
    (APP / "index.html").write_text(idx, encoding="utf-8", newline="\n")

    precache, _version = write_sw()

    size = (DATA / "bundle.json").stat().st_size
    pdf_size = sum(p.stat().st_size for p in pdfs)
    print(f"app/data/bundle.json: {size / 1024:.0f} KB ({len(bundle['tracts'])} tracts, "
          f"{len(bundle['sites'])} sites, {len(bundle['scenarios'])} scenarios); "
          f"version {bundle['meta']['version']}, data as of {inp['data_as_of']}")
    print(f"Precache: {len(precache)} files, PDFs {pdf_size / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
