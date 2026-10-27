#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – detailed languages by area from ACS PUMS (2019-2023 5-year).

ACS table C16001 lumps Ilocano, Japanese, Hawaiian, Chuukese and Marshallese into
"Other Asian and Pacific Island languages". The PUMS person file keeps the detailed
language (LANP), the same source DBEDT used for State of Hawaii Data Book 2024,
Table 1.44. This script aggregates it; it never writes or prints microdata rows.

  * persons 5+ (AGEP >= 5) speaking a language other than English (LANP not blank)
  * limited English = speaks English less than "very well" (ENG in 2, 3, 4)
  * weights PWGTP; 90% MOE from the 80 replicate weights (successive differences:
    SE = sqrt(4/80 * sum((rep - est)^2)), MOE = 1.645 * SE)
  * PUMA -> county from the Census 2020 tract-to-PUMA relationship file. Hawaii's 2020
    PUMAs do NOT all nest within counties: PUMA 00100 covers Kauai, Maui and Kalawao, so
    those counties are reported as one area ("Kauai + Maui"). No split is invented.
  * cells with fewer than 100 weighted people or fewer than 10 sample persons are
    suppressed and shown as "<100"

Usage:  python3 scripts/build_languages_pums.py
Inputs (data/raw/pums, gitignored): csv_phi.zip, PUMS_Data_Dictionary_2019-2023.csv,
        2020_Census_Tract_to_2020_PUMA.txt
Outputs: data/sources/languages_by_county.csv           (by area, suppressed)
         data/sources/pums_language_state_summary.csv  (statewide, for DBEDT validation)
         data/sources/puma_county_2020.csv              (Hawaii PUMA -> counties)
"""
from __future__ import annotations

import csv
import io
import math
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "pums"
SRC = ROOT / "data" / "sources"

PUMS_URL = "https://www2.census.gov/programs-surveys/acs/data/pums/2023/5-Year/csv_phi.zip"
DICT_URL = ("https://www2.census.gov/programs-surveys/acs/tech_docs/pums/data_dict/"
            "PUMS_Data_Dictionary_2019-2023.csv")
REL_URL = ("https://www2.census.gov/geo/docs/maps-data/data/rel2020/"
           "2020_Census_Tract_to_2020_PUMA.txt")
DBEDT_URL = "https://files.hawaii.gov/dbedt/economic/databook/2024-individual/01/014424.pdf"
VINTAGE = "ACS PUMS 2019-2023 5-year"
COUNTY_FIPS = {"001": "Hawaii", "003": "Honolulu", "005": "Maui", "007": "Kauai", "009": "Maui"}
AREA_ORDER = ("Kauai + Maui", "Honolulu", "Hawaii")
LEP_CODES = {"2", "3", "4"}
N_REP = 80
MIN_WEIGHTED, MIN_N = 100, 10
SUPPRESSED = "<100"

# DBEDT Table 1.44 groupings: "Tagalog, Filipino"; "Chinese" incl. Mandarin, Cantonese and
# other Chinese languages; "Cebuano and other Philippine languages".
GROUPS = {"2910": "Tagalog, Filipino", "2920": "Tagalog, Filipino",
          "1970": "Chinese", "2000": "Chinese", "2030": "Chinese", "2050": "Chinese",
          "2950": "Cebuano and other Philippine languages",
          "3190": "Cebuano and other Philippine languages"}


def language_names(dict_path: Path) -> dict:
    """LANP code -> language name, with DBEDT groupings applied."""
    out = {}
    with open(dict_path, newline="", encoding="latin-1") as fh:
        for r in csv.reader(fh):
            if len(r) > 6 and r[0] == "VAL" and r[1] == "LANP" and r[4].isdigit():
                out[r[4]] = GROUPS.get(r[4], r[6])
    return out


def puma_counties(rel_path: Path, state: str = "15") -> dict:
    """PUMA -> sorted county names, from the 2020 tract-to-PUMA relationship file."""
    m = defaultdict(set)
    with open(rel_path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r["STATEFP"] == state:
                m[r["PUMA5CE"]].add(COUNTY_FIPS[r["COUNTYFP"]])
    return {p: sorted(c) for p, c in m.items()}


def area_of(counties: list) -> str:
    return counties[0] if len(counties) == 1 else " + ".join(sorted(counties))


def moe90(est: float, reps: list) -> float:
    return 1.645 * math.sqrt(4 / N_REP * sum((r - est) ** 2 for r in reps))


def aggregate(rows, names: dict, puma_area: dict) -> dict:
    """Stream person rows -> {(area, language): sums}. Rows are never kept."""
    agg = defaultdict(lambda: {"speakers": 0.0, "lep": 0.0, "n": 0, "n_lep": 0,
                               "lep_reps": [0.0] * N_REP})
    rep_cols = [f"PWGTP{i}" for i in range(1, N_REP + 1)]
    for r in rows:
        lanp = (r.get("LANP") or "").strip()
        if not lanp or not r.get("AGEP") or int(r["AGEP"]) < 5:
            continue
        lang = names.get(lanp, f"LANP {lanp}")
        w = float(r["PWGTP"])
        lep = (r.get("ENG") or "").strip() in LEP_CODES
        for key in ((puma_area[r["PUMA"]], lang), ("Hawaii State", lang)):
            a = agg[key]
            a["speakers"] += w
            a["n"] += 1
            if lep:
                a["lep"] += w
                a["n_lep"] += 1
                reps = a["lep_reps"]
                for i, c in enumerate(rep_cols):
                    reps[i] += float(r[c])
    return agg


def suppressed(weighted: float, n: int) -> bool:
    return weighted < MIN_WEIGHTED or n < MIN_N


def table(agg: dict, area: str, counties: str) -> list:
    """Aggregate rows for one area, ranked by limited-English speakers, suppressed."""
    cells = [(lang, a) for (ar, lang), a in agg.items() if ar == area]
    total_lep = sum(a["lep"] for _, a in cells)
    cells.sort(key=lambda x: (-x[1]["lep"], x[0]))
    out, rank = [], 0
    for lang, a in cells:
        sup_lep = suppressed(a["lep"], a["n_lep"])
        sup_spk = suppressed(a["speakers"], a["n"])
        if not sup_lep:
            rank += 1
        out.append({
            "area": area, "counties": counties, "language": lang,
            "speakers_5plus": SUPPRESSED if sup_spk else round(a["speakers"]),
            "speak_english_less_than_very_well": SUPPRESSED if sup_lep else round(a["lep"]),
            "moe_90": "" if sup_lep else round(moe90(a["lep"], a["lep_reps"])),
            "share_of_area_lep": "" if sup_lep or not total_lep else round(a["lep"] / total_lep, 4),
            "rank": rank if not sup_lep else "",
            "suppressed": sup_lep,
            "source": VINTAGE, "source_url": PUMS_URL, "puma_county_url": REL_URL,
        })
    return out


def main() -> int:
    need = [RAW / "csv_phi.zip", RAW / "PUMS_Data_Dictionary_2019-2023.csv",
            RAW / "2020_Census_Tract_to_2020_PUMA.txt"]
    if not all(p.exists() for p in need):
        print("Missing PUMS inputs in data/raw/pums – download:\n  " +
              "\n  ".join((PUMS_URL, DICT_URL, REL_URL)), file=sys.stderr)
        return 1
    names = language_names(need[1])
    pc = puma_counties(need[2])
    puma_area = {p: area_of(c) for p, c in pc.items()}
    nested = {p: len(c) == 1 for p, c in pc.items()}

    with zipfile.ZipFile(need[0]) as z, z.open("psam_p15.csv") as fh:
        agg = aggregate(csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8")), names, puma_area)

    SRC.mkdir(parents=True, exist_ok=True)
    with open(SRC / "puma_county_2020.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["puma", "counties", "area", "nests_in_one_county", "source_url"])
        for p in sorted(pc):
            w.writerow([p, ";".join(pc[p]), puma_area[p], nested[p], REL_URL])

    area_counties = defaultdict(set)
    for p, cs in pc.items():
        area_counties[puma_area[p]].update(cs)
    rows = [r for a in AREA_ORDER for r in table(agg, a, ";".join(sorted(area_counties[a])))]
    state = table(agg, "Hawaii State", "Hawaii;Honolulu;Kauai;Maui")
    fields = list(rows[0])
    for path, data in ((SRC / "languages_by_county.csv", rows),
                       (SRC / "pums_language_state_summary.csv", state)):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(data)

    print(f"PUMAs: {len(pc)}; nest within one county: "
          f"{sum(nested.values())}/{len(pc)} (not nested: "
          f"{', '.join(f'{p}={puma_area[p]}' for p in pc if not nested[p]) or 'none'})")
    print(f"Wrote {len(rows)} area x language rows "
          f"({sum(1 for r in rows if r['suppressed'])} suppressed) -> "
          f"data/sources/languages_by_county.csv")
    for a in AREA_ORDER:
        top = [r for r in rows if r["area"] == a and not r["suppressed"]][:6]
        print(f"  {a:<13}" + "; ".join(f"{r['language']} {r['speak_english_less_than_very_well']:,}"
                                       for r in top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
