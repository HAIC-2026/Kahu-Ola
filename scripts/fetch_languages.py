#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – language access by county (ACS 5-year table C16001).

C16001 = language spoken at home by ability to speak English, population 5 years and
over. County totals only: no individual data. Kalawao is grouped with Maui, as in
fetch_data.COUNTY_FIPS.

The Census Data API now requires a key even for small queries, so this uses the
Census Bureau's keyless data.census.gov download of the same table; the response
names the equivalent api.census.gov query (dataAPIURI), recorded in the output.

Usage:  python3 scripts/fetch_languages.py            (download, cache, tidy)
        python3 scripts/fetch_languages.py --offline  (re-tidy from data/raw)
Outputs:
  data/raw/acs_c16001_county.json, data/raw/acs_c16001_labels.json   (raw responses)
  data/sources/languages_by_county.csv                                (tidy, committed)
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import COUNTIES, COUNTY_FIPS, fetch_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "sources" / "languages_by_county.csv"

YEAR = 2024                       # ACS 2020-2024 5-year, latest with C16001 (checked 2026-10-27)
TABLE = "C16001"
DATA_URL = (f"https://data.census.gov/api/access/data/table"
            f"?g=040XX00US15%240500000&id=ACSDT5Y{YEAR}.{TABLE}")
LABELS_URL = f"https://api.census.gov/data/{YEAR}/acs/acs5/groups/{TABLE}.json"
LEP = 'Speak English less than "very well"'
FIELDS = ["county", "language", "speakers_5plus", "speak_english_less_than_very_well",
          "moe_90", "share_of_county_lep", "rank", "table", "acs_year", "source_url",
          "api_url", "fetched_at"]


def language_vars(labels: dict) -> dict:
    """language -> (total var, less-than-very-well var), from the C16001 label tree."""
    out = {}
    for var, meta in labels.items():
        if not (var.startswith(TABLE) and var.endswith("E")):
            continue
        parts = [p.rstrip(":") for p in meta["label"].split("!!")]
        if len(parts) == 3 and parts[2] != "Speak only English":
            out.setdefault(parts[2], [None, None])[0] = var
        elif len(parts) == 4 and parts[3] == LEP:
            out.setdefault(parts[2], [None, None])[1] = var
    return {k: tuple(v) for k, v in out.items() if all(v)}


def _num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x < 0 else x          # ACS uses negative sentinels for "not available"


def tidy(response: dict, labels: dict, fetched_at: str = "") -> list:
    """County x language rows, LEP = speaks English less than "very well"."""
    data = response["response"]["data"]
    header, rows = data[0], [dict(zip(data[0], r)) for r in data[1:]]
    api_url = response["response"].get("dataAPIURI", "")
    langs = language_vars(labels)
    agg = {}                                            # (county, language) -> [tot, lep, moe²]
    for r in rows:
        county = COUNTY_FIPS.get(str(r["GEO_ID"])[-5:])
        if not county:
            continue
        for lang, (tot_var, lep_var) in langs.items():
            a = agg.setdefault((county, lang), [0.0, 0.0, 0.0])
            a[0] += _num(r.get(tot_var)) or 0
            a[1] += _num(r.get(lep_var)) or 0
            m = _num(r.get(lep_var[:-1] + "M"))
            a[2] += (m or 0) ** 2                       # Census approximation for sums
    out = []
    for county in COUNTIES:
        mine = sorted(((lang, v) for (c, lang), v in agg.items() if c == county),
                      key=lambda x: (-x[1][1], x[0]))
        total_lep = sum(v[1] for _, v in mine)
        for rank, (lang, (tot, lep, moe2)) in enumerate(mine, 1):
            out.append({
                "county": county, "language": lang,
                "speakers_5plus": int(tot), "speak_english_less_than_very_well": int(lep),
                "moe_90": round(math.sqrt(moe2)),
                "share_of_county_lep": round(lep / total_lep, 4) if total_lep else 0.0,
                "rank": rank, "table": TABLE, "acs_year": f"{YEAR - 4}-{YEAR} 5-year",
                "source_url": DATA_URL, "api_url": api_url, "fetched_at": fetched_at,
            })
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ACS C16001 language access by county")
    ap.add_argument("--offline", action="store_true", help="re-tidy from data/raw")
    args = ap.parse_args(argv)
    RAW.mkdir(parents=True, exist_ok=True)
    raw_data, raw_labels = RAW / "acs_c16001_county.json", RAW / "acs_c16001_labels.json"
    if not args.offline:
        raw_data.write_text(json.dumps(fetch_json(DATA_URL)), encoding="utf-8")
        raw_labels.write_text(json.dumps(fetch_json(LABELS_URL)), encoding="utf-8")
    fetched = datetime.fromtimestamp(raw_data.stat().st_mtime, timezone.utc).isoformat(
        timespec="seconds")
    rows = tidy(json.loads(raw_data.read_text(encoding="utf-8")),
                json.loads(raw_labels.read_text(encoding="utf-8"))["variables"], fetched)
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows -> {OUT.relative_to(ROOT)}\n")
    for c in COUNTIES:
        top = [r for r in rows if r["county"] == c][:3]
        print(f"{c:<10}" + "; ".join(f"{r['language']} {r['speak_english_less_than_very_well']:,}"
                                     for r in top))
    return 0


if __name__ == "__main__":
    sys.exit(main())
