#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – who lives where: county totals, communities by island,
detailed race/ethnicity by county.

Newest published data first; the 2020 Census is the baseline and cross-check.
  * County totals: Census Bureau Population Estimates, Vintage 2025 (July 1, 2025),
    next to the 2020 Census (PL 94-171) count.
  * Communities: ACS 2020-2024 5-year total population for every Census Designated
    Place (CDP), with the 2020 Census count; each CDP is assigned to an island using
    DBEDT State Data Book 2025 table 01.12 (island and CDP).
  * Race/ethnicity by county: ACS detailed tables (B02015/B02016 alone, B02018/B02019
    alone or in any combination), broad groups (B02001, B02008-B02012, B03002) and
    Vintage 2025 broad groups; 2020 Census DHC-A (table T01001, one POPGROUP per group) as
    the 2020 baseline. Honolulu, Hawaiʻi, Maui and Kauaʻi counties use the ACS 2025
    1-year (released 2026-10-29) wherever the table and cell are published; otherwise
    the ACS 2020-2024 5-year figure is kept and the row says so. Kalawao (too small for
    1-year estimates) and the State rows keep the 5-year.

Census publishes detailed race down to county only. Honolulu County = Oʻahu and
Hawaiʻi County = Hawaiʻi Island; Maui County and Kauaʻi County are multi-island and
are labelled that way.

Aggregate published tables only, no microdata. Missing or suppressed cells are left
blank with status "suppressed" or "not available"; nothing is estimated or filled.
The Census Data API needs a key, so tables come from the keyless data.census.gov
download of the same table (its response names the equivalent api.census.gov query).

Usage:  python3 scripts/build_demographics.py            (download, cache, tidy)
        python3 scripts/build_demographics.py --offline  (re-tidy from data/raw)
Outputs (committed):
  data/sources/county_population_2020_2025.csv
  data/sources/communities_by_island.csv
  data/sources/race_ethnicity_by_county.csv
Raw downloads: data/raw/demographics/ (gitignored)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import USER_AGENT, fetch_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "demographics"
SRC = ROOT / "data" / "sources"
OUT_POP = SRC / "county_population_2020_2025.csv"
OUT_PLACES = SRC / "communities_by_island.csv"
OUT_RACE = SRC / "race_ethnicity_by_county.csv"

# ---------------------------------------------------------------- geography

COUNTY_FIPS = {"15001": "Hawaii", "15003": "Honolulu", "15005": "Kalawao",
               "15007": "Kauai", "15009": "Maui"}
COUNTY_ORDER = ("Honolulu", "Hawaii", "Maui", "Kauai", "Kalawao")
AREA_LABEL = {
    "State": "State of Hawaiʻi",
    "Honolulu": "Honolulu County = Oʻahu (island figure)",
    "Hawaii": "Hawaiʻi County = Hawaiʻi Island (island figure)",
    "Maui": "Maui County – multi-island: Maui, Molokaʻi, Lānaʻi, Kahoʻolawe (excludes Kalawao)",
    "Kauai": "Kauaʻi County – multi-island: Kauaʻi, Niʻihau",
    "Kalawao": "Kalawao County – Kalaupapa peninsula, Molokaʻi",
}
ISLAND_COUNTY = {"Oahu": "Honolulu", "Hawaii": "Hawaii", "Maui": "Maui", "Lanai": "Maui",
                 "Molokai": "Maui", "Kauai": "Kauai", "Niihau": "Kauai"}
ISLAND_LABEL = {"Oahu": "Oʻahu", "Hawaii": "Hawaiʻi Island", "Maui": "Maui",
                "Lanai": "Lānaʻi", "Molokai": "Molokaʻi", "Kauai": "Kauaʻi",
                "Niihau": "Niʻihau"}
SINGLE_ISLAND_COUNTIES = ("Honolulu", "Hawaii")

# ---------------------------------------------------------------- sources

DC = "https://data.census.gov/api/access/data/table"
G_COUNTY = "040XX00US15%240500000"
G_STATE = "0400000US15"
G_PLACE = "040XX00US15%241600000"
ACS_YEAR = 2024                                  # ACS 2020-2024 5-year (newest, checked 2026-10-27)
ACS_VINTAGE = "ACS 2020-2024 5-year"
ACS1_YEAR = 2025                                 # ACS 2025 1-year, released 2026-10-29
ACS1_VINTAGE = "ACS 2025 1-year"
ACS1_COUNTIES = ("Honolulu", "Hawaii", "Maui", "Kauai")      # 65,000+ people; not Kalawao
ACS1_KEPT = ("ACS 2025 1-year not published for this {what}; ACS 2020-2024 5-year figure "
             "kept.")
CONTROLLED = ("No margin of error: the 1-year county total is controlled to the Census "
              "Bureau's population estimates.")
PL_VINTAGE = "2020 Census (PL 94-171), April 1, 2020"
DHCA_VINTAGE = "2020 Census DHC-A, April 1, 2020"
PEP_VINTAGE = "Census Bureau Population Estimates, Vintage 2025 (July 1, 2025)"
PEP_TOTALS_URL = ("https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/"
                  "counties/totals/co-est2025-alldata.csv")
PEP_CHAR_URL = ("https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/"
                "counties/asrh/cc-est2025-alldata-15.csv")
PEP_NOTE = ("Vintage 2025 released 2026-06-25; also republished by DBEDT at "
            "https://census.hawaii.gov/population-estimate/")
PEP_YEAR_CODE = "7"                              # cc-est2025 YEAR 7 = July 1, 2025
DBEDT_URL = "https://files.hawaii.gov/dbedt/economic/databook/db2025/DB2025_section01.xlsx"
DBEDT_TABLE = "DBEDT State Data Book 2025, table 01.12"


def dc_url(table_id: str, g: str, popgroup: str = "") -> str:
    return f"{DC}?g={g}&id={table_id}" + (f"&t={popgroup}" if popgroup else "")


def acs_id(table: str) -> str:
    return f"ACSDT5Y{ACS_YEAR}.{table}"


def acs1_id(table: str) -> str:
    return f"ACSDT1Y{ACS1_YEAR}.{table}"


ACS_TABLES = ("B01003", "B02001", "B02008", "B02009", "B02010", "B02011", "B02012",
              "B03002", "B02015", "B02016", "B02018", "B02019")
PL_TABLES = ("P1", "P2")
DHCA_TABLE = "DECENNIALDDHCA2020.T01001"

# group -> (ACS alone var, ACS alone-or-in-combination var, DHC-A alone, DHC-A AOIC)
# Variable labels verified against api.census.gov/data/2024/acs/acs5/groups/*.json and
# DHC-A POPGROUP codes against api.census.gov/data/2020/dec/ddhca/variables/POPGROUP.json.
DETAILED = {
    "Native Hawaiian":            ("B02016_002", "B02019_002", "3883", "3925"),
    "Samoan":                     ("B02016_003", "B02019_003", "3886", "3928"),
    "Tongan":                     ("B02016_004", "B02019_004", "3888", "3930"),
    "Chamorro":                   ("B02016_006", "B02019_006", "3896", "3938"),
    "Chuukese":                   ("B02016_007", "B02019_007", "3897", "3939"),
    "Marshallese":                ("B02016_009", "B02019_009", "3901", "3943"),
    "Other Micronesian":          ("B02016_010", "B02019_010", "3908", "3950"),
    "Filipino":                   ("B02015_012", "B02018_012", "3797", "3854"),
    "Japanese":                   ("B02015_004", "B02018_004", "3767", "3824"),
    "Chinese, except Taiwanese":  ("B02015_002", "B02018_002", "3765", "3822"),
    "Korean":                     ("B02015_005", "B02018_005", "3768", "3825"),
    "Vietnamese":                 ("B02015_019", "B02018_019", "3804", "3861"),
}
EXPECTED_LABEL = {                                # last label segment, for verification
    "B02016_002": "Native Hawaiian", "B02016_003": "Samoan", "B02016_004": "Tongan",
    "B02016_006": "Chamorro", "B02016_007": "Chuukese", "B02016_009": "Marshallese",
    "B02016_010": "Other Micronesian", "B02015_012": "Filipino", "B02015_004": "Japanese",
    "B02015_002": "Chinese, except Taiwanese", "B02015_005": "Korean",
    "B02015_019": "Vietnamese",
}
# broad group -> (ACS alone var, ACS AOIC var, PEP alone prefix, PEP AOIC prefix)
BROAD = {
    "White":                             ("B02001_002", "B02008_001", "WA", "WAC"),
    "Black or African American":         ("B02001_003", "B02009_001", "BA", "BAC"),
    "American Indian and Alaska Native": ("B02001_004", "B02010_001", "IA", "IAC"),
    "Asian":                             ("B02001_005", "B02011_001", "AA", "AAC"),
    "Native Hawaiian and Other Pacific Islander": ("B02001_006", "B02012_001", "NA", "NAC"),
    "Some other race":                   ("B02001_007", "", "", ""),
    "Two or more races":                 ("B02001_008", "", "TOM", ""),
}
HISPANIC = ("B03002_012", "H")
BROAD_ALONE_SUM_TOTAL = "B02001_001"


# ---------------------------------------------------------------- download

def fetch_bytes(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as r:
        return r.read()


def fetch_table(url: str) -> dict:
    """data.census.gov table. HTTP 204 (no rows published for any geography, e.g. every
    county below the DHC-A threshold) is kept as an empty table, not an error."""
    body = fetch_bytes(url)
    if not body.strip():
        return {"response": {"data": [], "dataAPIURI": "", "no_content": True}}
    return json.loads(body.decode("utf-8"))


def raw_jobs() -> dict:
    """raw file name -> download URL."""
    jobs = {}
    for t in ACS_TABLES:
        jobs[f"acs_{t}_county.json"] = dc_url(acs_id(t), G_COUNTY)
        jobs[f"acs_{t}_state.json"] = dc_url(acs_id(t), G_STATE)
    for t in ("B02001", "B02015", "B02016", "B02018", "B02019"):
        jobs[f"acs_{t}_labels.json"] = f"https://api.census.gov/data/{ACS_YEAR}/acs/acs5/groups/{t}.json"
    for t in ACS_TABLES:
        jobs[f"acs1_{t}_county.json"] = dc_url(acs1_id(t), G_COUNTY)
    for t in ("B02001", "B02015", "B02016", "B02018", "B02019"):
        jobs[f"acs1_{t}_labels.json"] = f"https://api.census.gov/data/{ACS1_YEAR}/acs/acs1/groups/{t}.json"
    jobs["acs_B01003_place.json"] = dc_url(acs_id("B01003"), G_PLACE)
    for t in PL_TABLES:
        jobs[f"pl_{t}_county.json"] = dc_url(f"DECENNIALPL2020.{t}", G_COUNTY)
        jobs[f"pl_{t}_state.json"] = dc_url(f"DECENNIALPL2020.{t}", G_STATE)
    jobs["pl_P1_place.json"] = dc_url("DECENNIALPL2020.P1", G_PLACE)
    for codes in DETAILED.values():
        for pg in codes[2:]:
            jobs[f"dhca_{pg}_county.json"] = dc_url(DHCA_TABLE, G_COUNTY, pg)
            jobs[f"dhca_{pg}_state.json"] = dc_url(DHCA_TABLE, G_STATE, pg)
    jobs["co-est2025-alldata.csv"] = PEP_TOTALS_URL
    jobs["cc-est2025-alldata-15.csv"] = PEP_CHAR_URL
    jobs["DB2025_section01.xlsx"] = DBEDT_URL
    return jobs


def download_all(pause: float = 1.0) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for name, url in raw_jobs().items():
        path = RAW / name
        try:
            if url.startswith(DC):
                path.write_text(json.dumps(fetch_table(url)), encoding="utf-8")
            elif name.endswith(".json"):
                path.write_text(json.dumps(fetch_json(url)), encoding="utf-8")
            else:
                path.write_bytes(fetch_bytes(url))
        except (OSError, RuntimeError, ValueError) as e:
            if not name.startswith("acs1_"):
                raise
            # ACS 1-year table not published (yet): recorded, the 5-year figure is kept
            path.write_text(json.dumps({"response": {"data": [], "unavailable": str(e)[:200]}}),
                            encoding="utf-8")
        print(f"  {name}")
        time.sleep(pause)


# ---------------------------------------------------------------- parsing helpers

def dc_rows(name: str) -> tuple:
    """data.census.gov response -> (rows as dicts, equivalent api.census.gov URL).
    A missing ACS 1-year file counts as not published."""
    if name.startswith("acs1_") and not (RAW / name).exists():
        return [], ""
    resp = json.loads((RAW / name).read_text(encoding="utf-8"))["response"]
    data = resp["data"]
    if not data:
        return [], resp.get("dataAPIURI", "")
    return [dict(zip(data[0], r)) for r in data[1:]], resp.get("dataAPIURI", "")


def num(v):
    """Published value or None. ACS uses negative sentinels for "not available"."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x < 0 else x


def county_of(geo_id: str) -> str:
    return "State" if geo_id.endswith("US15") else COUNTY_FIPS.get(geo_id[-5:], "")


def norm_name(s: str) -> str:
    """Place name without diacritics, ʻokina, 'CDP' or county suffix."""
    s = re.sub(r"\s*\((\w+) County\)", "", s.split(",")[0])
    s = re.sub(r"\s+CDP$", "", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[ʻ‘’']", "", s)
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def name_county(place_name: str) -> str:
    m = re.search(r"\((\w+) County\)", place_name)
    return m.group(1) if m else ""


def xlsx_sheet(path: Path, sheet: str) -> list:
    """Rows of one worksheet as lists of strings (standard library only)."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
          "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
            shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rid = next(s for s in wb.find("m:sheets", ns) if s.get("name") == sheet).get(f"{{{ns['r']}}}id")
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    target = next(r.get("Target") for r in rels if r.get("Id") == rid).lstrip("/")
    target = target if target.startswith("xl/") else "xl/" + target
    rows = []
    for row in ET.fromstring(z.read(target)).iter(f"{{{ns['m']}}}row"):
        cells = {}
        for c in row.findall("m:c", ns):
            col = re.match(r"[A-Z]+", c.get("r")).group()
            v = c.find("m:v", ns)
            if c.get("t") == "s" and v is not None:
                cells[col] = shared[int(v.text)]
            elif c.get("t") == "inlineStr":
                cells[col] = "".join(x.text or "" for x in c.iter(f"{{{ns['m']}}}t"))
            else:
                cells[col] = v.text if v is not None else ""
        rows.append([cells.get(k, "") for k in "ABCD"])
    return rows


def dbedt_islands(path: Path) -> list:
    """Table 01.12 -> [(island, place or '' for the island row, population or None)]."""
    out, island = [], None
    for name, level, pop, _hh in xlsx_sheet(path, "01.12"):
        name = name.strip()
        if level == "level 1":
            island = name
            out.append((island, "", num(pop)))
        elif level == "level 2" and island:
            out.append((island, name, num(pop)))
    return out


def pep_rows() -> list:
    with open(RAW / "co-est2025-alldata.csv", newline="", encoding="latin-1") as fh:
        return [r for r in csv.DictReader(fh) if r["STATE"] == "15"]


def pep_char() -> dict:
    """county (or State) -> July 1, 2025 all-ages row of cc-est2025-alldata-15."""
    out = {}
    with open(RAW / "cc-est2025-alldata-15.csv", newline="", encoding="latin-1") as fh:
        for r in csv.DictReader(fh):
            if r["YEAR"] == PEP_YEAR_CODE and r["AGEGRP"] == "0":
                out[COUNTY_FIPS["15" + r["COUNTY"]]] = r
    return out


def pep_sum(row: dict, prefix: str) -> int:
    return int(row[f"{prefix}_MALE"]) + int(row[f"{prefix}_FEMALE"])


def pct(n, d):
    return "" if n is None or not d else round(100 * n / d, 2)


def fmt(x):
    return "" if x is None else int(x)


# ---------------------------------------------------------------- A. county totals

def county_totals() -> list:
    pl, pl_api = dc_rows("pl_P1_county.json")
    pl_state, _ = dc_rows("pl_P1_state.json")
    pl_by = {county_of(r["GEO_ID"]): num(r["P1_001N"]) for r in pl + pl_state}
    pep = {("State" if r["COUNTY"] == "000" else COUNTY_FIPS["15" + r["COUNTY"]]): r
           for r in pep_rows()}
    acs5 = acs_values("B01003")[0]
    acs1 = acs1_values("B01003")
    out = []
    for c in ("State",) + COUNTY_ORDER:
        r = pep[c]
        p20, p25 = pl_by[c], num(r["POPESTIMATE2025"])
        a5, a1 = acs5.get(c, {}), acs1.get(c) if c in ACS1_COUNTIES else None
        est1 = num((a1 or {}).get("B01003_001E"))
        moe1 = num((a1 or {}).get("B01003_001M"))
        acs1_note = (
            "Not in the ACS 1-year (fewer than 65,000 people); ACS 2020-2024 5-year kept."
            if c == "Kalawao" else "State figure not refreshed (county figures only)."
            if c == "State" else ACS1_KEPT.format(what="table")
            if est1 is None else "" if moe1 is not None else CONTROLLED)
        out.append({
            "county": c, "area_label": AREA_LABEL[c],
            "pop_2020_census": fmt(p20), "estimates_base_2020": r["ESTIMATESBASE2020"],
            "pop_2025_v2025": fmt(p25),
            "pop_acs_2020_2024": fmt(num(a5.get("B01003_001E"))),
            "moe_acs_2020_2024": fmt(num(a5.get("B01003_001M"))),
            "pop_acs_2025_1yr": fmt(est1), "moe_acs_2025_1yr": fmt(moe1),
            "acs_2025_1yr_note": acs1_note,
            "change_2020_2025": fmt(p25 - p20), "pct_change": pct(p25 - p20, p20),
            "table_ids": "DECENNIALPL2020.P1 (P1_001N); CO-EST2025-ALLDATA (POPESTIMATE2025); "
                         f"{acs_id('B01003')}; " + (acs1_id("B01003") if est1 is not None else ""),
            "source_urls": f"{dc_url('DECENNIALPL2020.P1', G_COUNTY)} ; {PEP_TOTALS_URL}",
            "vintage": f"{PL_VINTAGE}; {PEP_VINTAGE}; {ACS_VINTAGE}"
                       + (f"; {ACS1_VINTAGE}" if est1 is not None else ""),
            "note": PEP_NOTE + ". Change = Vintage 2025 minus the 2020 Census count; "
                    "the estimates base differs slightly from the count.",
        })
    return out


# ---------------------------------------------------------------- B. communities

def assign_islands(places: list, dbedt: list) -> tuple:
    """places: [{'geoid','name'}]. Returns ({geoid: (island, dbedt_name)}, unassigned, unused)."""
    index = {}
    for island, place, _ in dbedt:
        if place:
            index.setdefault(norm_name(place), []).append((island, place))
    assigned, unassigned, used = {}, [], set()
    for p in places:
        cands = index.get(norm_name(p["name"]), [])
        hint = name_county(p["name"])
        if hint:
            cands = [c for c in cands if ISLAND_COUNTY.get(c[0].strip()) == hint]
        if len(cands) == 1:
            assigned[p["geoid"]] = (cands[0][0].strip(), cands[0][1])
            used.add(cands[0])
        else:
            unassigned.append(p["name"])
    unused = [f"{i}: {n}" for i, n in
              ((i, n) for vals in index.values() for i, n in vals) if (i, n) not in used]
    return assigned, unassigned, unused


def communities() -> tuple:
    acs, _ = dc_rows("acs_B01003_place.json")
    pl, _ = dc_rows("pl_P1_place.json")
    pl_by = {r["GEO_ID"]: num(r["P1_001N"]) for r in pl}
    acs_c, _ = dc_rows("acs_B01003_county.json")
    pl_c, _ = dc_rows("pl_P1_county.json")
    county_acs = {county_of(r["GEO_ID"]): (num(r["B01003_001E"]), num(r["B01003_001M"])) for r in acs_c}
    county_pl = {county_of(r["GEO_ID"]): num(r["P1_001N"]) for r in pl_c}
    dbedt = dbedt_islands(RAW / "DB2025_section01.xlsx")
    island_total = {i.strip(): pop for i, place, pop in dbedt if not place}

    places = [{"geoid": r["GEO_ID"], "name": r["NAME"], "acs": num(r["B01003_001E"]),
               "moe": num(r["B01003_001M"]), "pl": pl_by.get(r["GEO_ID"])} for r in acs]
    assigned, unassigned, unused = assign_islands(places, dbedt)

    place_tables = "ACSDT5Y2024.B01003; DECENNIALPL2020.P1; " + DBEDT_TABLE
    place_urls = f"{dc_url(acs_id('B01003'), G_PLACE)} ; {dc_url('DECENNIALPL2020.P1', G_PLACE)} ; {DBEDT_URL}"
    vintage = f"{ACS_VINTAGE}; {PL_VINTAGE}"
    rows = []
    for island in ISLAND_COUNTY:
        county = ISLAND_COUNTY[island]
        mine = sorted((p for p in places if assigned.get(p["geoid"], ("",))[0] == island),
                      key=lambda p: -(p["acs"] or 0))
        rows.append({
            "row_type": "island_total", "island": ISLAND_LABEL[island], "county": county,
            "place": "", "geoid": "", "rank_in_island": "",
            "acs_2020_2024": fmt(island_total.get(island)), "acs_moe_90": "",
            "pl_2020": "", "share_of_total_pct": "", "dbedt_name": island,
            "table_ids": DBEDT_TABLE + " (from ACS 2020-2024 B01003)", "source_urls": DBEDT_URL,
            "vintage": ACS_VINTAGE,
            "note": ("No Census Designated Places on Niʻihau (DBEDT 01.12 note [a])"
                     if island == "Niihau" else "Island total as published by DBEDT"),
        })
        for rank, p in enumerate(mine, 1):
            rows.append({
                "row_type": "place", "island": ISLAND_LABEL[island], "county": county,
                "place": p["name"].split(",")[0], "geoid": p["geoid"], "rank_in_island": rank,
                "acs_2020_2024": fmt(p["acs"]), "acs_moe_90": fmt(p["moe"]),
                "pl_2020": fmt(p["pl"]),
                "share_of_total_pct": pct(p["acs"], island_total.get(island)),
                "dbedt_name": assigned[p["geoid"]][1],
                "table_ids": place_tables, "source_urls": place_urls, "vintage": vintage,
                "note": "Share = ACS place population / DBEDT island total",
            })
    for county in ("Honolulu", "Hawaii", "Maui", "Kauai"):
        tot, tot_moe = county_acs[county]
        mine = [p for p in places if ISLAND_COUNTY.get(assigned.get(p["geoid"], ("",))[0]) == county]
        cdp = sum(p["acs"] or 0 for p in mine)
        cdp_pl = sum(p["pl"] or 0 for p in mine)
        moe = math.sqrt((tot_moe or 0) ** 2 + sum((p["moe"] or 0) ** 2 for p in mine))
        islands = [ISLAND_LABEL[i] for i, c in ISLAND_COUNTY.items() if c == county]
        single = county in SINGLE_ISLAND_COUNTIES
        rows.append({
            "row_type": "outside_cdp" if single else "outside_cdp_county_level",
            "island": islands[0] if single else " + ".join(islands), "county": county,
            "place": "Outside any CDP", "geoid": "", "rank_in_island": "",
            "acs_2020_2024": fmt(tot - cdp), "acs_moe_90": round(moe),
            "pl_2020": fmt(county_pl[county] - cdp_pl),
            "share_of_total_pct": pct(tot - cdp, tot), "dbedt_name": "",
            "table_ids": "ACSDT5Y2024.B01003 (county and place); DECENNIALPL2020.P1 (county and place)",
            "source_urls": f"{dc_url(acs_id('B01003'), G_COUNTY)} ; {dc_url('DECENNIALPL2020.P1', G_COUNTY)}",
            "vintage": vintage,
            "note": (f"County total minus the sum of its CDPs; county total ACS {fmt(tot)}, "
                     f"2020 Census {fmt(county_pl[county])}. MOE approximated with the Census "
                     "sum-of-squares formula (the county total is a controlled ACS estimate with no MOE)."
                     + ("" if single else " County-level remainder for a multi-island county: "
                        "not split by island.")),
        })
    return rows, unassigned, unused


# ---------------------------------------------------------------- C. race/ethnicity

def acs_values(table: str) -> tuple:
    rows, api = [], ""
    for geo in ("county", "state"):
        r, a = dc_rows(f"acs_{table}_{geo}.json")
        rows += r
        api = api or a
    return {county_of(r["GEO_ID"]): r for r in rows}, api


def acs1_values(table: str) -> dict:
    """county -> row of the ACS 2025 1-year table ({} when the table is not published)."""
    return {county_of(r["GEO_ID"]): r for r in dc_rows(f"acs1_{table}_county.json")[0]}


def acs_label(var: str, prefix: str = "acs") -> str:
    table = var.split("_")[0]
    path = RAW / f"{prefix}_{table}_labels.json"
    if not path.exists():
        return ""
    meta = json.loads(path.read_text(encoding="utf-8"))["variables"].get(var + "E", {})
    return meta.get("label", "").split("!!")[-1].rstrip(":")


def race_rows() -> list:
    tables = {t: acs_values(t) for t in ACS_TABLES}
    totals = {c: num(r["B01003_001E"]) for c, r in tables["B01003"][0].items()}
    tables1 = {t: acs1_values(t) for t in ACS_TABLES}
    totals1 = {c: num(r.get("B01003_001E")) for c, r in tables1["B01003"].items()}
    pl = {county_of(r["GEO_ID"]): num(r["P1_001N"])
          for f in ("pl_P1_county.json", "pl_P1_state.json") for r in dc_rows(f)[0]}
    pep = pep_char()
    pep["State"] = {k: sum(int(pep[c][k]) for c in COUNTY_ORDER) if k.endswith(("MALE", "POP")) else ""
                    for k in pep["Honolulu"]}
    areas = ("State",) + COUNTY_ORDER
    out = []

    def acs_row(c, group, gtype, measure, var):
        table = var.split("_")[0]
        kept = ""
        if c in ACS1_COUNTIES:                       # ACS 2025 1-year where published
            r1 = tables1[table].get(c)
            est1 = num((r1 or {}).get(var + "E"))
            if r1 is not None and est1 is not None:
                moe1 = num(r1.get(var + "M"))
                note = "" if moe1 is not None else \
                    f"MOE not published (annotation {r1.get(var + 'MA') or r1.get(var + 'M')})"
                out.append({
                    "county": c, "area_label": AREA_LABEL[c], "group": group, "group_type": gtype,
                    "measure": measure, "source": ACS1_VINTAGE, "vintage": ACS1_VINTAGE,
                    "count": fmt(est1), "moe_90": fmt(moe1), "pct_of_county": pct(est1, totals1.get(c)),
                    "county_total": fmt(totals1.get(c)), "status": "published",
                    "table_id": acs1_id(table), "variable": var + "E",
                    "source_url": dc_url(acs1_id(table), G_COUNTY), "note": note,
                })
                return
            kept = ACS1_KEPT.format(what="table" if not tables1[table] else "cell")
        r = tables[table][0].get(c, {})
        est, moe = num(r.get(var + "E")), num(r.get(var + "M"))
        status = "published" if est is not None else "not available"
        note = ""
        if est is not None and moe is None:
            note = "MOE not published (controlled estimate or annotation " \
                   f"{r.get(var + 'MA') or r.get(var + 'M')})"
        out.append({
            "county": c, "area_label": AREA_LABEL[c], "group": group, "group_type": gtype,
            "measure": measure, "source": ACS_VINTAGE, "vintage": ACS_VINTAGE,
            "count": fmt(est), "moe_90": fmt(moe), "pct_of_county": pct(est, totals.get(c)),
            "county_total": fmt(totals.get(c)), "status": status,
            "table_id": acs_id(table), "variable": var + "E",
            "source_url": dc_url(acs_id(table), G_STATE if c == "State" else G_COUNTY),
            "note": " ".join(x for x in (kept, note) if x),
        })

    def pep_row(c, group, measure, prefix):
        r = pep[c]
        n, tot = pep_sum(r, prefix), int(r["TOT_POP"])
        out.append({
            "county": c, "area_label": AREA_LABEL[c], "group": group, "group_type": "broad",
            "measure": measure, "source": PEP_VINTAGE, "vintage": PEP_VINTAGE,
            "count": n, "moe_90": "", "pct_of_county": pct(n, tot), "county_total": tot,
            "status": "published", "table_id": "CC-EST2025-ALLDATA-15",
            "variable": f"{prefix}_MALE+{prefix}_FEMALE (YEAR=7, AGEGRP=0)",
            "source_url": PEP_CHAR_URL,
            "note": "Estimates have no published MOE. State = sum of counties." if c == "State"
                    else "Estimates have no published MOE",
        })

    for c in areas:
        for group, (a_var, c_var, a_pg, c_pg) in DETAILED.items():
            acs_row(c, group, "detailed", "alone", a_var)
            acs_row(c, group, "detailed", "alone_or_in_combination", c_var)
        for group, (a_var, c_var, pa, pc) in BROAD.items():
            acs_row(c, group, "broad", "alone", a_var)
            if c_var:
                acs_row(c, group, "broad", "alone_or_in_combination", c_var)
            if pa:
                pep_row(c, group, "alone", pa)
            if pc:
                pep_row(c, group, "alone_or_in_combination", pc)
        acs_row(c, "Hispanic or Latino (any race)", "broad", "any_race", HISPANIC[0])
        pep_row(c, "Hispanic or Latino (any race)", "any_race", HISPANIC[1])

    for group, (_, _, a_pg, c_pg) in DETAILED.items():
        for measure, pg in (("alone", a_pg), ("alone_or_in_combination", c_pg)):
            rows = []
            for geo in ("county", "state"):
                rows += dc_rows(f"dhca_{pg}_{geo}.json")[0]
            got = {county_of(r["GEO_ID"]): r for r in rows}
            for c in areas:
                r = got.get(c)
                n = num(r["T01001_001N"]) if r else None
                label = r["POPGROUP_LABEL"] if r else ""
                out.append({
                    "county": c, "area_label": AREA_LABEL[c], "group": group,
                    "group_type": "detailed", "measure": measure,
                    "source": "2020 Census", "vintage": DHCA_VINTAGE,
                    "count": fmt(n), "moe_90": "", "pct_of_county": pct(n, pl.get(c)),
                    "county_total": fmt(pl.get(c)),
                    "status": "published" if n is not None else "suppressed",
                    "table_id": DHCA_TABLE, "variable": f"T01001_001N, POPGROUP={pg} ({label or 'not published for this geography'})",
                    "source_url": dc_url(DHCA_TABLE, G_STATE if c == "State" else G_COUNTY, pg),
                    "note": ("Includes differential-privacy noise. % of 2020 Census total (P1_001N)."
                             if n is not None else
                             "Suppressed: below the DHC-A population threshold for this geography; not estimated."),
                })
    return out


def verify_labels() -> list:
    """Mismatches between the expected and the published ACS variable labels (5-year and
    2025 1-year: the same variable must mean the same group in both)."""
    bad = []
    for prefix in ("acs", "acs1"):
        for var, want in EXPECTED_LABEL.items():
            aoic = var.replace("B02016", "B02019").replace("B02015", "B02018")
            for v in (var, aoic):
                g = acs_label(v, prefix)
                if g and g != want:
                    bad.append(f"{prefix} {v}: {g!r} != {want!r}")
    for group, (a_var, *_rest) in BROAD.items():
        got = acs_label(a_var)
        if got and not got.lower().startswith(group.lower().split(" or ")[0][:5]):
            bad.append(f"{a_var}: {got!r} vs {group!r}")
    return bad


# ---------------------------------------------------------------- write

def write_csv(path: Path, rows: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--offline", action="store_true", help="re-tidy from data/raw only")
    args = ap.parse_args(argv)
    if not args.offline:
        print("Downloading to", RAW)
        download_all()
    bad = verify_labels()
    if bad:
        print("Label mismatch:", *bad, sep="\n  ")
        return 1
    pop = county_totals()
    places, unassigned, unused = communities()
    race = race_rows()
    write_csv(OUT_POP, pop)
    write_csv(OUT_PLACES, places)
    write_csv(OUT_RACE, race)
    print(f"Wrote {OUT_POP.name} ({len(pop)}), {OUT_PLACES.name} ({len(places)}), "
          f"{OUT_RACE.name} ({len(race)})")
    print(f"{'County':10}{'2020 Census':>13}{'V2025':>10}{'Change':>9}{'%':>7}")
    for r in pop:
        print(f"{r['county']:10}{r['pop_2020_census']:>13,}{r['pop_2025_v2025']:>10,}"
              f"{r['change_2020_2025']:>9,}{r['pct_change']:>7}")
    print("Places without an island:", unassigned or "none")
    print("DBEDT places without a Census CDP:", unused or "none")
    supp = sorted({(r["county"], r["group"], r["measure"]) for r in race if r["status"] != "published"})
    print(f"Suppressed / not available cells: {len(supp)}")
    for s in supp:
        print("  ", *s)
    return 1 if unassigned else 0


if __name__ == "__main__":
    sys.exit(main())
