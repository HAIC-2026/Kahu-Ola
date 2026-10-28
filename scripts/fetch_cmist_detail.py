#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – more CMIST detail per Census area (Census tract).

ACS 2020-2024 5-year, tract level, Hawaiʻi (aggregate published tables only):
  * B18102 hearing difficulty   – sum of the "With a hearing difficulty" rows (all ages)
  * B18103 vision difficulty    – sum of the "With a vision difficulty" rows (all ages)
  * B18104 cognitive difficulty – sum of the "With a cognitive difficulty" rows (age 5+)
  * B09020 age 65+ living alone – householders living alone, male + female
    (B09020_015 + B09020_018)
90% margins of error are combined with the Census sum-of-squares approximation.
The Census Data API needs a key, so tables come from the keyless data.census.gov download
of the same table; labels come from the api.census.gov variable list (no key needed).

Note: the CMIST counts in the tract layer come from CDC SVI 2022 (ACS 2018-2022). These
four counts are from the newer ACS 2020-2024 release; both use 2020 Census tracts.

Usage:  python3 scripts/fetch_cmist_detail.py            (download, cache, tidy)
        python3 scripts/fetch_cmist_detail.py --offline  (re-tidy from data/raw)
Output: data/sources/cmist_detail_by_tract.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import fetch_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "acs_detail"
OUT = ROOT / "data" / "sources" / "cmist_detail_by_tract.csv"
YEAR = 2024
VINTAGE = "ACS 2020-2024 5-year"
G_TRACT = "040XX00US15%241400000"
MEASURES = {   # field -> (table, label test on the last label part)
    "hearing": ("B18102", lambda leaf, parts: leaf == "With a hearing difficulty"),
    "vision": ("B18103", lambda leaf, parts: leaf == "With a vision difficulty"),
    "cognitive": ("B18104", lambda leaf, parts: leaf == "With a cognitive difficulty"),
    "age65_alone": ("B09020", lambda leaf, parts: leaf == "Living alone" and "Householder" in parts),
}
FIELDS = ["tract_fips", "hearing", "hearing_moe", "vision", "vision_moe", "cognitive",
          "cognitive_moe", "age65_alone", "age65_alone_moe", "tables", "vintage", "source_url"]


def data_url(table: str) -> str:
    return f"https://data.census.gov/api/access/data/table?g={G_TRACT}&id=ACSDT5Y{YEAR}.{table}"


def labels_url(table: str) -> str:
    return f"https://api.census.gov/data/{YEAR}/acs/acs5/groups/{table}.json"


def download() -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    for table in sorted({t for t, _ in MEASURES.values()}):
        (RAW / f"{table}_tract.json").write_text(json.dumps(fetch_json(data_url(table))))
        (RAW / f"{table}_labels.json").write_text(json.dumps(fetch_json(labels_url(table))))
        print(f"  {table}")
        time.sleep(1)


def variables(table: str, test) -> list:
    meta = json.loads((RAW / f"{table}_labels.json").read_text())["variables"]
    out = []
    for var, m in meta.items():
        if var.startswith(table) and var.endswith("E"):
            parts = [p.rstrip(":") for p in m["label"].split("!!")]
            if test(parts[-1], parts):
                out.append(var[:-1])
    return sorted(out)


def num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return None if x < 0 else x


def tidy() -> list:
    rows = {}
    for field, (table, test) in MEASURES.items():
        vars_ = variables(table, test)
        if not vars_:
            raise RuntimeError(f"{table}: no variables matched for {field}")
        resp = json.loads((RAW / f"{table}_tract.json").read_text())["response"]["data"]
        head = resp[0]
        for raw in resp[1:]:
            r = dict(zip(head, raw))
            fips = r["GEO_ID"][-11:]
            est = [num(r.get(v + "E")) for v in vars_]
            moe = [num(r.get(v + "M")) or 0.0 for v in vars_]
            row = rows.setdefault(fips, {"tract_fips": fips})
            row[field] = "" if any(e is None for e in est) else int(sum(est))
            row[f"{field}_moe"] = round(math.sqrt(sum(m * m for m in moe)))
    tables = ", ".join(f"ACSDT5Y{YEAR}.{t}" for t, _ in MEASURES.values())
    urls = " ; ".join(data_url(t) for t, _ in MEASURES.values())
    for row in rows.values():
        row.update({"tables": tables, "vintage": VINTAGE, "source_url": urls})
    return [rows[k] for k in sorted(rows)]


def load(path: Path = OUT) -> dict:
    """tract_fips -> row; empty if not built."""
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["tract_fips"]: r for r in csv.DictReader(fh)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ACS hearing/vision/cognitive and 65+ alone by tract")
    ap.add_argument("--offline", action="store_true", help="re-tidy from data/raw")
    if not ap.parse_args(argv).offline:
        download()
    rows = tidy()
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    tot = {f: sum(int(r[f] or 0) for r in rows) for f in MEASURES}
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(rows)} tracts; state totals {tot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
