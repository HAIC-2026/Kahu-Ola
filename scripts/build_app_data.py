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

Usage:  python3 scripts/build_app_data.py    (after build_playbooks.py)
        python3 scripts/build_app_data.py --copy-only
            (deploy step, e.g. Cloudflare Pages: only copy playbooks/*.pdf into app/playbooks/)
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
from build_playbooks import (AFN_PARTS, CMIST, COL, COUNTY_LABEL, COUNTY_LINE_LABEL,  # noqa: E402
                             DETAIL_KEYS, DISCLAIMER, KALAWAO_NOTE, SERVICE_ANIMALS, WHO_ELSE,
                             results_data, NO_FACILITY_SCREEN, FACILITY_ZONE_D, LAHAINA_NOTE, LAHAINA_SUMMARY,
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
SHELL = ["./", "index.html", "app.js", "styles.css", "manifest.webmanifest", "icon.svg",
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


def tsunami_overlay(path: Path = ROOT / "data" / "raw" / "tsunami_zone.geojson") -> dict:
    """State tsunami evacuation zone outline, simplified, by county (build time only)."""
    if not path.exists():
        return {}
    out = {}
    for f in json.loads(path.read_text(encoding="utf-8"))["features"]:
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
    return out


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
        "results": results_data(),
        "tsunami_zone": tsunami_overlay(),
        "area_fields": [k for k, _s in AREA_FIELDS],
        "official_map": OFFICIAL_MAP,
        "provenance": {"numbers": PROV_NUMBERS, "shelters": PROV_SHELTERS,
                       "sources_url": message_library.SOURCES_URL},
    }
    body = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    bundle["meta"]["version"] = hashlib.sha256(body.encode()).hexdigest()[:12]
    return bundle


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


def cache_version(precache: list) -> str:
    """Hash of every pre-cached file, so any change (data, PDF, app shell) gives the
    service worker a new cache. The generated index.html block is part of the hash."""
    h = hashlib.sha256()
    for rel in precache:
        f = APP / ("index.html" if rel == "./" else rel)
        h.update(rel.encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:12]


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
                    help="only copy playbooks/*.pdf into app/playbooks (deploy step)")
    args = ap.parse_args(argv)
    if args.copy_only:
        print(f"Copied {len(copy_playbooks())} PDF playbooks -> app/playbooks/")
        return 0
    inp = load_inputs()
    bundle = build(inp)
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
    (APP / "index.html").write_text(idx, encoding="utf-8")

    data_files = sorted(f"data/{p.name}" for p in DATA.iterdir() if p.is_file())
    precache = SHELL + data_files + [f"playbooks/{p.name}" for p in pdfs]
    sw = (APP / "sw.js").read_text(encoding="utf-8")
    sw = replace_block(sw, "// BEGIN GENERATED", "// END GENERATED",
                       f"const VERSION = {json.dumps(cache_version(precache))};\n"
                       f"const PRECACHE = {json.dumps(precache, indent=2)};")
    (APP / "sw.js").write_text(sw, encoding="utf-8")

    size = (DATA / "bundle.json").stat().st_size
    pdf_size = sum(p.stat().st_size for p in pdfs)
    print(f"app/data/bundle.json: {size / 1024:.0f} KB ({len(bundle['tracts'])} tracts, "
          f"{len(bundle['sites'])} sites, {len(bundle['scenarios'])} scenarios); "
          f"version {bundle['meta']['version']}, data as of {inp['data_as_of']}")
    print(f"Precache: {len(precache)} files, PDFs {pdf_size / 1024 / 1024:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
