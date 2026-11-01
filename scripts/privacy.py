#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – small-number suppression and per-area citations.

Rule (app, map tooltips, panels, PDFs, annexes; app/app.js has the same rule in cnt()):
  * a per-area count of 0 shows 0;
  * a per-area count above 0 that rounds to less than 10 shows "fewer than 10";
  * in a Census area with fewer than 100 residents only the population is shown; every
    sub-count reads "suppressed (small area)".
County and state totals are not suppressed. Sorting and ranking may use the true value but
never show it. Margins of error are hidden whenever their count is hidden.

Citations: every per-area figure names its ACS table and years (CDC/ATSDR SVI 2022
documentation, variable table; ACS 2020-2024 detailed tables) and its 90% margin of error
where the source publishes one (SVI M_ columns; ACS MOE). Power-dependent counts are an
allocation of HHS emPOWER county totals and have no margin of error.

Usage:  python3 scripts/privacy.py      (writes data/sources/area_moe.csv from data/raw/svi.geojson)
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_SVI = ROOT / "data" / "raw" / "svi.geojson"
DETAIL = ROOT / "data" / "sources" / "cmist_detail_by_tract.csv"
OUT = ROOT / "data" / "sources" / "area_moe.csv"
MIN_COUNT = 10
SMALL_AREA = 100
FEWER = "fewer than 10"
SMALL = "suppressed (small area)"
PRIVACY_LINE = "Per-area counts from 1 to 9 are not shown. All figures are public Census Bureau, CDC and HHS estimates, not personal records."
NO_MOE = "no margin of error (model estimate)"
# area field -> (citation, MOE column in area_moe.csv or None)
CITE = {
    "population": ("ACS 2018–2022, table S0601 (via CDC/ATSDR SVI 2022)", "population"),
    "lep": ("ACS 2018–2022, table B16005 (via CDC/ATSDR SVI 2022)", "lep"),
    "power": ("HHS emPOWER county count, allocated by each area's share of people age 65 and older "
              "(estimate; no margin of error)", None),
    "disability": ("ACS 2018–2022, table DP02 (DP02_0072E, via CDC/ATSDR SVI 2022)", "disability"),
    "age65": ("ACS 2018–2022, table S0101 (S0101_C01_030E, via CDC/ATSDR SVI 2022)", "age65"),
    "no_car": ("ACS 2018–2022, table DP04 (DP04_0058E, households without a vehicle, via CDC/ATSDR "
               "SVI 2022) × people per household; margin of error scaled the same way", "no_car"),
    "hearing": ("ACS 2020–2024, table B18102", "hearing"),
    "vision": ("ACS 2020–2024, table B18103", "vision"),
    "cognitive": ("ACS 2020–2024, table B18104", "cognitive"),
    "age65_alone": ("ACS 2020–2024, table B09020", "age65_alone"),
}
MOE_FIELDS = ["population", "lep", "disability", "age65", "no_car", "hearing", "vision",
              "cognitive", "age65_alone"]
MOE_NOTE = ("± is the 90% margin of error published with the estimate (SVI M_ columns; ACS), "
            "scaled by the fraction of residents who live in the risk area.")


def suppressed(v, pop=None) -> bool:
    """True when a per-area count must not be shown."""
    if pop is not None and pop < SMALL_AREA:
        return True
    return v is not None and v > 0 and round(v) < MIN_COUNT


def count_text(v, pop=None, digits: int = 0) -> str:
    """A per-area count as shown anywhere a reader can see it."""
    if pop is not None and pop < SMALL_AREA:
        return SMALL
    if v is None:
        return "–"
    if v == 0:
        return "0"
    if round(v) < MIN_COUNT:
        return FEWER
    return f"{round(v, digits):,.{digits}f}" if digits else f"{round(v):,}"


def with_moe(v, moe, pop=None) -> str:
    """'96 ± 41'; the margin is hidden with its count, and absent when the source has none."""
    t = count_text(v, pop)
    if suppressed(v, pop) or moe is None or v is None:
        return t
    return f"{t} ± {round(moe):,}"


def load_moe(path: Path = OUT) -> dict:
    """{tract: {field: whole-area 90% MOE or None}} (committed; built from data/raw/svi.geojson)."""
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["tract_fips"]: {k: (float(r[k]) if r[k] not in ("", None) else None)
                                  for k in MOE_FIELDS} for r in csv.DictReader(fh)}


def build() -> int:
    if not RAW_SVI.exists():
        if OUT.exists():
            print(f"No {RAW_SVI.relative_to(ROOT)}: keeping the committed {OUT.relative_to(ROOT)}")
            return 0
        print(f"Build stopped: {RAW_SVI.relative_to(ROOT)} and {OUT.relative_to(ROOT)} are missing.",
              file=sys.stderr)
        return 1
    svi = json.loads(RAW_SVI.read_text(encoding="utf-8"))["features"]
    with open(DETAIL, newline="", encoding="utf-8") as fh:
        det = {r["tract_fips"]: r for r in csv.DictReader(fh)}
    num = lambda v: None if v in (None, "", -999, -999.0) or (isinstance(v, (int, float)) and v < 0) else float(v)  # noqa: E731
    rows = []
    for f in svi:
        p = f["properties"]
        fips = str(p.get("FIPS") or p.get("GEOID") or "")
        if not fips.startswith("15"):
            continue
        hh, pop = num(p.get("E_HH")), num(p.get("E_TOTPOP"))
        pph = pop / hh if hh and pop else None
        mveh = num(p.get("M_NOVEH"))
        d = det.get(fips, {})
        rows.append({"tract_fips": fips, "population": num(p.get("M_TOTPOP")), "lep": num(p.get("M_LIMENG")),
                     "disability": num(p.get("M_DISABL")), "age65": num(p.get("M_AGE65")),
                     "no_car": round(mveh * pph, 1) if mveh is not None and pph else None,
                     **{k: num(d.get(f"{k}_moe")) for k in ("hearing", "vision", "cognitive", "age65_alone")}})
    rows.sort(key=lambda r: r["tract_fips"])
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["tract_fips", *MOE_FIELDS], lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: ("" if v is None else (int(v) if float(v).is_integer() else v)) if k != "tract_fips" else v
                        for k, v in r.items()})
    print(f"Wrote {OUT.relative_to(ROOT)} ({len(rows)} Census areas)")
    return 0


if __name__ == "__main__":
    sys.exit(build())
