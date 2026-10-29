#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – printable ESF-6 playbooks, one per county x hazard.

Writes playbooks/<county>_<hazard>.html and .pdf (4 x 5 = 20) plus playbooks/index.html.
Print-first: US Letter, black-and-white safe (shapes and text labels, never color alone),
system fonts only, inline SVG maps (no tiles, no CDN, no web fonts, no network).

PDF: a local headless browser prints each HTML file (CHROME_BIN, Playwright's cached
Chromium, or Google Chrome); WeasyPrint is the fallback. With --html-only, PDFs are skipped.

Usage:  python3 scripts/build_playbooks.py [--html-only]
        (after model_needs.py, match.py and build_languages_pums.py)
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import svgmap  # noqa: E402
from fetch_data import COUNTIES  # noqa: E402
from fetch_flood_zones import CACHE as FLOOD_CACHE, LAYER_URL as FLOOD_URL  # noqa: E402
from match import load_languages, select_languages  # noqa: E402
from build_tract_labels import load_labels  # noqa: E402
from message_library import LANG_LABEL  # noqa: E402
from hawaii_time import hst_date  # noqa: E402
from model_needs import FLOOD, HAZARDS, site_status  # noqa: E402
import build_access  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
CONFIG = ROOT / "config"
OUT = ROOT / "playbooks"

DISCLAIMER = ("Planning aid. Supports, does not replace, county emergency plans. "
              "Not an official shelter list.")
COUNTY_LABEL = {"Kauai": "Kauaʻi", "Honolulu": "Honolulu", "Maui": "Maui", "Hawaii": "Hawaiʻi"}
HAZARD_LABEL = {"hurricane": "Hurricane", "wildfire": "Wildfire", "tsunami": "Tsunami",
                "inland_flood": "Inland flooding", "coastal_flood": "Coastal flooding"}
STATUS_LABEL = {"ok": "✓ Usable", "check": "⚠ Check flood zone",
                "check (tract-level)": "⚠ Check flood zone (no site flood data)",
                "undetermined": "? Flood risk not mapped", "exclude": "✕ Not for this hazard"}
SITE_KEY_STATUS = {"ok": "usable", "check": "check flood zone",
                   "check (tract-level)": "check flood zone", "undetermined": "flood risk not mapped",
                   "exclude": "not for this hazard", "unlocated": "not on map"}

# Plain-language wording shared by the playbooks and the app (build_app_data.py).
COL = {
    "area": "Community (Census area)",
    "at_risk": "People in the risk area",
    "shelter": "May need a public shelter (low – likely – high)",
    "lep": "Speak English less than well",
    "power": "Use power-dependent medical equipment (estimate)",
    "disability": "People with a disability",
    "age65": "Age 65 and older",
    "no_car": "People in households without a car",
    "needs_total": "Needs total (a person can be in more than one column)",
    "hearing": "Hearing difficulty",
    "vision": "Vision difficulty",
    "cognitive": "Cognitive difficulty (memory, decisions)",
    "age65_alone": "Age 65 and older, living alone",
    "highrise": "Homes in buildings with 10+ units: may lose elevator and AC in a long power outage",
}
DETAIL_KEYS = [("hearing", "C_hearing_at_risk", "C"), ("vision", "C_vision_at_risk", "C"),
               ("cognitive", "I_cognitive_at_risk", "I"), ("age65_alone", "S_age65_alone_at_risk", "S")]
SERVICE_ANIMALS = "Service animals stay with their handler (ADA); not counted as pets."
KALAWAO_NOTE = "Kalawao County (Kalaupapa, Molokaʻi) is planned with Maui County."
WHO_ELSE = [
    ("Domestic-violence survivors", "Served through confidential providers; no counts by design."),
    ("Off-grid households", "No public Census-area data; county and health partners to supply."),
    ("People on dialysis or receiving home care",
     "No public Census-area data; county and health partners to supply."),
    ("Earthquake", "Not modeled; listed as a limitation in the plan."),
    ("Caregivers and personal care attendants",
     "Stay with the person they support; count them for cots, meals and space."),
    ("Behavioral health", "Mental-health staff at each shelter (ratio: {SOURCES})."),
    ("Niʻihau", "Privately owned island, no public shelter; plan with the landowner and "
                "Kauaʻi County."),
    ("Families afraid to seek shelter (including immigrant families)",
     "The county publishes who may use shelters; trusted community messengers share it."),
]
COUNTY_LINE_LABEL = {"homelessness": "People experiencing homelessness (Point-in-Time count)",
                     "visitors": "Visitors on island (average per day)"}
FOOTPRINT_TEXT = {
    "all tracts": "every Census area in the county",
    "share inside tsunami zone": "the people living inside the tsunami evacuation zone",
    "top 25% of each county's tracts by NRI score":
        "the 25% of Census areas in the county with the highest FEMA risk score for this hazard",
}
RATE_NOTE = {
    "hurricane": "South Carolina Emergency Management Division hurricane shelter planning "
                 "factors (2%, 3%, 5%).",
    "wildfire": "High = the share of Lahaina residents in shelters the day after the 2023 fire "
                "(1,418 of 12,702 people). Low and likely are team assumptions.",
    "tsunami": "Team assumptions: likely 5%; low 2% (the hurricane planning factor); high 11% "
               "(the Lahaina 2023 rate).",
}
RATE_NOTE["inland_flood"] = RATE_NOTE["coastal_flood"] = RATE_NOTE["tsunami"]
SOURCE = {
    "people": "Source: people and needs – CDC/ATSDR Social Vulnerability Index 2022 (ACS "
              "2018–2022 estimates), HHS emPOWER and FEMA National Risk Index v1.20; community "
              "names – 2020 Census blocks and places, spellings from USGS GNIS.",
    "summary": "Source: CDC/ATSDR Social Vulnerability Index 2022 (ACS 2018–2022 estimates), "
               "HHS emPOWER, FEMA National Risk Index v1.20; shelter rates: {SOURCES}.",
    "sites": "Source: county announcements of sites opened in 2026; FEMA flood zones (Hawaiʻi "
             "Statewide GIS, State DFIRM); tsunami evacuation zones (Hawaiʻi Statewide GIS).",
    "needs": "Source: likely estimate × planning factors ({SOURCES}; Florida Division of "
             "Emergency Management 2010; AVMA (2020 data) for pets).",
    "decisions": "Source: National Weather Service, Central Pacific Hurricane Center and "
                 "Pacific Tsunami Warning Center product definitions (links: {SOURCES}).",
    "languages": "Source: ACS PUMS 2019–2023 5-year (validated against the DBEDT State of "
                 "Hawaiʻi Data Book 2024, Table 1.44).",
    "detail": "Source: ACS 2020–2024 5-year Census-area tables B18102 (hearing), B18103 "
              "(vision), B18104 (cognitive) and B09020 (age 65 and older living alone), times the share "
              "of each area in the risk area; homes in 10+ unit buildings: CDC/ATSDR SVI 2022 "
              "(E_MUNIT, housing units).",
    "county_lines": "Source: Point-in-Time counts – Bridging the Gap 2026 report (Hawaiʻi, "
                    "Maui, Kauaʻi; night of Jan 25, 2026) and Partners In Care 2026 count for "
                    "Oʻahu as released by the City and County of Honolulu; visitors – DBEDT "
                    "State of Hawaiʻi Data Book 2025, Table 7.06. Details: {SOURCES}.",
    "access": f"{build_access.SOURCE_TEXT} {build_access.ATTRIBUTION}",
    "facilities": "Source: CMS Provider Data Catalog (dialysis facilities, nursing homes, "
                  "hospitals; facility addresses only), located with Esri ArcGIS World Geocoder; "
                  "zones: State tsunami evacuation zone and FEMA flood zones (Hawaiʻi Statewide "
                  "GIS, State DFIRM).",
    "reach": "Source: proposed channels and formats in the plan's communication pathways – "
             "supports, does not replace, county and State public-information plans.",
}
SOURCES_TOKEN = "{SOURCES}"            # PDFs: "section 8"; app: a "see Sources" link


def src_text(key: str) -> str:
    """Source line for the printed playbook."""
    return SOURCE[key].replace(SOURCES_TOKEN, "section 8")


AREA_DISPLAY = {"Kauai + Maui": "Kauaʻi + Maui", "Hawaii": "Hawaiʻi", "Kauai": "Kauaʻi"}


def area_label(area: str) -> str:
    return AREA_DISPLAY.get(area, area)


def lang_label(text: str) -> str:
    """Readable language names inside any label (e.g. a need name)."""
    for raw, shown in LANG_LABEL.items():
        text = text.replace(raw, shown)
    return text


RULE_TEXT = {"all": "Every Census area",
             "tsunami_zone_share": "Share living inside the tsunami evacuation zone",
             "nri_top_share_by_county": "Top {share} of Census areas by FEMA risk score",
             "nri_top_share": "Top {share} of Census areas statewide by FEMA risk score",
             "nri_rating": "Census areas with a high FEMA risk rating"}


def plain(text: str) -> str:
    """Reader wording for config text: no code words or file names."""
    text = re.sub(r"\bteam_assumption\b", "Team assumption", str(text))
    text = re.sub(r"\b(?:config|data|scripts)/[\w./-]+", "the plan's sources", text)
    text = re.sub(r"PLAN\.md(?: §[\d.]+)?", "the plan", text)
    return text


def rule_text(rule: str, share=None) -> str:
    s = RULE_TEXT.get(rule, rule.replace("_", " "))
    return s.replace("{share}", pct_text(share) if share is not None else "")


def pct_text(x: float) -> str:
    """Percent with a decimal only when needed: 0.112 -> '11.2%', 0.11 -> '11%'."""
    v = round(x * 100, 1)
    return f"{v:.0f}%" if v == int(v) else f"{v}%"
CMIST = [("C – Communication", "people who speak English less than well (they may need "
          "interpreters and translated messages), and people with hearing or vision "
          "difficulty."),
         ("M – Medical", "people who use power-dependent medical equipment (an estimate from "
          "HHS emPOWER)."),
         ("I – Independence", "people with a disability, people with cognitive difficulty "
          "(memory, decisions) and people age 65 and older."),
         ("S – Safety and support", "people age 65 and older living alone, children and "
          "people living in group quarters (in the needs table)."),
         ("T – Transportation", "people in households without a car.")]


REASON_PLAIN = [
    (r"^FEMA zone D: flood risk undetermined$", "FEMA has not mapped flood risk here (zone D)"),
    (r"^FEMA Special Flood Hazard Area \(zone (\w+)\)$", r"In a FEMA high-risk flood zone (zone \1)"),
    (r"^FEMA zone (\w+): outside Special Flood Hazard Area$",
     r"Outside FEMA high-risk flood zones (zone \1)"),
    (r"^no site flood data; tract is in flood footprint$",
     "No flood map data for the site; its Census area is in the flood risk area"),
    (r"^no site flood data; tract outside flood footprint$",
     "No flood map data for the site; its Census area is outside the flood risk area"),
    (r"^no site-level screen for this hazard$", "No site check for this hazard"),
    (r"^not located – not on map$", "Address not located; not on the map"),
    (r"^inside tsunami evacuation zone$", "Inside the tsunami evacuation zone"),
    (r"^outside tsunami evacuation zone$", "Outside the tsunami evacuation zone"),
]


def plain_reason(reason: str) -> str:
    for pat, repl in REASON_PLAIN:
        if re.match(pat, reason):
            return re.sub(pat, repl, reason)
    return reason


def partner_names(partners_cfg: dict) -> dict:
    """partner_type -> readable name from config/partners.json (county agencies merged)."""
    out = {}
    for p in partners_cfg.get("partners", []):
        name = re.sub(r" – \w+ \(agency name to be confirmed\)$", "", p["name"])
        out.setdefault(p["partner_type"], name)
    return out


def partner_text(ids: str, names: dict) -> str:
    return ", ".join(names.get(i.strip(), i.strip()) for i in ids.split(";") if i.strip())


PROV_NUMBERS = "Calculated by open code from public data · see Sources"
PROV_SHELTERS = "Compiled from official county releases · verified by team"


def prov(text: str, where: str = "") -> str:
    return f'<p class="prov">{escape(text)}{escape(where)}</p>'


def community_cell(main: str, sub: str) -> str:
    """Community name first, Census area ID as a smaller second line."""
    return f'{escape(main)}<br><small>{escape(sub)}</small>' 
STATUS_ORDER = ["ok", "check", "check (tract-level)", "undetermined", "exclude"]
AFN_PARTS = ("M_power_dependent_at_risk", "I_disability_at_risk", "C_lep_at_risk",
             "T_no_vehicle_persons_at_risk")
KAUAI_MAUI_NOTE = ("Kauaʻi and Maui share one language list: the Census survey reports both "
                   "counties (and Kalawao) as one area, so they cannot be separated.")


def slug(county: str, hazard: str) -> str:
    return f"{county.lower()}_{hazard}"


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def n(v) -> str:
    try:
        return f"{round(float(v)):,}"
    except (TypeError, ValueError):
        return escape(str(v or "–"))


# ---------------------------------------------------------------- data

def load_inputs() -> dict:
    needs = load_json(PROC / "needs_by_scenario.json")
    with open(PROC / "needs_by_tract.csv", newline="", encoding="utf-8") as fh:
        tract_rows = list(csv.DictReader(fh))
    return {
        "needs": needs,
        "tract_rows": tract_rows,
        "afn": load_json(PROC / "afn_tracts.geojson"),
        "shelters": load_json(PROC / "shelters_2026.geojson"),
        "candidates": load_json(PROC / "candidates.geojson"),
        "match": load_json(PROC / "match_plan.json"),
        "comm": load_json(CONFIG / "communication.json"),
        "partners": load_json(CONFIG / "partners.json"),
        "county_lines": load_county_lines(),
        "results": results_data(),
        "languages": load_languages(),
        "labels": load_labels(),
        "data_as_of": hst_date(needs.get("built_at")),
        "access": build_access.load(),      # None: no ArcGIS summary, straight-line only
    }


def load_county_lines(path: Path = ROOT / "data" / "sources" / "county_lines.csv") -> list:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def scenario(inp: dict, county: str, hazard: str) -> dict:
    return next(s for s in inp["needs"]["scenarios"]
                if s["county"] == county and s["hazard"] == hazard)


def match_scenario(inp: dict, county: str, hazard: str) -> dict:
    return next(s for s in inp["match"]["scenarios"]
                if s["county"] == county and s["hazard"] == hazard)


def tract_rows(inp: dict, county: str, hazard: str) -> list:
    return [r for r in inp["tract_rows"] if r["county"] == county and r["hazard"] == hazard]


def sites_for(inp: dict, county: str, hazard: str) -> list:
    """Known 2026 sites with status and reason; numbered for the map."""
    footprint = {r["tract_fips"] for r in tract_rows(inp, county, hazard)}
    out = []
    for f in inp["shelters"]["features"]:
        p = f["properties"]
        if p["county"] != county:
            continue
        geom = f.get("geometry")
        if geom:
            status, reason = site_status(p, hazard, footprint)
        else:
            status, reason = "unlocated", "not located – not on map"
        out.append({"name": p["name"], "address": p.get("address", ""),
                    "site_type": p.get("site_type", ""),
                    "times_opened_2026": p.get("times_opened_2026", 0),
                    "status": status, "reason": reason,
                    "lon": geom["coordinates"][0] if geom else None,
                    "lat": geom["coordinates"][1] if geom else None})
    order = {s: i for i, s in enumerate(STATUS_ORDER + ["unlocated"])}
    out.sort(key=lambda s: (order[s["status"]], s["name"]))
    for i, s in enumerate(out, 1):
        s["n"] = i
    return out


def largest_communities(rows: list, rates: dict, k: int = 3) -> list:
    rows = sorted(rows, key=lambda r: (-float(r["shelter_demand"]), r["tract_fips"]))[:k]
    out = []
    for r in rows:
        ar = float(r["at_risk_pop"])
        out.append({"tract_fips": r["tract_fips"],
                    "tract_label": r.get("tract_label") or r["tract_fips"],
                    "label_main": r.get("label_main") or r.get("tract_label") or r["tract_fips"],
                    "label_sub": r.get("label_sub", ""), "at_risk_pop": ar,
                    "low": ar * rates["low"], "central": float(r["shelter_demand"]),
                    "high": ar * rates["high"],
                    **{k: float(r[k]) for k in AFN_PARTS + ("I_age65_at_risk",)},
                    **{f: float(r.get(f) or 0) for _k, f, _l in DETAIL_KEYS}})
    return out


# ---------------------------------------------------------------- html parts

CSS = """
@page { size: Letter; margin: 0.6in 0.6in 0.85in 0.6in;
        @bottom-left { content: var(--footer); font: 9pt Arial, Helvetica, sans-serif;
                       vertical-align: top; padding-top: 6pt; border-top: 1px solid #000; }
        @bottom-right { content: "Page " counter(page) " of " counter(pages);
                        font: 9pt Arial, Helvetica, sans-serif; vertical-align: top;
                        padding-top: 6pt; border-top: 1px solid #000; } }
* { box-sizing: border-box; }
body { font-family: Arial, Helvetica, sans-serif; font-size: 12pt; line-height: 1.35;
       color: #000; background: #fff; margin: 0; }
h1 { font-size: 22pt; margin: 0 0 4pt; }
h2 { font-size: 15pt; margin: 16pt 0 6pt; border-bottom: 2px solid #000; padding-bottom: 2pt; }
h3 { font-size: 13pt; margin: 10pt 0 4pt; }
p, li { margin: 3pt 0; }
.asof { font-size: 12pt; font-weight: bold; }
.note { border: 2px solid #000; padding: 6pt 8pt; margin: 8pt 0; }
.kpis { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6pt; margin: 6pt 0; }
.kpi { border: 1px solid #000; padding: 5pt 7pt; }
.kpi b { display: block; font-size: 16pt; }
table { width: 100%; border-collapse: collapse; margin: 6pt 0; font-size: 10.5pt; }
th, td { border: 1px solid #000; padding: 3pt 5pt; text-align: left; vertical-align: top; }
th { background: #e6e6e6; }
td.num, th.num { text-align: right; }
td.num { white-space: nowrap; }
th { font-size: 9.5pt; line-height: 1.2; }
td:first-child { min-width: 1.3in; }
td small, .src, .range { font-size: 9pt; color: #333; }
.src { margin: 0 0 8pt; }
.mapwrap { display: grid; grid-template-columns: 2fr 1fr; gap: 10pt; align-items: start; }
ol.sitekey { margin: 0; padding-left: 0; list-style: none; font-size: 10pt; }
ol.sitekey li { margin: 0 0 3pt; }
.guide h3 { margin-top: 8pt; }
.guide p, .guide li { font-size: 11pt; }
.example td { background: #f2f2f2; }
.prov { font-size: 9.5pt; font-weight: bold; margin: 2pt 0 6pt; }
tr { break-inside: avoid; }
.page { break-before: page; }
.map { border: 1px solid #000; }
ul.legend { list-style: none; padding: 0; columns: 2; font-size: 10.5pt; }
ul.legend li { display: flex; align-items: center; gap: 6pt; break-inside: avoid; }
.footer { font-size: 9.5pt; border-top: 1px solid #000; padding-top: 3pt; margin-top: 24pt; }
@media print { .footer { display: none; } }
.status { white-space: nowrap; font-weight: bold; }
@media screen { body { max-width: 8.5in; margin: 0 auto; padding: 0.5in; }
}
"""


def css(data_as_of: str) -> str:
    """Page CSS with the footer text baked into the @page margin box (repeats on every
    printed page)."""
    text = f"Data as of {data_as_of} · {DISCLAIMER}".replace("\\", "").replace('"', "'")
    return CSS.replace("var(--footer)", f'"{text}"')


def table(headers: list, rows: list, num_cols: tuple = (), caption: str = "") -> str:
    th = "".join(f'<th scope="col"{" class=num" if i in num_cols else ""}>{escape(h)}</th>'
                 for i, h in enumerate(headers))
    body = "".join("<tr>" + "".join(f'<td{" class=num" if i in num_cols else ""}>{c}</td>'
                                    for i, c in enumerate(r)) + "</tr>" for r in rows)
    cap = f"<caption>{escape(caption)}</caption>" if caption else ""
    return f"<table>{cap}<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


def summary_html(sc: dict, hazard: str) -> str:
    kpis = [(COL["at_risk"], n(sc["at_risk_pop"])),
            ("May need a public shelter (likely)", n(sc["shelter_demand_central"])),
            ("May need a public shelter (low – high)",
             f'{n(sc["shelter_demand_low"])} – {n(sc["shelter_demand_high"])}'),
            (COL["lep"] + " (C)", n(sc["C_lep_at_risk"])),
            (COL["power"] + " (M)", n(sc["M_power_dependent_at_risk"])),
            (COL["disability"] + " (I)", n(sc["I_disability_at_risk"])),
            (COL["age65"] + " (I)", n(sc["I_age65_at_risk"])),
            (COL["no_car"] + " (T)", n(sc["T_no_vehicle_persons_at_risk"])),
            ("Known 2026 shelter sites usable for this hazard", n(sc.get("known_sites_usable")))]
    kpis[8:8] = [(f"{COL[k]} ({letter})", n(sc.get(field))) for k, field, letter in DETAIL_KEYS]
    if hazard == "hurricane":
        kpis.append((COL["highrise"], n(sc.get("highrise_units_at_risk"))))
    if hazard == "tsunami":
        kpis.append(("People in the extreme tsunami zone (worst case)",
                     n(sc.get("at_risk_pop_extreme_zone"))))
    cells = "".join(f'<div class="kpi">{escape(k)}<b>{v}</b></div>' for k, v in kpis)
    return (f'<h2>1. Summary</h2>{prov(PROV_NUMBERS, " (section 8)")}<div class="kpis">{cells}</div>'
            f'<p class="src">{escape(src_text("summary"))}</p>'
            f'<p>Share of people in the risk area who may need a public shelter: low '
            f'{pct_text(sc["rate_low"])}, likely {pct_text(sc["rate_central"])}, high {pct_text(sc["rate_high"])}. '
            f'One person can be counted in more than one need. Page 2 explains how to read '
            f'these numbers.</p>')


HURRICANE_SCOPE_NOTE = ("Hurricanes affect the whole county, so these are simply the most "
                        "populous at-risk Census areas.")


def scope_html(sc: dict, comms: list, hazard: str = "") -> str:
    rows = [[community_cell(c["label_main"], c["label_sub"]), n(c["at_risk_pop"]),
             f'{n(c["low"])} – <b>{n(c["central"])}</b> – {n(c["high"])}',
             n(c["C_lep_at_risk"]), n(c["M_power_dependent_at_risk"]),
             n(c["I_disability_at_risk"]), n(c["I_age65_at_risk"]),
             n(c["T_no_vehicle_persons_at_risk"])] for c in comms]
    area = FOOTPRINT_TEXT.get(sc.get("footprint_rule", ""), sc.get("footprint_rule", ""))
    return ('<h2>2. Scope: county total vs. one community</h2>'
            '<div class="note"><b>The county total is an upper bound.</b> It counts '
            f'{escape(area)} as hit at the same time. Real events usually hit fewer '
            'communities.</div>'
            '<h3>Largest single community (the Census areas with the most people who may '
            'need a shelter)</h3>'
            + (f'<p>{escape(HURRICANE_SCOPE_NOTE)}</p>' if hazard == "hurricane" else "")
            + table([COL["area"], COL["at_risk"], COL["shelter"], COL["lep"], COL["power"],
                     COL["disability"], COL["age65"], COL["no_car"]], rows,
                    num_cols=(1, 2, 3, 4, 5, 6, 7))
            + f'<p class="src">{escape(src_text("people"))}</p>'
            + '<p>To plan for one community, use the first row.</p>')


def guide_html(sc: dict, comms: list, hazard: str) -> str:
    """Page 2: how to read this playbook, with one example row."""
    ex = comms[0] if comms else None
    example = ""
    if ex:
        example = ('<h3>Example row</h3>'
                   + table([COL["area"], COL["at_risk"], COL["shelter"]],
                           [[community_cell(ex["label_main"], ex["label_sub"]),
                             n(ex["at_risk_pop"]),
                             f'{n(ex["low"])} – <b>{n(ex["central"])}</b> – {n(ex["high"])}']],
                           num_cols=(1, 2)).replace("<tr><td", '<tr class="example"><td', 1)
                   + f'<p>Read it as: about {n(ex["at_risk_pop"])} people live in the risk area '
                     f'of {escape(ex["label_main"])}. If this hazard hits, between '
                     f'{n(ex["low"])} and {n(ex["high"])} of them may need a public shelter; '
                     f'{n(ex["central"])} is the likely number.</p>')
    area = FOOTPRINT_TEXT.get(sc.get("footprint_rule", ""), sc.get("footprint_rule", ""))
    cmist = "".join(f"<li><b>{escape(k)}:</b> {escape(v)}</li>" for k, v in CMIST)
    return (f'<section class="guide page"><h2>How to read this playbook</h2>'
            f'{example}'
            '<h3>Census area</h3>'
            '<p>A neighborhood-sized area the U.S. Census uses, usually 1,200–8,000 people. '
            'The number (for example "Census area 308") is its Census ID. Each area is named '
            'after the Census place where most of its people live. "near" means no one in the '
            'area lives inside a named place; "rural near" means most people live outside '
            'named places.</p>'
            '<h3>Low – likely – high</h3>'
            f'<p>The share of people in the risk area who may go to a public shelter: low '
            f'{pct_text(sc["rate_low"])}, likely {pct_text(sc["rate_central"])}, high '
            f'{pct_text(sc["rate_high"])}. Where the rates come from: '
            f'{escape(RATE_NOTE.get(hazard, ""))}</p>'
            f'<h3>Who has access and functional needs (CMIST)</h3><ul>{cmist}</ul>'
            '<h3>County total vs. one community</h3>'
            f'<p>The county total counts {escape(area)} as hit at the same time, so it is an '
            'upper bound. Use the "Largest single community" table to plan for an event that '
            'hits one community.</p>'
            '<h3>Map</h3>'
            '<p>Darker blue means more people with needs, from "Lowest need" to "Highest '
            'need". A solid outline marks a Census area in the risk area; a dashed outline is '
            'outside it. Symbols: ○ usable site, △ check flood zone, ◇ flood risk not mapped, '
            '☒ not for this hazard. Numbers on the map match the site key.</p>'
            '<h3>Why population numbers can differ</h3>'
            '<p>People in the risk area come from ACS 2018–2022 estimates (through the CDC '
            'Social Vulnerability Index 2022). Community names use 2020 Census counts. County '
            'totals in the plan use Census estimates for 2025. Each table names its source '
            'underneath.</p>'
            '<div class="note"><b>Every number is a planning estimate. In an event, follow '
            'county announcements.</b></div></section>')


def map_html(inp: dict, county: str, hazard: str, sites: list) -> str:
    tracts = [f for f in inp["afn"]["features"] if f["properties"]["county"] == county]
    rows = tract_rows(inp, county, hazard)
    values = {r["tract_fips"]: sum(float(r[k]) for k in AFN_PARTS) for r in rows}
    labels = {fips: r["tract_label"] for fips, r in inp.get("labels", {}).items()}
    svg, bounds = svgmap.render(
        tracts, values, set(values),
        [s for s in sites if s["lon"] is not None],
        f"{COUNTY_LABEL[county]} {HAZARD_LABEL[hazard]}: people with needs by Census area "
        f"and known shelter sites", labels=labels)
    key = "".join(f'<li><b>{s["n"]}</b> = {escape(s["name"])} '
                  f'({escape(SITE_KEY_STATUS.get(s["status"], s["status"]))})</li>'
                  for s in sites)
    return (f'<h2 class="page">3. Map: people with needs and known sites</h2>'
            f'<div class="mapwrap"><div class="map">{svg}</div>'
            f'<div><h3>Site key</h3><ol class="sitekey">{key}</ol></div></div>'
            f'{svgmap.legend(bounds)}'
            '<p>Color = people in the risk area who speak English less than well, use '
            'power-dependent medical equipment, have a disability, or live without a car '
            '(a person can be counted more than once). No street map: Census area outlines '
            'only.</p>'
            f'<p class="src">{escape(src_text("people"))}</p>')


def sites_html(sites: list, sc: dict, access: dict | None = None) -> str:
    rows = [[str(s["n"]), f'<span class="status">{escape(STATUS_LABEL.get(s["status"], "Not located"))}</span>',
             escape(s["name"]), escape(s["address"]), escape(plain_reason(s["reason"])),
             str(s["times_opened_2026"])] for s in sites]
    return ('<h2 class="page">4. Known sites (opened in 2026 events)</h2>'
            + prov(PROV_SHELTERS)
            + table(["#", "Status for this hazard", "Site", "Address", "Why",
                     "Times opened in 2026"], rows, num_cols=(0, 5))
            + f'<p class="src">{escape(src_text("sites"))}</p>'
            + (f'<p class="src">{escape(src_text("access"))}</p>' if access else "")
            + f'<p>Candidate public schools in this county usable for this hazard: '
              f'<b>{n(sc.get("candidate_schools_usable"))}</b>'
            + (f'; flood risk not mapped (FEMA zone D): {n(sc.get("candidate_schools_flood_undetermined"))}'
               if sc.get("candidate_schools_flood_undetermined") else "")
            + '. Sites are places a county has opened before; not every site opens in every '
              'event. Always follow current county announcements.</p>')


def county_lines_html(lines: list, county: str) -> str:
    """County counts planned separately; never added to the Census-area totals."""
    rows = [[escape(COUNTY_LINE_LABEL.get(r["line"], r["line"])), n(r["value"]),
             escape(r["detail"]), escape(r["period"])] for r in lines if r["county"] == county]
    if not rows:
        return ""
    return ('<h3>Also plan for (county counts, not included in the totals above)</h3>'
            + table(["Group", "People", "Detail", "Date"], rows, num_cols=(1,))
            + f'<p class="src">{escape(src_text("county_lines"))}</p>')


def who_else_html() -> str:
    items = "".join(f"<li><b>{escape(k)}:</b> {escape(v.replace(SOURCES_TOKEN, 'section 8'))}</li>"
                    for k, v in WHO_ELSE)
    return f'<div class="note"><b>Who else to plan for</b><ul>{items}</ul></div>'


def reach_html(comm: dict, partners: dict) -> str:
    rows = [[escape(c["description"]), escape(partners.get(c["owner"], c["owner"])
                                             if c["owner"] != "county_em" else
                                             "County Emergency Management (each county)"),
             escape(partner_text("; ".join(c["support"]), partners))] for c in comm["channels"]]
    fmts = "".join(f"<li><b>{escape(k)}:</b> {escape(v)}</li>"
                   for k, v in comm.get("accessible_formats", {}).get("formats", []))
    return ('<h3>How to reach residents</h3>'
            + table(["Channel", "Owner (proposed)", "Support (proposed)"], rows)
            + f'<p class="src">{escape(src_text("reach"))}</p>'
            + f'<p><b>Accessible formats for every message:</b></p><ul>{fmts}</ul>')


def more_needs_html(comms: list) -> str:
    rows = [[community_cell(c["label_main"], c["label_sub"])]
            + [n(c.get(field)) for _k, field, _l in DETAIL_KEYS] for c in comms]
    return ('<h3>More needs in the largest communities</h3>'
            + table([COL["area"]] + [COL[k] for k, _f, _l in DETAIL_KEYS], rows,
                    num_cols=(1, 2, 3, 4))
            + f'<p class="src">{escape(src_text("detail"))}</p>')


def needs_html(ms: dict, partners: dict, county: str = "", lines: list | None = None) -> str:
    rows = [[escape(lang_label(l["need"])), n(l["quantity"]), escape(l["unit"]),
             escape(partner_text(l["lead_partner_types"], partners)),
             escape(partner_text(l["support_partner_types"], partners)),
             escape(str(l["pledged_capacity"]) or "—"), "confirm with partner"
             if l["gap"].startswith("unknown") else escape(l["gap"])] for l in ms["needs"]]
    return ('<h2 class="page">5. Needs and proposed partners</h2>'
            '<p>Likely estimate. Roles are <b>proposed – to be confirmed with partner</b>. '
            'The pledged column stays blank until a partner confirms it.</p>'
            + table(["Need", "How many", "Unit", "Proposed lead", "Proposed support",
                     "Pledged by partner", "Still needed"], rows, num_cols=(1,))
            + f'<p class="src">{escape(src_text("needs"))}</p>'
            + f'<p><b>{escape(SERVICE_ANIMALS)}</b></p>'
            + county_lines_html(lines or [], county)
            + (f'<p>{escape(KALAWAO_NOTE)}</p>' if county == "Maui" else "")
            + who_else_html())


def decisions_html(match: dict, hazard: str, partners: dict) -> str:
    rows = [[f'<b>{escape(d["timing"].upper())}</b>',
             f'{escape(d["trigger"])}<br><small>{escape(d["issuer"])}</small>',
             escape(d["action"]), escape(d["owner_name"]),
             escape(partner_text(d["support"], partners))] for d in match["decision_points"][hazard]]
    return ('<h2 class="page">6. Decision points</h2>'
            '<div class="note">Proposed – supports, does not replace, county plans.</div>'
            + table(["When", "Trigger", "Action", "Owner (proposed)", "Support"], rows)
            + f'<p class="src">{escape(src_text("decisions"))}</p>')


def outreach_html(ms: dict, langs: list, county: str, comms: list | None = None,
                  comm: dict | None = None, partners: dict | None = None) -> str:
    rows = [[str(t["rank"]), community_cell(t.get("label_main") or t.get("tract_label", ""),
                                            t.get("label_sub", "")),
             n(t["at_risk_pop"]), n(t["power_dependent"]), n(t["disability"]),
             n(t["limited_english"]), n(t["no_vehicle"]), n(t["afn_need_sum"])]
            for t in ms["priority_tracts"]]
    lrows = [[escape(lang_label(l["language"])), n(l["speak_english_less_than_very_well"]),
              "±" + n(l["moe_90"])] for l in langs]
    area = langs[0]["area"] if langs else ""
    note = f"<p>{escape(KAUAI_MAUI_NOTE)}</p>" if county in ("Kauai", "Maui") else ""
    return ('<h2 class="page">7. Priority outreach and languages</h2>'
            '<h3>Top 10 Census areas by number of people with needs</h3>'
            + table(["#", COL["area"], COL["at_risk"], COL["power"], COL["disability"],
                     COL["lep"], COL["no_car"], COL["needs_total"]], rows,
                    num_cols=(0, 2, 3, 4, 5, 6, 7))
            + f'<p class="src">{escape(src_text("people"))}</p>'
            + (more_needs_html(comms) if comms else "")
            + (reach_html(comm, partners or {}) if comm else "")
            + f'<h3>Languages: people age 5 and older who speak English less than "very well" '
              f'({escape(area_label(area))})</h3>'
            + note
            + table(["Language", "People", "Margin of error (90%)"], lrows, num_cols=(1, 2))
            + f'<p class="src">{escape(src_text("languages"))}</p>'
            + '<p>Pre-approved message templates: none yet; no machine translation without '
              'human review.</p>')


def results_data() -> dict:
    """Results: every number read from data files (and config/results.json)."""
    cov = json.loads((PROC / "coverage.json").read_text(encoding="utf-8"))
    counties = {k: v for k, v in cov.items() if isinstance(v, dict) and "tracts" in v}
    with open(PROC / "backtest.csv", newline="", encoding="utf-8") as fh:
        bt = list(csv.DictReader(fh))
    timing_path = PROC / "rebuild_timing.json"
    timing = json.loads(timing_path.read_text(encoding="utf-8")) if timing_path.exists() else None
    base = dict(json.loads((CONFIG / "results.json").read_text(encoding="utf-8"))["time_baseline"])
    base["source"] = "Team assumption, to be confirmed with DHS in a timed tabletop exercise"
    return {
        "tracts": sum(v["tracts"] for v in counties.values()),
        "with_cmist": sum(v["with_cmist"] for v in counties.values()),
        "with_nri": sum(v["with_nri"] for v in counties.values()),
        "backtest": [{k: r[k] for k in ("event", "date", "observed", "model_low", "model_central",
                                        "model_high", "observed_within_band", "calibration_event")}
                     for r in bt],
        "rebuild": timing, "baseline": base,
        "sources": {"coverage": "coverage check of the needs layer (CDC SVI 2022, FEMA NRI v1.20)",
                    "backtest": "Lahaina 2023 backtest (Maui Now count of people in shelters)",
                    "rebuild": "timed full rebuild from local data",
                    "baseline": base["source"]},
    }


def results_html(r: dict) -> str:
    items = [f'<li><b>Coverage:</b> {n(r["with_cmist"])} of {n(r["tracts"])} Census areas have '
             f'needs data (FEMA risk data joined for {n(r["with_nri"])} of {n(r["tracts"])}). '
             f'<small>Source: {escape(r["sources"]["coverage"])}.</small></li>']
    for b in r["backtest"]:
        items.append(
            f'<li><b>Backtest – {escape(b["event"])} ({escape(b["date"])}):</b> observed '
            f'{n(b["observed"])} people in shelters; model {n(b["model_low"])} / '
            f'{n(b["model_central"])} / {n(b["model_high"])} (low / likely / high). '
            + ("This is a calibration event, not validation: the high rate was set from it. "
               if b["calibration_event"] == "True" else "")
            + f'<small>Source: {escape(r["sources"]["backtest"])}.</small></li>')
    t, base = r["rebuild"], r["baseline"]
    if t:
        items.append(
            f'<li><b>Time:</b> a full rebuild from local data ({n(t["steps"])} steps, '
            f'{n(t["scenarios"])} scenarios, {n(t["playbooks"])} playbooks) took {t["seconds"]} '
            f'seconds on {escape(t["machine"])} ({escape(t["measured_at"][:10])}). Team-assumed '
            f'baseline without this tool: {base["value"]} {escape(base["unit"])}. '
            f'<small>Sources: {escape(r["sources"]["rebuild"])}; {escape(base["source"])}.</small></li>')
    return '<h2 class="page">9. Results</h2><ul class="results">' + "".join(items) + "</ul>"


FACILITY_ZONE_D = "Also in FEMA zone D (flood risk not mapped, not counted above): {n} –"
NO_FACILITY_SCREEN = ("No facility-level zone screen for this hazard (the same as for shelter "
                      "sites).")


def facility_rows(access: dict | None, county: str, hazard: str) -> tuple[list, int]:
    """(care facilities in this hazard's zone, all care facilities) for one county."""
    fac = [f for f in (access or {}).get("facilities", []) if f["county"] == county]
    return [f for f in fac if f["zones"].get(hazard)], len(fac)


def facilities_html(inp: dict, county: str, hazard: str) -> str:
    if not inp.get("access"):
        return ""
    rows, total = facility_rows(inp["access"], county, hazard)
    head = "<h3>Care facilities in hazard zones</h3>"
    if hazard not in ("tsunami", *FLOOD):
        body = f"<p>{escape(NO_FACILITY_SCREEN)} Care facilities in this county: {total}.</p>"
    elif rows:
        body = table(["Name", "Type", "Zone"],
                     [[escape(f["name"]), escape(f["type_label"]), escape(f["zones"][hazard])]
                      for f in rows],
                     caption=f"Care facilities in hazard zones – {COUNTY_LABEL[county]}, "
                             f"{HAZARD_LABEL[hazard]} ({len(rows)} of {total})")
    else:
        body = (f"<p>None of the {total} care facilities in this county is inside the "
                f"{escape(HAZARD_LABEL[hazard].lower())} zone.</p>")
    zone_d = [f for f in inp["access"]["facilities"]
              if f["county"] == county and (f["fld_zone"] or "").upper() == "D"]
    if hazard in FLOOD and zone_d:
        body += (f"<p>{FACILITY_ZONE_D.format(n=len(zone_d))} "
                 + escape(", ".join(f["name"] for f in zone_d)) + ".</p>")
    return head + body + f'<p class="src">{escape(src_text("facilities"))}</p>'


def sources_html(inp: dict) -> str:
    pf = inp["needs"]["planning_factors"]
    rows = []
    for hz, r in pf["shelter_seeking_rate"].items():
        if hz.startswith("_"):
            continue
        rows.append([f"Shelter-seeking rate – {escape(HAZARD_LABEL.get(hz, hz))}",
                     f'{pct_text(r["low"])} / {pct_text(r["central"])} / {pct_text(r["high"])}',
                     escape(plain(r["source"]))])
    for hz, r in pf["footprint"].items():
        if isinstance(r, dict):
            rows.append([f"Footprint – {escape(HAZARD_LABEL.get(hz, hz))}",
                         escape(rule_text(r["rule"], r.get("share"))),
                         escape(plain(r.get("note") or pf["footprint"].get(
                             "nri_top_share_by_county_note", "Team assumption")))])
    for k, v in pf["per_person"].items():
        rows.append([escape(k.replace("_", " ").capitalize()), escape(str(v["value"])),
                     escape(plain(v["source"]))])
    staff = ", ".join(f"{k.replace('_', ' ')} 1:{v['per_children'] if isinstance(v, dict) else v}"
                      for k, v in pf["staff_per_shift"].items() if not k.startswith("_"))
    rows.append(["Staffing ratios (one staff member per N residents)", escape(staff),
                 escape(plain(pf["staff_per_shift"]["_about"]))])
    for k, v in pf["pets"].items():
        rows.append([escape(k.replace("_", " ").capitalize()), escape(str(v["value"])),
                     escape(plain(v["source"]))])
    data = [[escape(s["source"]), escape(hst_date(s.get("fetched_at", ""))), escape(s["source_url"])]
            for s in inp["afn"]["metadata"].get("sources", [])]
    flood_dates = []
    if FLOOD_CACHE.exists():
        with open(FLOOD_CACHE, newline="", encoding="utf-8") as fh:
            flood_dates = sorted(r["queried_at"][:10] for r in csv.DictReader(fh))
    data += [
        ["Hawaiʻi Statewide GIS – State DFIRM (FEMA flood hazard areas, 6/15/26)",
         escape(flood_dates[-1] if flood_dates else ""), escape(FLOOD_URL)],
        ["County shelter activations 2026 (official county releases)", "2026-10-27",
         "County shelter activation table: one official county source per row"],
        ["2020 Census Block Assignment File, place/CDP (tract community labels)", "2026-10-27",
         "https://www2.census.gov/geo/docs/maps-data/data/baf2020/BlockAssign_ST15_HI.zip"],
        ["2020 Census PL 94-171 block population P1_001N (tract community labels)", "2026-10-27",
         "https://www2.census.gov/programs-surveys/decennial/2020/data/01-Redistricting_File--PL_94-171/Hawaii/hi2020.pl.zip"],
        ["ACS PUMS 2019-2023 5-year (detailed languages)", "2026-10-27",
         "https://www2.census.gov/programs-surveys/acs/data/pums/2023/5-Year/csv_phi.zip"],
        ["DBEDT State of Hawaiʻi Data Book 2024, Table 1.44 (validation)", "2026-10-27",
         "https://files.hawaii.gov/dbedt/economic/databook/2024-individual/01/014424.pdf"],
        ["Partner list: Hawaiʻi DHS – ESF-6 challenge statement (2026)", "2026-10-15",
         "Hawaiʻi DHS – ESF-6 challenge statement (2026)"],
    ]
    data += [[escape(k.replace("_", " ")), "", escape(u)]
             for k, u in inp["match"]["sources"]["triggers"].items()]
    if inp.get("access"):
        data += [[escape(f"CMS Provider Data Catalog – {t}"), "", escape(
                     f"https://data.cms.gov/provider-data/dataset/{ds}")]
                 for ds, t in build_access.fa.CMS.values()]
        data += [["Esri ArcGIS World Geocoder (site check, care facilities) and ArcGIS "
                  "routing (drive and walk times, normal traffic). Powered by Esri.", "",
                  "https://developers.arcgis.com/rest/"]]
    return ('<h2 class="page">8. Sources and assumptions</h2>'
            '<h3>Planning factors</h3>'
            + table(["Factor", "Value", "Source or team assumption"], rows)
            + '<h3>Data sources</h3>'
            + table(["Source", "Fetched", "URL / file"], data)
            + '<p>Privacy: aggregate census-tract and county data only. No individual '
              'records. Public facility names and addresses only.</p>')


def playbook_html(inp: dict, county: str, hazard: str) -> str:
    sc = scenario(inp, county, hazard)
    ms = match_scenario(inp, county, hazard)
    sites = sites_for(inp, county, hazard)
    rates = inp["needs"]["planning_factors"]["shelter_seeking_rate"][hazard]
    comms = largest_communities(tract_rows(inp, county, hazard), rates)
    langs = select_languages(inp["languages"].get(county, []), inp["comm"])
    title = f"{COUNTY_LABEL[county]} – {HAZARD_LABEL[hazard]} ESF-6 playbook"
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title><style>{css(inp["data_as_of"])}</style></head>
<body>
<header>
<h1>{escape(title)}</h1>
<p class="asof">Data as of {escape(inp["data_as_of"])}</p>
<p><b>County:</b> {escape(COUNTY_LABEL[county])} · <b>Hazard:</b> {escape(HAZARD_LABEL[hazard])}</p>
<div class="note"><b>{escape(DISCLAIMER)}</b></div>
</header>
<main>
{summary_html(sc, hazard)}
{scope_html(sc, comms, hazard)}
{guide_html(sc, comms, hazard)}
{map_html(inp, county, hazard, sites)}
{sites_html(sites, sc, inp.get("access"))}
{facilities_html(inp, county, hazard)}
{needs_html(ms, partner_names(inp["partners"]), county, inp["county_lines"])}
{decisions_html(inp["match"], hazard, partner_names(inp["partners"]))}
{outreach_html(ms, langs, county, comms, inp["comm"], partner_names(inp["partners"]))}
{sources_html(inp)}
{results_html(inp["results"])}
</main>
<footer class="footer">Data as of {escape(inp["data_as_of"])} · {escape(DISCLAIMER)}</footer>
</body></html>
"""


def index_html(data_as_of: str) -> str:
    rows = []
    for c in COUNTIES:
        cells = "".join(f'<td><a href="{slug(c, h)}.pdf">PDF</a> · '
                        f'<a href="{slug(c, h)}.html">HTML</a></td>' for h in HAZARDS)
        rows.append(f"<tr><th scope=row>{escape(COUNTY_LABEL[c])}</th>{cells}</tr>")
    heads = "".join(f"<th scope=col>{escape(HAZARD_LABEL[h])}</th>" for h in HAZARDS)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ESF-6 playbooks</title><style>{css(data_as_of)}</style></head>
<body><h1>Hawaiʻi ESF-6 playbooks</h1><p class="asof">Data as of {escape(data_as_of)}</p>
<div class="note"><b>{escape(DISCLAIMER)}</b></div>
<table><thead><tr><th scope=col>County</th>{heads}</tr></thead><tbody>{"".join(rows)}</tbody></table>
</body></html>
"""


# ---------------------------------------------------------------- pdf

def find_browser() -> str | None:
    cands = [os.environ.get("CHROME_BIN", "")]
    cands += sorted(glob.glob(str(Path.home() / "Library/Caches/ms-playwright/chromium-*/"
                                  "chrome-mac*/*.app/Contents/MacOS/*")), reverse=True)
    cands += sorted(glob.glob(str(Path.home() / ".cache/ms-playwright/chromium-*/chrome-linux*/chrome")),
                    reverse=True)
    cands += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              shutil.which("chromium") or "", shutil.which("google-chrome") or ""]
    return next((c for c in cands if c and os.path.isfile(c) and os.access(c, os.X_OK)), None)


def to_pdf(html: Path, pdf: Path, browser: str | None) -> str:
    if browser:
        with tempfile.TemporaryDirectory() as prof:
            subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-first-run",
                            "--no-default-browser-check", f"--user-data-dir={prof}",
                            "--no-pdf-header-footer", f"--print-to-pdf={pdf}",
                            html.resolve().as_uri()],
                           check=True, capture_output=True, timeout=120)
        return "chrome"
    import weasyprint  # noqa: PLC0415 – fallback only
    weasyprint.HTML(filename=str(html)).write_pdf(str(pdf))
    return "weasyprint"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build printable ESF-6 playbooks")
    ap.add_argument("--html-only", action="store_true", help="skip PDF output")
    args = ap.parse_args(argv)
    inp = load_inputs()
    OUT.mkdir(exist_ok=True)
    browser = None if args.html_only else find_browser()
    engine = "none"
    for c in COUNTIES:
        for h in HAZARDS:
            html = OUT / f"{slug(c, h)}.html"
            html.write_text(playbook_html(inp, c, h), encoding="utf-8")
            if not args.html_only:
                engine = to_pdf(html, OUT / f"{slug(c, h)}.pdf", browser)
    (OUT / "index.html").write_text(index_html(inp["data_as_of"]), encoding="utf-8")
    print(f"Wrote {len(COUNTIES) * len(HAZARDS)} playbooks -> playbooks/ (PDF engine: {engine})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
