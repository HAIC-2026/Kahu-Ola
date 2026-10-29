#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – Step 2: MAP.

Builds one statewide census-tract layer that combines:
  * CMIST indicators (CDC/ATSDR SVI 2022, from ACS 2018-2022)
  * hazard exposure (FEMA National Risk Index v1.20 + State tsunami evacuation zones)
  * electricity-dependent residents (HHS emPOWER, county total allocated to tracts)

De-identified, aggregate data only. No individual records are used or created.

Usage:
    python3 scripts/fetch_data.py      # downloads raw data first
    python3 scripts/build_map.py
Outputs:
    data/processed/afn_tracts.geojson  (map layer, loads into ArcGIS / QGIS / web)
    data/processed/afn_tracts.csv      (same attributes, no geometry)
    data/processed/coverage.json       (Metric 1: tract coverage by county)
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hawaii_time import now_hst  # noqa: E402
from geo import ZoneIndex, representative_point  # noqa: E402
from fetch_data import COUNTIES, NRI_HAZARD_LAYERS, county_from_fips  # noqa: E402
import fetch_cmist_detail  # noqa: E402
import block_shares  # noqa: E402
from raw_inputs import MissingInput, load_geojson  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "processed"

# SVI estimate fields used as CMIST proxies (verified field names, SVI 2022).
CMIST_FIELDS = {
    "C": {"limited_english": "E_LIMENG"},
    "M": {"uninsured": "E_UNINSUR"},          # + power_dependent from emPOWER
    "I": {"disability": "E_DISABL", "age_65_plus": "E_AGE65"},
    "S": {"age_17_under": "E_AGE17", "group_quarters": "E_GROUPQ"},
    "T": {"households_no_vehicle": "E_NOVEH"},
}
HOUSING_FIELDS = {"multi_unit_10plus": "E_MUNIT", "mobile_homes": "E_MOBILE"}
# More CMIST detail from ACS 2020-2024 5-year tract tables (scripts/fetch_cmist_detail.py)
DETAIL_FIELDS = {"C_hearing_difficulty": "hearing", "C_vision_difficulty": "vision",
                 "I_cognitive_difficulty": "cognitive", "S_age65_living_alone": "age65_alone"}

# Confirmed via Datatrove (Oct 27, 2026). Do NOT use Any_Healthcare_Srvc_Any_DME:
# it sums service columns and double-counts people with several services.
EMPOWER_COUNT_FIELD = "Power_Dependent_Devices_DME"
EMPOWER_FIPS_FIELD = "FIPS_Code"


def num(v):
    """SVI uses -999 for missing values."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f <= -999 else f


def load(key: str):
    p = RAW / f"{key}.geojson"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# ---------------------------------------------------------------- emPOWER

def empower_by_county(fc: dict | None, field: str | None = EMPOWER_COUNT_FIELD):
    """Return ({county: count}, field_used). Picks the count field by name if not set."""
    if not fc or not fc.get("features"):
        return {}, None
    sample = fc["features"][0].get("properties") or {}
    if field is None:
        numeric = [k for k, v in sample.items() if isinstance(v, (int, float))]
        preferred = [k for k in numeric
                     if any(s in k.lower() for s in ("dme", "elec", "power"))
                     and "bene" not in k.lower()]
        field = (preferred or [None])[0]
    if field is None:
        return {}, None
    out = {}
    for f in fc["features"]:
        p = f.get("properties") or {}
        fips = str(p.get(EMPOWER_FIPS_FIELD) or "").split(".")[0].zfill(5)
        if not fips.startswith("15"):
            fips = next((str(v).zfill(5) for v in p.values()
                         if str(v).isdigit() and len(str(v).zfill(5)) == 5
                         and str(v).zfill(5).startswith("150")), "")
        county = county_from_fips(fips) if fips else ""
        val = num(p.get(field))
        if county and val is not None:
            out[county] = out.get(county, 0) + val
    return out, field


# ---------------------------------------------------------------- build

def percentile_ranks(values: list) -> list:
    """0..1 rank among non-null values; None stays None."""
    pairs = sorted((v, i) for i, v in enumerate(values) if v is not None)
    ranks = [None] * len(values)
    n = len(pairs)
    for r, (_, i) in enumerate(pairs):
        ranks[i] = r / (n - 1) if n > 1 else 0.0
    return ranks


def build(svi, nri: dict | None, tsunami, extreme, empower, samples: int = 100,
          detail: dict | None = None, blocks: dict | None = None) -> dict:
    """nri = {hazard_key: FeatureCollection} from the NRI v1.20 per-hazard layers;
    detail = {tract_fips: row} from data/sources/cmist_detail_by_tract.csv;
    blocks = block_shares.load() (2020 block population and internal points): tsunami shares
    are population-weighted; without blocks they are the share of the area (grid points)."""
    detail = fetch_cmist_detail.load() if detail is None else detail
    nri = {k: v for k, v in (nri or {}).items() if v}
    # tract FIPS -> {hazard: properties}
    nri_by_fips: dict = {}
    for hz, layer in nri.items():
        for f in layer.get("features", []):
            p = f.get("properties") or {}
            nri_by_fips.setdefault(str(p.get("TRACTFIPS")), {})[hz] = p
    geom_layer = next(iter(nri.values()), None)
    nri_index = ZoneIndex(geom_layer, key="TRACTFIPS")
    t_index, x_index = ZoneIndex(tsunami), ZoneIndex(extreme)
    power, power_field = empower_by_county(empower)

    rows = []
    for f in (svi or {}).get("features", []):
        p = f.get("properties") or {}
        g = f.get("geometry")
        if not g:
            continue
        fips = str(p.get("FIPS", ""))
        county = county_from_fips(fips)
        pop = num(p.get("E_TOTPOP")) or 0
        r = {"tract_fips": fips, "county": county, "location": p.get("LOCATION", ""),
             "population": pop, "households": num(p.get("E_HH")),
             "svi_overall_pctl": num(p.get("RPL_THEMES"))}
        for theme, fields in CMIST_FIELDS.items():
            for name, src in fields.items():
                r[f"{theme}_{name}"] = num(p.get(src))
        for name, src in HOUSING_FIELDS.items():
            r[name] = num(p.get(src))
        d = detail.get(fips, {})
        for name, src in DETAIL_FIELDS.items():
            r[name] = num(d.get(src))

        # NRI: exact FIPS match, else tract containing our representative point
        by_hz = nri_by_fips.get(fips)
        match = "fips" if by_hz else ""
        if not by_hz and nri_index:
            hit = nri_index.find(*representative_point(g))
            if hit:
                by_hz = nri_by_fips.get(str((hit.get("properties") or {}).get("TRACTFIPS")))
                match = "spatial" if by_hz else ""
        by_hz = by_hz or {}
        for hz, (code, _) in NRI_HAZARD_LAYERS.items():
            hp = by_hz.get(hz, {})
            r[f"nri_{hz}_rating"] = hp.get(f"{code}_RISKR") or ""
            r[f"nri_{hz}_score"] = num(hp.get(f"{code}_RISKS"))
        r["nri_version"] = next((p.get("NRI_VER") for p in by_hz.values()
                                 if p.get("NRI_VER")), "")
        r["nri_match"] = match

        for key, idx in (("tsunami_zone_share", t_index), ("tsunami_extreme_share", x_index)):
            pw = block_shares.share(blocks, fips, idx.contains) if idx else None
            r[key] = round(pw if pw is not None else idx.share_inside(g, samples), 3)
        # Standard evacuation zone = planning number (used in warnings).
        # Extreme zone reported separately as the worst case.
        r["tsunami_exposed_pop_est"] = round(pop * r["tsunami_zone_share"])
        r["tsunami_extreme_exposed_pop_est"] = round(
            pop * max(r["tsunami_zone_share"], r["tsunami_extreme_share"]))
        rows.append((r, g))

    # emPOWER county totals -> tracts, proportional to 65+ population (Medicare proxy)
    age65_by_county = {}
    for r, _ in rows:
        age65_by_county[r["county"]] = age65_by_county.get(r["county"], 0) + (
            r["I_age_65_plus"] or 0)
    for r, _ in rows:
        total, base = power.get(r["county"]), age65_by_county.get(r["county"])
        r["M_power_dependent_est"] = (round(total * (r["I_age_65_plus"] or 0) / base, 1)
                                      if total is not None and base else None)

    # AFN index: mean percentile of per-capita CMIST rates (transparent, unweighted)
    def rate(r, key, denom="population"):
        d = r.get(denom) or 0
        v = r.get(key)
        return v / d if (v is not None and d) else None

    indicators = {
        "C": [rate(r, "C_limited_english") for r, _ in rows],
        "M": [rate(r, "M_power_dependent_est") if r["M_power_dependent_est"] is not None
              else rate(r, "M_uninsured") for r, _ in rows],
        "I": [rate(r, "I_disability") for r, _ in rows],
        "S": [rate(r, "S_age_17_under") for r, _ in rows],
        "T": [rate(r, "T_households_no_vehicle", "households") for r, _ in rows],
    }
    ranks = {k: percentile_ranks(v) for k, v in indicators.items()}
    for i, (r, _) in enumerate(rows):
        vals = [ranks[k][i] for k in "CMIST" if ranks[k][i] is not None]
        for k in "CMIST":
            r[f"pctl_{k}"] = None if ranks[k][i] is None else round(ranks[k][i], 3)
        r["afn_index"] = round(sum(vals) / len(vals), 3) if vals else None

    method = "population" if blocks else "area"
    features = [{"type": "Feature", "properties": r, "geometry": _round_geom(g)}
                for r, g in rows]
    meta = {
        "title": "Hawaiʻi AFN × hazard tract layer (CMIST)",
        "built_at": now_hst(),
        "privacy": "Aggregate census-tract data only. No individual records.",
        "method": {
            "cmist_proxies": CMIST_FIELDS,
            "power_dependent": "HHS emPOWER county total allocated to tracts by share "
                               "of county 65+ population (Medicare proxy). Estimate.",
            "empower_field_used": power_field,
            "share_method": method,
            "tsunami_share": (block_shares.METHOD[method] if method == "population" else
                              f"share of the area: {samples} grid points inside the zone; "
                              "exposed pop assumes even spread within the tract") + ". "
                             + (f"Blocks: {blocks['source']}. " if blocks else "")
                             + "tsunami_exposed_pop_est = standard evacuation zone; "
                             "tsunami_extreme_exposed_pop_est = extreme zone (worst case)",
            "nri_join": "NRI v1.20 per-hazard layers joined on tract FIPS (2020 tracts); spatial fallback",
            "afn_index": "mean statewide percentile of C, M, I, S, T per-capita rates",
        },
        "sources": [l["metadata"] for l in (svi, *nri.values(), tsunami, extreme, empower) if l]
                   + ([{"source": "ACS 2020-2024 5-year, tract tables B18102 (hearing), B18103 "
                                  "(vision), B18104 (cognitive), B09020 (age 65+ living alone)",
                        "source_url": fetch_cmist_detail.data_url("B18102"),
                        "fetched_at": "2026-10-27"}] if detail else []),
    }
    return {"type": "FeatureCollection", "features": features, "metadata": meta}


def _round_geom(g: dict, nd: int = 5) -> dict:
    def rnd(c):
        return [round(c[0], nd), round(c[1], nd)] if isinstance(c[0], (int, float)) \
            else [rnd(s) for s in c]
    return {"type": g["type"], "coordinates": rnd(g["coordinates"])}


def coverage(fc: dict) -> dict:
    out = {}
    for c in COUNTIES:
        feats = [f["properties"] for f in fc["features"] if f["properties"]["county"] == c]
        n = len(feats)
        out[c] = {
            "tracts": n,
            "with_cmist": sum(1 for p in feats if p["I_disability"] is not None),
            "with_nri": sum(1 for p in feats if p["nri_match"]),
            "with_power_estimate": sum(1 for p in feats
                                       if p["M_power_dependent_est"] is not None),
            "population": int(sum(p["population"] for p in feats)),
            "tsunami_exposed_pop_est": int(sum(p["tsunami_exposed_pop_est"] for p in feats)),
            "tsunami_extreme_exposed_pop_est": int(sum(p["tsunami_extreme_exposed_pop_est"]
                                                       for p in feats)),
        }
        out[c]["coverage_pct"] = round(100 * out[c]["with_cmist"] / n, 1) if n else 0.0
    return out


def need(key: str, what: str) -> dict:
    return load_geojson(RAW / f"{key}.geojson", what)


def main() -> int:
    try:   # every layer is required: a missing one would silently zero that hazard
        svi = need("svi", "CDC/ATSDR SVI Census areas")
        nri = {hz: need(f"nri_{hz}", f"FEMA NRI {hz}") for hz in NRI_HAZARD_LAYERS}
        layers = [need("tsunami_zone", "State tsunami evacuation zones"),
                  need("tsunami_extreme", "State extreme tsunami evacuation zones"),
                  need("empower_county", "HHS emPOWER county counts")]
    except MissingInput as e:
        print(e, file=sys.stderr)
        return 1
    fc = build(svi, nri, *layers, blocks=block_shares.load())
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "afn_tracts.geojson").write_text(json.dumps(fc), encoding="utf-8")
    props = [f["properties"] for f in fc["features"]]
    if props:
        with open(OUT / "afn_tracts.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(props[0]))
            w.writeheader()
            w.writerows(props)
    cov = coverage(fc)
    (OUT / "coverage.json").write_text(json.dumps(cov, indent=1), encoding="utf-8")

    print(f"Wrote {len(props)} tracts -> data/processed/afn_tracts.geojson / .csv\n")
    print(f"{'County':<10}{'Tracts':>7}{'CMIST%':>8}{'NRI':>6}{'Power':>7}"
          f"{'Population':>12}{'Tsunami pop':>13}{'Extreme':>10}")
    for c, v in cov.items():
        print(f"{c:<10}{v['tracts']:>7}{v['coverage_pct']:>8}{v['with_nri']:>6}"
              f"{v['with_power_estimate']:>7}{v['population']:>12,}"
              f"{v['tsunami_exposed_pop_est']:>13,}"
              f"{v['tsunami_extreme_exposed_pop_est']:>10,}")
    used = fc["metadata"]["method"]["empower_field_used"]
    print(f"\nemPOWER count field: {used or 'NOT FOUND – check data/raw/empower_county.geojson'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
