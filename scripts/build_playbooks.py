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
from hawaii_time import hst_date  # noqa: E402
from model_needs import HAZARDS, site_status  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PROC = ROOT / "data" / "processed"
CONFIG = ROOT / "config"
OUT = ROOT / "playbooks"

DISCLAIMER = ("Planning aid. Supports, does not replace, county emergency plans. "
              "Not an official shelter list.")
COUNTY_LABEL = {"Kauai": "Kauaʻi", "Honolulu": "Honolulu", "Maui": "Maui", "Hawaii": "Hawaiʻi"}
HAZARD_LABEL = {"hurricane": "Hurricane", "wildfire": "Wildfire", "tsunami": "Tsunami",
                "inland_flood": "Inland flooding", "coastal_flood": "Coastal flooding"}
STATUS_LABEL = {"ok": "✓ Usable", "check": "⚠ Check – flood",
                "check (tract-level)": "⚠ Check – flood (tract-level)",
                "undetermined": "? Undetermined – flood", "exclude": "✕ Excluded"}
STATUS_ORDER = ["ok", "check", "check (tract-level)", "undetermined", "exclude"]
AFN_PARTS = ("M_power_dependent_at_risk", "I_disability_at_risk", "C_lep_at_risk",
             "T_no_vehicle_persons_at_risk")
KAUAI_MAUI_NOTE = ("Kauaʻi and Maui share one language list: ACS PUMS reports both counties "
                   "(and Kalawao) as a single area, PUMA 00100, so they cannot be separated.")


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
        "languages": load_languages(),
        "labels": load_labels(),
        "data_as_of": hst_date(needs.get("built_at")),
    }


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
                    "tract_label": r.get("tract_label") or r["tract_fips"], "at_risk_pop": ar,
                    "low": ar * rates["low"], "central": float(r["shelter_demand"]),
                    "high": ar * rates["high"],
                    **{k: float(r[k]) for k in AFN_PARTS + ("I_age65_at_risk",)}})
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
td.num, th.num { text-align: right; white-space: nowrap; }
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
    kpis = [("People at risk", n(sc["at_risk_pop"])),
            ("Shelter demand (central)", n(sc["shelter_demand_central"])),
            ("Shelter demand low – high",
             f'{n(sc["shelter_demand_low"])} – {n(sc["shelter_demand_high"])}'),
            ("Limited English (C)", n(sc["C_lep_at_risk"])),
            ("Power-dependent (M)", n(sc["M_power_dependent_at_risk"])),
            ("Disability (I)", n(sc["I_disability_at_risk"])),
            ("Age 65+ (I)", n(sc["I_age65_at_risk"])),
            ("People without a vehicle (T)", n(sc["T_no_vehicle_persons_at_risk"])),
            ("Known 2026 sites usable", n(sc.get("known_sites_usable")))]
    if hazard == "tsunami":
        kpis.append(("At risk, extreme tsunami zone (worst case)",
                     n(sc.get("at_risk_pop_extreme_zone"))))
    cells = "".join(f'<div class="kpi">{escape(k)}<b>{v}</b></div>' for k, v in kpis)
    return (f'<h2>1. Summary</h2><div class="kpis">{cells}</div>'
            f'<p>Shelter-seeking rates: low {sc["rate_low"]:.0%}, central {sc["rate_central"]:.0%}, '
            f'high {sc["rate_high"]:.1%}. CMIST counts are people at risk, from census-tract '
            f'estimates; one person can appear in more than one count.</p>')


HURRICANE_SCOPE_NOTE = ("Hurricanes affect the whole county, so these are simply the most "
                        "populous at-risk tracts.")


def scope_html(sc: dict, comms: list, hazard: str = "") -> str:
    rows = [[escape(c["tract_label"]), n(c["at_risk_pop"]),
             f'{n(c["low"])} / <b>{n(c["central"])}</b> / {n(c["high"])}',
             n(c["C_lep_at_risk"]), n(c["M_power_dependent_at_risk"]),
             n(c["I_disability_at_risk"]), n(c["I_age65_at_risk"]),
             n(c["T_no_vehicle_persons_at_risk"])] for c in comms]
    return ('<h2>2. Scope: county total vs. one community</h2>'
            '<div class="note"><b>County total = upper bound.</b> It assumes every at-risk '
            f'tract is hit at once ({escape(sc.get("footprint_rule", ""))}). Real events '
            'usually hit fewer communities.</div>'
            '<h3>Largest single community (highest-demand census tracts)</h3>'
            + (f'<p>{escape(HURRICANE_SCOPE_NOTE)}</p>' if hazard == "hurricane" else "")
            + table(["Tract", "At risk", "Shelter low / central / high", "Limited English",
                     "Power-dep.", "Disability", "65+", "No vehicle"], rows,
                    num_cols=(1, 2, 3, 4, 5, 6, 7))
            + '<p>Plan a realistic one-community event with the first row.</p>')


def map_html(inp: dict, county: str, hazard: str, sites: list) -> str:
    tracts = [f for f in inp["afn"]["features"] if f["properties"]["county"] == county]
    rows = tract_rows(inp, county, hazard)
    values = {r["tract_fips"]: sum(float(r[k]) for k in AFN_PARTS) for r in rows}
    labels = {fips: r["tract_label"] for fips, r in inp.get("labels", {}).items()}
    svg, bounds = svgmap.render(
        tracts, values, set(values),
        [s for s in sites if s["lon"] is not None],
        f"{COUNTY_LABEL[county]} {HAZARD_LABEL[hazard]}: AFN need by census tract and "
        f"known shelter sites", labels=labels)
    return (f'<h2 class="page">3. Map: AFN need and known sites</h2>'
            f'<div class="map">{svg}</div>{svgmap.legend(bounds)}'
            '<p>AFN need = power-dependent + disability + limited English + no-vehicle people '
            'at risk (people may be counted more than once). Numbers on markers match the '
            'sites table. No basemap: tract outlines only.</p>')


def sites_html(sites: list, sc: dict) -> str:
    rows = [[str(s["n"]), f'<span class="status">{escape(STATUS_LABEL.get(s["status"], "Not located"))}</span>',
             escape(s["name"]), escape(s["address"]), escape(s["reason"]),
             str(s["times_opened_2026"])] for s in sites]
    return ('<h2 class="page">4. Known sites (opened in 2026 events)</h2>'
            + table(["#", "Status", "Site", "Address", "Reason", "Times opened 2026"], rows,
                    num_cols=(0, 5))
            + f'<p>Candidate public schools in this county usable for this hazard: '
              f'<b>{n(sc.get("candidate_schools_usable"))}</b>'
            + (f'; flood risk undetermined (zone D): {n(sc.get("candidate_schools_flood_undetermined"))}'
               if sc.get("candidate_schools_flood_undetermined") else "")
            + '. Sites are places a county has opened before; not every site opens in every '
              'event. Always follow current county announcements.</p>')


def needs_html(ms: dict) -> str:
    rows = [[escape(l["need"]), n(l["quantity"]), escape(l["unit"]),
             escape(l["lead_partner_types"]), escape(l["support_partner_types"]),
             escape(str(l["pledged_capacity"]) or "—"), "confirm with partner"
             if l["gap"].startswith("unknown") else escape(l["gap"])] for l in ms["needs"]]
    return ('<h2 class="page">5. Needs and proposed partners</h2>'
            '<p>Central estimate. Roles are <b>proposed – to be confirmed with partner</b>. '
            'Pledged capacity stays blank until a partner confirms it.</p>'
            + table(["Need", "Quantity", "Unit", "Proposed lead", "Proposed support",
                     "Pledged", "Gap"], rows, num_cols=(1,)))


def decisions_html(match: dict, hazard: str) -> str:
    rows = [[f'<b>{escape(d["timing"].upper())}</b>',
             f'{escape(d["trigger"])}<br><small>{escape(d["issuer"])}</small>',
             escape(d["action"]), escape(d["owner_name"]),
             escape(d["support"].replace("; ", ", "))] for d in match["decision_points"][hazard]]
    return ('<h2 class="page">6. Decision points</h2>'
            '<div class="note">Proposed – supports, does not replace, county plans.</div>'
            + table(["When", "Trigger", "Action", "Owner (proposed)", "Support"], rows))


def outreach_html(ms: dict, langs: list, county: str) -> str:
    rows = [[str(t["rank"]), escape(t.get("tract_label") or t["tract_fips"]), n(t["at_risk_pop"]),
             n(t["power_dependent"]), n(t["disability"]), n(t["limited_english"]),
             n(t["no_vehicle"]), n(t["afn_need_sum"])] for t in ms["priority_tracts"]]
    lrows = [[escape(l["language"]), n(l["speak_english_less_than_very_well"]),
              "±" + n(l["moe_90"])] for l in langs]
    area = langs[0]["area"] if langs else ""
    note = f"<p>{escape(KAUAI_MAUI_NOTE)}</p>" if county in ("Kauai", "Maui") else ""
    return ('<h2 class="page">7. Priority outreach and languages</h2>'
            '<h3>Top 10 census tracts by AFN need (tract-level counts only)</h3>'
            + table(["#", "Tract", "At risk", "Power-dep.", "Disability", "Limited English",
                     "No vehicle", "AFN need"], rows, num_cols=(0, 2, 3, 4, 5, 6, 7))
            + f'<h3>Languages: people who speak English less than "very well" ({escape(area)})</h3>'
            + note
            + table(["Language", "People 5+", "90% MOE"], lrows, num_cols=(1, 2))
            + '<p>Source: ACS PUMS 2019-2023 5-year (validated against DBEDT Data Book 2024, '
              'Table 1.44). Pre-approved message templates: none yet; no machine translation '
              'without human review.</p>')


def sources_html(inp: dict) -> str:
    pf = inp["needs"]["planning_factors"]
    rows = []
    for hz, r in pf["shelter_seeking_rate"].items():
        if hz.startswith("_"):
            continue
        rows.append([f"Shelter-seeking rate – {escape(HAZARD_LABEL.get(hz, hz))}",
                     f'{r["low"]} / {r["central"]} / {r["high"]}', escape(r["source"])])
    for hz, r in pf["footprint"].items():
        if isinstance(r, dict):
            rows.append([f"Footprint – {escape(HAZARD_LABEL.get(hz, hz))}", escape(r["rule"])
                         + (f' ({r["share"]:.0%})' if "share" in r else ""),
                         escape(r.get("note") or pf["footprint"].get(
                             "nri_top_share_by_county_note", "team assumption"))])
    for k, v in pf["per_person"].items():
        rows.append([escape(k.replace("_", " ")), escape(str(v["value"])), escape(v["source"])])
    staff = ", ".join(f"{k.replace('_', ' ')} 1:{v['per_children'] if isinstance(v, dict) else v}"
                      for k, v in pf["staff_per_shift"].items() if not k.startswith("_"))
    rows.append(["Staffing ratios", escape(staff), escape(pf["staff_per_shift"]["_about"])])
    for k, v in pf["pets"].items():
        rows.append([escape(k.replace("_", " ")), escape(str(v["value"])), escape(v["source"])])
    data = [[escape(s["source"]), escape(hst_date(s.get("fetched_at", ""))), escape(s["source_url"])]
            for s in inp["afn"]["metadata"].get("sources", [])]
    flood_dates = []
    if FLOOD_CACHE.exists():
        with open(FLOOD_CACHE, newline="", encoding="utf-8") as fh:
            flood_dates = sorted(r["queried_at"][:10] for r in csv.DictReader(fh))
    data += [
        ["Hawaii Statewide GIS – State DFIRM (FEMA flood hazard areas, 6/15/26)",
         escape(flood_dates[-1] if flood_dates else ""), escape(FLOOD_URL)],
        ["County shelter activations 2026 (official county releases)", "see table",
         "data/sources/county_shelter_activations.csv"],
        ["Census TIGERweb 2020 Census Designated Places (tract community labels)", "2026-10-27",
         "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_Census2020/MapServer/28"],
        ["ACS PUMS 2019-2023 5-year (detailed languages)", "2026-10-27",
         "https://www2.census.gov/programs-surveys/acs/data/pums/2023/5-Year/csv_phi.zip"],
        ["DBEDT State of Hawaii Data Book 2024, Table 1.44 (validation)", "2026-10-27",
         "https://files.hawaii.gov/dbedt/economic/databook/2024-individual/01/014424.pdf"],
        ["Partner list: Hawaii DHS, HAIC 2026 ESF-6 challenge statement", "2026-10-15",
         "HAIC_AI Challenge_Submission_DHS_Disaster_2026.pdf"],
    ]
    data += [[escape(k.replace("_", " ")), "", escape(u)]
             for k, u in inp["match"]["sources"]["triggers"].items()]
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
{map_html(inp, county, hazard, sites)}
{sites_html(sites, sc)}
{needs_html(ms)}
{decisions_html(inp["match"], hazard)}
{outreach_html(ms, langs, county)}
{sources_html(inp)}
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
