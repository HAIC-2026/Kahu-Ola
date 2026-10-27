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

Usage:  python3 scripts/build_app_data.py    (after build_playbooks.py)
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import sys
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import svgmap  # noqa: E402
from build_playbooks import (AFN_PARTS, COUNTY_LABEL, DISCLAIMER, HAZARD_LABEL,  # noqa: E402
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
SHELL = ["./", "index.html", "app.js", "styles.css", "manifest.webmanifest", "icon.svg"]
SCENARIO_FIELDS = ("at_risk_pop", "shelter_demand_low", "shelter_demand_central",
                   "shelter_demand_high", "rate_low", "rate_central", "rate_high",
                   "C_lep_at_risk", "M_power_dependent_at_risk", "I_disability_at_risk",
                   "I_age65_at_risk", "T_no_vehicle_persons_at_risk", "tracts_at_risk",
                   "footprint_rule", "scope", "known_sites_usable", "known_sites_check_flood",
                   "known_sites_flood_undetermined", "candidate_schools_usable",
                   "candidate_schools_flood_undetermined", "at_risk_pop_extreme_zone")


def r4(v: float) -> float:
    return round(v, 4)


def tract_geometry(afn: dict) -> list:
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
            out.append({"f": f["properties"]["tract_fips"], "c": f["properties"]["county"],
                        "g": rings})
    return out


def build(inp: dict) -> dict:
    match = {(s["county"], s["hazard"]): s for s in inp["match"]["scenarios"]}
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
                    "lon": s["lon"] and r4(s["lon"]), "lat": s["lat"] and r4(s["lat"]),
                    "status": {}})
                site["status"][h] = [s["status"], s["reason"]]
            scenarios[key] = {
                "summary": {k: sc.get(k) for k in SCENARIO_FIELDS if k in sc},
                "tracts": {r["tract_fips"]: [round(float(r["at_risk_pop"])),
                                             round(float(r["shelter_demand"]), 1),
                                             round(sum(float(r[k]) for k in AFN_PARTS), 1)]
                           for r in rows},
                "largest": [{k: (round(v) if isinstance(v, float) else v) for k, v in x.items()}
                            for x in largest_communities(rows, rates)],
                "needs": [[l["need"], l["quantity"], l["unit"], l["lead_partner_types"],
                           l["support_partner_types"], l["pledged_capacity"],
                           "confirm with partner" if l["gap"].startswith("unknown") else l["gap"]]
                          for l in ms["needs"]],
                "priority_tracts": ms["priority_tracts"],
                "playbook": f"playbooks/{slug(c, h)}.pdf",
            }
    languages = {}
    for c in COUNTIES:
        sel = select_languages(inp["languages"].get(c, []), inp["comm"])
        languages[c] = {"area": sel[0]["area"] if sel else "",
                        "note": KAUAI_MAUI_NOTE if c in ("Kauai", "Maui") else "",
                        "rows": [[l["language"], l["speak_english_less_than_very_well"],
                                  l["moe_90"]] for l in sel]}
    decisions = {h: [[d["timing"], d["trigger"], d["issuer"], d["action"], d["owner_name"],
                      d["support"]] for d in inp["match"]["decision_points"][h]]
                 for h in HAZARDS}
    bundle = {
        "meta": {"data_as_of": inp["data_as_of"], "disclaimer": DISCLAIMER,
                 "decision_status": "Proposed – supports, does not replace, county plans.",
                 "role_status": "Proposed – to be confirmed with partner.",
                 "privacy": "Aggregate census-tract data and public facility names only. "
                            "No individual records."},
        "counties": [[c, COUNTY_LABEL[c]] for c in COUNTIES],
        "hazards": [[h, HAZARD_LABEL[h]] for h in HAZARDS],
        "status_labels": STATUS_LABEL,
        "tracts": tract_geometry(inp["afn"]),
        "sites": sorted(sites.values(), key=lambda s: s["id"]),
        "scenarios": scenarios,
        "decision_points": decisions,
        "languages": languages,
    }
    body = json.dumps(bundle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    bundle["meta"]["version"] = hashlib.sha256(body.encode()).hexdigest()[:12]
    return bundle


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


def main() -> int:
    inp = load_inputs()
    bundle = build(inp)
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / "bundle.json").write_text(json.dumps(bundle, ensure_ascii=False,
                                                 separators=(",", ":")), encoding="utf-8")
    version = {"version": bundle["meta"]["version"], "data_as_of": inp["data_as_of"]}
    (DATA / "version.json").write_text(json.dumps(version), encoding="utf-8")

    (APP / "playbooks").mkdir(exist_ok=True)
    for old in (APP / "playbooks").glob("*.pdf"):
        old.unlink()
    pdfs = sorted(PLAYBOOKS.glob("*.pdf"))
    for p in pdfs:
        shutil.copy2(p, APP / "playbooks" / p.name)

    links = "\n".join(
        f'<li>{escape(COUNTY_LABEL[c])}: ' + " · ".join(
            f'<a href="playbooks/{slug(c, h)}.pdf">{escape(HAZARD_LABEL[h])}</a>'
            for h in HAZARDS) + "</li>" for c in COUNTIES)
    idx = (APP / "index.html").read_text(encoding="utf-8")
    idx = replace_block(idx, "<!-- BEGIN GENERATED PDF LINKS -->",
                        "<!-- END GENERATED PDF LINKS -->", f"<ul>\n{links}\n</ul>")
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
