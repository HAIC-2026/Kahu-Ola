#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – Hawaiian display spellings for Census place (CDP) names.

Census and DBEDT publish CDP names without ʻokina or kahakō ("Kihei", "Waihee-Waiehu").
For anything a person reads, this map gives the official spelling from the USGS
Geographic Names Information System (GNIS), which records Board on Geographic Names
decisions for Hawaiʻi:
  1. a GNIS "Populated Place" in the same county with the same letters  -> that name
  2. else the GNIS "Census" record for the CDP, if it carries diacritics -> that name
  3. else, for hyphenated names, steps 1-2 applied to each part          ("Waiheʻe-Waiehu")
  4. else the Census spelling unchanged (nothing is guessed)
Matching ignores ʻokina, kahakō and case. A name with two different GNIS spellings in
the same county is left unchanged and reported.

IDs (GEOIDs, file keys) stay ASCII; only display text uses these spellings.

Usage:  python3 scripts/build_place_names.py            (download GNIS, build)
        python3 scripts/build_place_names.py --offline  (use data/raw cache)
Input:  data/sources/communities_by_island.csv (CDP list, Census names)
Output: data/sources/place_display_names.csv
"""
from __future__ import annotations

import argparse
import csv
import io
import re
import sys
import unicodedata
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import USER_AGENT  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
GNIS_URL = ("https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/"
            "DomesticNames/DomesticNames_HI_Text.zip")
RAW = ROOT / "data" / "raw" / "gnis" / "DomesticNames_HI_Text.zip"
COMMUNITIES = ROOT / "data" / "sources" / "communities_by_island.csv"
OUT = ROOT / "data" / "sources" / "place_display_names.csv"
FIELDS = ["cdp_geoid", "county", "census_name", "display_name", "method", "gnis_feature_id",
          "source", "source_url"]
GNIS_COUNTY = {"Kalawao": "Maui"}                  # Kalawao CDPs: none; tracts sit with Maui


def fold(s: str) -> str:
    """Letters only for matching: no ʻokina, kahakō or case."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[ʻ‘’']", "", s).lower().strip()


def load_gnis(path: Path = RAW) -> list:
    with zipfile.ZipFile(path) as z:
        member = next(n for n in z.namelist() if n.endswith("DomesticNames_HI.txt"))
        text = io.TextIOWrapper(z.open(member), encoding="utf-8-sig")
        return list(csv.DictReader(text, delimiter="|"))


def gnis_index(rows: list) -> tuple:
    """({(county, folded): {name: feature_id}} for populated places, same for CDP records)."""
    places, census = {}, {}
    for r in rows:
        county = GNIS_COUNTY.get(r["county_name"], r["county_name"])
        name = r["feature_name"]
        if r["feature_class"] == "Populated Place":
            places.setdefault((county, fold(name)), {})[name] = r["feature_id"]
        elif r["feature_class"] == "Census" and "(historical)" not in name:
            base = name.replace(" Census Designated Place", "")
            census.setdefault((county, fold(base)), {})[base] = r["feature_id"]
    return places, census


def lookup(county: str, name: str, places: dict, census: dict, ambiguous: list) -> tuple:
    """(display name, method, feature ids) or (None, '', '')."""
    key = (county, fold(name))
    hits = places.get(key, {})
    if len(hits) == 1:
        (n, fid), = hits.items()
        return n, "gnis_populated_place", fid
    if len(hits) > 1:
        ambiguous.append(f"{county}: {name} -> {sorted(hits)}")
    hits = census.get(key, {})
    if len(hits) == 1:
        (n, fid), = hits.items()
        if n != name:
            return n, "gnis_census", fid
    return None, "", ""


def build(cdps: list, gnis: list) -> tuple:
    """cdps: [(geoid, county, census_name)] -> (rows, ambiguous)."""
    places, census = gnis_index(gnis)
    rows, ambiguous = [], []
    for geoid, county, name in cdps:
        display, method, fid = lookup(county, name, places, census, ambiguous)
        if display is None and "-" in name:
            parts = [lookup(county, p, places, census, ambiguous) for p in name.split("-")]
            joined = "-".join(d or p for (d, _m, _f), p in zip(parts, name.split("-")))
            if joined != name:
                display, method = joined, "gnis_parts"
                fid = ";".join(f for _d, _m, f in parts if f)
        if display is None:
            display, method = name, "census_unchanged"
        assert fold(display) == fold(name), (name, display)       # letters never change
        rows.append({"cdp_geoid": geoid, "county": county, "census_name": name,
                     "display_name": display, "method": method, "gnis_feature_id": fid,
                     "source": "USGS GNIS Domestic Names, Hawaii (BGN official names)",
                     "source_url": GNIS_URL})
    return rows, ambiguous


def census_cdps(path: Path = COMMUNITIES) -> list:
    with open(path, newline="", encoding="utf-8") as fh:
        return [(r["geoid"][-7:], r["county"], re.sub(r" CDP( \(\w+ County\))?$", "", r["place"]))
                for r in csv.DictReader(fh) if r["row_type"] == "place"]


def load_display_names(path: Path = OUT) -> dict:
    """7-digit CDP GEOID -> display name. Empty if not built."""
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["cdp_geoid"]: r["display_name"] for r in csv.DictReader(fh)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Hawaiian display spellings for CDP names")
    ap.add_argument("--offline", action="store_true", help="use cached GNIS file")
    args = ap.parse_args(argv)
    if not args.offline:
        RAW.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(GNIS_URL, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=300) as r:
            RAW.write_bytes(r.read())
    rows, ambiguous = build(census_cdps(), load_gnis())
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    counts = {}
    for r in rows:
        counts[r["method"]] = counts.get(r["method"], 0) + 1
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(rows)} CDPs; {counts}")
    print("Unchanged (no GNIS spelling):",
          ", ".join(r["census_name"] for r in rows if r["method"] == "census_unchanged"))
    if ambiguous:
        print("Ambiguous:", *ambiguous, sep="\n  ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
