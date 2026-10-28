#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – Step 4: MATCH.

DHS ESF-6 part 3: match the MODEL's needs to partner resources, with proposed roles,
decision points and communication pathways, for every county x hazard scenario.

  * one line per need -> proposed lead + support partner types -> pledged capacity
    (blank until a partner fills config/partners.json) -> gap
  * decision points per hazard: official NWS / PTWC / CPHC trigger, timing, action, owner
  * communication pathways per county: top languages (ACS C16001), channels, and the
    pre-approved multilingual message library (data/sources/messages/)
  * top 10 tracts per county x hazard by AFN need, for priority outreach (tract counts)

Offline and deterministic: reads only local files, no network, no AI. Every role and
action is a proposal that supports, and does not replace, county plans.

Usage:  python3 scripts/match.py      (after model_needs.py and fetch_languages.py)
Outputs: data/processed/match_plan.json, data/processed/match_plan.csv (need lines)
"""
from __future__ import annotations

import csv
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import COUNTIES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config"
PROC = ROOT / "data" / "processed"
SOURCES = ROOT / "data" / "sources"
UNKNOWN_GAP = "unknown – confirm with partner"
TOP_TRACTS = 10
AFN_PARTS = ("M_power_dependent_at_risk", "I_disability_at_risk", "C_lep_at_risk",
             "T_no_vehicle_persons_at_risk")

# need, functions (first = lead function), needs_by_scenario field, unit, basis,
# (capacity function, capacity field) that a partner pledge is compared against.
NEEDS = [
    ("Cots / sleeping space", ["shelter_operations"], "cots", "cots",
     "1 per person in shelter (central estimate)", ("shelter_operations", "cots")),
    ("Floor space (≤72 h)", ["shelter_operations"], "floor_sqft_72h", "sq ft",
     "Florida DEM (2010): 20 sq ft per person", ("shelter_operations", "floor_sqft")),
    ("Floor space (≤2 weeks)", ["shelter_operations"], "floor_sqft_2wk", "sq ft",
     "Florida DEM (2010): 40 sq ft per person", ("shelter_operations", "floor_sqft")),
    ("Water", ["feeding"], "water_gal_per_day", "gal/day",
     "Florida DEM (2010): 1 gal per person per day", ("feeding", "water_gal_per_day")),
    ("Meals", ["feeding"], "meals_per_day", "meals/day",
     "Florida DEM (2010): 2 meals per person per day", ("feeding", "meals_per_day")),
    ("Toilets (≤72 h)", ["shelter_operations"], "toilets_72h", "toilets",
     "Florida DEM (2010): 1 per 40 persons", ("shelter_operations", "toilets")),
    ("Toilets (≤2 weeks)", ["shelter_operations"], "toilets_2wk", "toilets",
     "Florida DEM (2010): 1 per 20 persons", ("shelter_operations", "toilets")),
    ("Shelter staff", ["shelter_operations", "donations_volunteers"], "staff_per_shift",
     "staff per shift", "Florida DEM (2010) staffing ratios, incl. children's area 1:12",
     ("shelter_operations", "staff_per_shift")),
    ("Power outlets for power-dependent residents", ["power_medical_devices"],
     "power_outlets", "outlets",
     "1 per power-dependent person in shelter (team_assumption; emPOWER-based estimate)",
     ("power_medical_devices", "power_outlets")),
    ("Accessible transport", ["transportation"], "T_no_vehicle_persons_at_risk",
     "people in no-vehicle households at risk",
     "ACS via CDC SVI; outreach upper bound, not all will need a ride", None),
    ("Pet space – dog households", ["pets"], "dog_households", "households with a dog",
     "AVMA (2020 data): 44.6% of households", None),
    ("Pet space – cat households", ["pets"], "cat_households", "households with a cat",
     "AVMA (2020 data): 26% of households", None),
    ("Children's area", ["shelter_operations", "afn_support_medical"], "S_children_in_shelter",
     "children in shelter", "tract share age 17 and under; staff counted in Shelter staff",
     None),
]


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


# ---------------------------------------------------------------- partners

def partners_for(partners: list, function: str, county: str) -> dict:
    """{'lead': [...], 'support': [...]} partner types for one function in one county."""
    out = {"lead": [], "support": []}
    for p in partners:
        if p.get("county") and p["county"] != county:
            continue
        for f in p["functions"]:
            if f["function"] == function and p["partner_type"] not in out[f["role"]]:
                out[f["role"]].append(p["partner_type"])
    return out


def pledged(partners: list, cap: tuple | None, county: str):
    """Sum of partner pledges for (function, field) in a county, or None if none filled.
    A county-scoped partner may pledge a number; a state/statewide partner must pledge
    a {county: number} mapping so statewide capacity is never counted twice."""
    if not cap:
        return None
    fn, field = cap
    total, found = 0.0, False
    for p in partners:
        if p.get("county") and p["county"] != county:
            continue
        v = (p.get("capacity") or {}).get(fn, {}).get(field)
        if isinstance(v, dict):
            v = v.get(county)
        elif p.get("county") is None:
            v = None
        if isinstance(v, (int, float)):
            total, found = total + v, True
    return total if found else None


def gap_text(quantity: float, pledge) -> str:
    if pledge is None:
        return UNKNOWN_GAP
    short = quantity - pledge
    return f"shortfall {round(short):,}" if short > 0 else "covered"


# ---------------------------------------------------------------- languages

def load_languages(path: Path = SOURCES / "languages_by_county.csv") -> dict:
    """county -> unsuppressed languages ranked by limited-English speakers (ACS PUMS).
    An area may cover several counties (Kauai + Maui share PUMA 00100): each county
    gets the area's list, labelled with the area."""
    out = {c: [] for c in COUNTIES}
    if not path.exists():
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["suppressed"] == "True":
                continue
            for c in r["counties"].split(";"):
                if c in out:
                    out[c].append({
                        "language": r["language"], "area": r["area"],
                        "speak_english_less_than_very_well": int(r["speak_english_less_than_very_well"]),
                        "moe_90": int(r["moe_90"]),
                        "share_of_area_lep": float(r["share_of_area_lep"]),
                        "rank": int(r["rank"]),
                    })
    for c in out:
        out[c].sort(key=lambda x: x["rank"])
    return out


def select_languages(langs: list, comm: dict) -> list:
    """Top N by limited-English speakers, plus the always-include languages
    (Hawaiian, Chuukese, Marshallese) wherever they are above the suppression threshold."""
    top = langs[:comm["top_languages_per_county"]]
    names = {l["language"] for l in top}
    extra = [l for l in langs if l["language"] in comm.get("always_include_if_not_suppressed", [])
             and l["language"] not in names]
    return top + extra


# ---------------------------------------------------------------- needs

def need_lines(sc: dict, partners: list, languages: list) -> list:
    """languages: the county's selected languages (select_languages)."""
    county, hazard = sc["county"], sc["hazard"]
    rows = []

    def add(need, functions, qty, unit, basis, cap, language=""):
        lead = partners_for(partners, functions[0], county)
        support = list(lead["support"])
        for fn in functions[1:]:
            other = partners_for(partners, fn, county)
            support += [t for t in other["lead"] + other["support"]
                        if t not in support and t not in lead["lead"]]
        pl = pledged(partners, cap, county)
        rows.append({
            "county": county, "hazard": hazard, "need": need, "language": language,
            "quantity": round(qty), "unit": unit, "basis": basis,
            "function": functions[0],
            "lead_partner_types": "; ".join(lead["lead"]),
            "support_partner_types": "; ".join(support),
            "pledged_capacity": "" if pl is None else round(pl),
            "gap": gap_text(qty, pl),
            "status": "proposed – to be confirmed with partner",
        })

    for need, functions, field, unit, basis, cap in NEEDS:
        add(need, functions, float(sc.get(field) or 0), unit, basis, cap)
    lep = float(sc.get("C_lep_in_shelter") or 0)
    for lang in languages:
        add(f"Interpreters – {lang['language']}", ["language_access"],
            lep * lang["share_of_area_lep"], "people with limited English in shelter",
            f"CDC SVI limited-English share x ACS PUMS 2019-2023 language mix ({lang['area']}); "
            "interpreter ratio not sourced – partner to set", None, lang["language"])
    return rows


# ---------------------------------------------------------------- decision points

def decision_table(dp_cfg: dict, hazard: str, partners: list) -> list:
    names = {p["partner_type"]: p["name"] for p in partners}
    order = {t: i for i, t in enumerate(dp_cfg["timing_order"])}
    out = []
    for d in sorted(dp_cfg["decision_points"].get(hazard, []),
                    key=lambda d: order[d["timing"]]):
        t = dp_cfg["triggers"][d["trigger"]]
        out.append({
            "hazard": hazard, "timing": d["timing"], "trigger": t["product"],
            "issuer": t["issuer"], "trigger_definition": t["definition"],
            "trigger_source": t["url"], "action": d["action"],
            "owner": d["owner"],
            "owner_name": "County Emergency Management (each county)"
            if d["owner"] == "county_em" else names.get(d["owner"], d["owner"]),
            "support": "; ".join(d["support"]), "status": d["status"],
        })
    return out


# ---------------------------------------------------------------- communication

def ensure_message_library(languages: dict, comm: dict, root: Path = ROOT) -> list:
    """Header-only template files per selected language; existing files are never
    overwritten. Files for languages no longer selected are removed only while they are
    header-only: a file holding any template rows is always kept."""
    lib = root / comm["message_library"]["dir"]
    lib.mkdir(parents=True, exist_ok=True)
    langs = ["English"] + sorted({l["language"] for ls in languages.values()
                                  for l in select_languages(ls, comm)})
    keep = {f"{slug(l)}.csv" for l in langs}
    for p in sorted(lib.glob("*.csv")):
        if p.name not in keep:
            with open(p, newline="", encoding="utf-8") as fh:
                if not list(csv.DictReader(fh)):
                    p.unlink()
    out = []
    for lang in langs:
        p = lib / f"{slug(lang)}.csv"
        if not p.exists():
            with open(p, "w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerow(comm["message_library"]["columns"])
        with open(p, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        approved = sum(1 for r in rows if (r.get("approved") or "").lower() == "yes"
                       and r.get("reviewed_by"))
        out.append({"language": lang, "file": str(p.relative_to(root)),
                    "templates": len(rows), "approved_templates": approved})
    return out


def communication(languages: dict, comm: dict, library: list) -> dict:
    by_lang = {l["language"]: l for l in library}
    out = {}
    for c in COUNTIES:
        top = select_languages(languages.get(c, []), comm)
        out[c] = {
            "language_area": top[0]["area"] if top else "",
            "top_languages_lep": [dict(l, approved_templates=by_lang.get(
                l["language"], {}).get("approved_templates", 0)) for l in top],
            "channels": comm["channels"],
            "message_library_status": "no approved templates yet"
            if not any(by_lang.get(l["language"], {}).get("approved_templates")
                       for l in top) else "some approved templates",
            "status": comm["status"],
        }
    return out


# ---------------------------------------------------------------- priority tracts

def priority_tracts(tract_rows: list, county: str, hazard: str, n: int = TOP_TRACTS) -> list:
    mine = [r for r in tract_rows if r["county"] == county and r["hazard"] == hazard]
    scored = []
    for r in mine:
        parts = {k: float(r.get(k) or 0) for k in AFN_PARTS}
        scored.append((round(sum(parts.values()), 1), r["tract_fips"], r, parts))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [{"rank": i, "tract_fips": fips, "tract_label": r.get("tract_label") or fips,
             "label_main": r.get("label_main") or r.get("tract_label") or fips,
             "label_sub": r.get("label_sub", ""),
             "at_risk_pop": round(float(r["at_risk_pop"])),
             "power_dependent": round(p["M_power_dependent_at_risk"]),
             "disability": round(p["I_disability_at_risk"]),
             "limited_english": round(p["C_lep_at_risk"]),
             "no_vehicle": round(p["T_no_vehicle_persons_at_risk"]),
             "afn_need_sum": score}
            for i, (score, fips, r, p) in enumerate(scored[:n], 1)]


# ---------------------------------------------------------------- run

def run(needs: dict, tract_rows: list, partners_cfg: dict, dp_cfg: dict, comm: dict,
        languages: dict, shelters: list, library: list) -> dict:
    partners = partners_cfg["partners"]
    scenarios, lines = [], []
    for sc in needs["scenarios"]:
        c, hz = sc["county"], sc["hazard"]
        nl = need_lines(sc, partners, select_languages(languages.get(c, []), comm))
        lines += nl
        scenarios.append({
            "county": c, "hazard": hz, "scope": sc.get("scope", ""),
            "shelter_demand_low": sc["shelter_demand_low"],
            "shelter_demand_central": sc["shelter_demand_central"],
            "shelter_demand_high": sc["shelter_demand_high"],
            "known_sites_usable": sc.get("known_sites_usable"),
            "known_sites_check_flood": sc.get("known_sites_check_flood"),
            "known_sites_flood_undetermined": sc.get("known_sites_flood_undetermined"),
            "known_sites_opened_2026": sum(1 for f in shelters
                                           if f["properties"]["county"] == c),
            "needs": nl,
            "priority_tracts": priority_tracts(tract_rows, c, hz),
        })
    hazards = list(dict.fromkeys(s["hazard"] for s in needs["scenarios"]))
    return {
        "title": "Hawaiʻi ESF-6 MATCH plan: needs x partner roles, decision points, "
                 "communication pathways",
        "status": "proposed – supports, does not replace, county plans. Roles are "
                  "proposed – to be confirmed with partner.",
        "privacy": "Aggregate tract and county estimates only. No individual records.",
        "inputs_built_at": needs.get("built_at"),
        "sources": {"partners": partners_cfg["source"],
                    "triggers": {k: v["url"] for k, v in dp_cfg["triggers"].items() if v["url"]},
                    "languages": "data/sources/languages_by_county.csv (ACS C16001)"},
        "scenarios": scenarios,
        "decision_points": {hz: decision_table(dp_cfg, hz, partners) for hz in hazards},
        "communication": communication(languages, comm, library),
        "message_library": library,
    }


def main() -> int:
    needs = load_json(PROC / "needs_by_scenario.json")
    partners_cfg = load_json(CONFIG / "partners.json")
    dp_cfg = load_json(CONFIG / "decision_points.json")
    comm = load_json(CONFIG / "communication.json")
    if not all((needs, partners_cfg, dp_cfg, comm)):
        print("Missing inputs: run model_needs.py; check config/partners.json, "
              "decision_points.json, communication.json", file=sys.stderr)
        return 1
    with open(PROC / "needs_by_tract.csv", newline="", encoding="utf-8") as fh:
        tract_rows = list(csv.DictReader(fh))
    languages = load_languages()
    shelters = (load_json(PROC / "shelters_2026.geojson") or {}).get("features", [])
    library = ensure_message_library(languages, comm)
    plan = run(needs, tract_rows, partners_cfg, dp_cfg, comm, languages, shelters, library)

    (PROC / "match_plan.json").write_text(json.dumps(plan, indent=1, ensure_ascii=False),
                                          encoding="utf-8")
    lines = [l for s in plan["scenarios"] for l in s["needs"]]
    with open(PROC / "match_plan.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(lines[0]))
        w.writeheader()
        w.writerows(lines)

    print(f"Matched {len(plan['scenarios'])} scenarios, {len(lines)} need lines -> "
          f"data/processed/match_plan.json / .csv")
    print(f"Message library: {len(library)} languages, "
          f"{sum(l['approved_templates'] for l in library)} approved templates")
    for c in COUNTIES:
        top = plan["communication"][c]["top_languages_lep"][:3]
        print(f"  {c:<10}" + "; ".join(f"{l['language']} {l['speak_english_less_than_very_well']:,}"
                                       for l in top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
