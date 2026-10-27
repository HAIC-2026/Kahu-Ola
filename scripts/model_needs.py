#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – Step 3: MODEL.

For every county x hazard planning scenario, estimate:
  * who is at risk (de-identified tract counts, CMIST)
  * how many people may need public shelter (low / central / high)
  * what that shelter population needs (space, water, meals, toilets, staff,
    power outlets, interpreters, accessible transport, pet space)
  * which known sites are usable for that hazard

Every factor lives in config/planning_factors.json with its source. The script is
deterministic and offline: no AI, no network. AI only explains results elsewhere.

Usage:  python3 scripts/model_needs.py        (after build_map.py and build_shelters.py)
Outputs:
  data/processed/needs_by_scenario.csv / .json   (county x hazard)
  data/processed/needs_by_tract.csv              (tract x hazard, for maps)
  data/processed/backtest.csv                    (model vs past events)
"""
from __future__ import annotations

import csv
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import COUNTIES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "config" / "planning_factors.json"
PROC = ROOT / "data" / "processed"
EVENTS = ROOT / "data" / "sources" / "past_events.csv"
HAZARDS = ("hurricane", "wildfire", "tsunami", "inland_flood", "coastal_flood")
HIGH = {"Very High", "Relatively High"}


def load_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def val(x) -> float:
    return x["value"] if isinstance(x, dict) else x


def nz(v) -> float:
    return float(v) if isinstance(v, (int, float)) else 0.0


# ---------------------------------------------------------------- footprint

def footprint_shares(tracts: list, hazard: str, cfg: dict) -> tuple[dict, str]:
    """Return ({tract_fips: share of population at risk}, rule_used)."""
    rule = cfg["footprint"][hazard]
    if rule["rule"] == "all":
        return {t["tract_fips"]: 1.0 for t in tracts}, "all tracts"
    if rule["rule"] == "tsunami_zone_share":
        return ({t["tract_fips"]: nz(t.get("tsunami_zone_share")) for t in tracts
                 if nz(t.get("tsunami_zone_share")) > 0}, "share inside tsunami zone")
    ratings = set(rule.get("ratings", HIGH))
    hit = {t["tract_fips"]: 1.0 for t in tracts
           if t.get(f"nri_{hazard}_rating") in ratings}
    if hit:
        return hit, f"NRI rating in {sorted(ratings)}"
    # Fallback: top share of tracts by NRI score statewide
    scored = sorted((nz(t.get(f"nri_{hazard}_score")), t["tract_fips"]) for t in tracts
                    if isinstance(t.get(f"nri_{hazard}_score"), (int, float)))
    k = math.ceil(len(scored) * cfg["footprint"]["fallback_top_share"])
    top = {fips: 1.0 for _, fips in scored[-k:]} if k else {}
    return top, f"fallback: top {int(cfg['footprint']['fallback_top_share'] * 100)}% by NRI score"


# ---------------------------------------------------------------- per tract

def tract_rows(tracts: list, hazard: str, shares: dict, rate: float) -> list:
    rows = []
    for t in tracts:
        share = shares.get(t["tract_fips"], 0.0)
        if share <= 0:
            continue
        pop = nz(t.get("population"))
        hh = nz(t.get("households"))
        at_risk = pop * share
        demand = at_risk * rate

        def per_cap(key):
            return nz(t.get(key)) / pop if pop else 0.0

        pph = pop / hh if hh else 0.0
        rows.append({
            "tract_fips": t["tract_fips"], "county": t["county"], "hazard": hazard,
            "share_at_risk": round(share, 3),
            "at_risk_pop": at_risk,
            "shelter_demand": demand,
            # outreach before the event: everyone at risk
            "C_lep_at_risk": at_risk * per_cap("C_limited_english"),
            "M_power_dependent_at_risk": at_risk * per_cap("M_power_dependent_est"),
            "I_disability_at_risk": at_risk * per_cap("I_disability"),
            "I_age65_at_risk": at_risk * per_cap("I_age_65_plus"),
            "T_no_vehicle_persons_at_risk": nz(t.get("T_households_no_vehicle")) * share * pph,
            "highrise_units_at_risk": nz(t.get("multi_unit_10plus")) * share,
            # inside public shelters
            "C_lep_in_shelter": demand * per_cap("C_limited_english"),
            "M_power_dependent_in_shelter": demand * per_cap("M_power_dependent_est"),
            "I_disability_in_shelter": demand * per_cap("I_disability"),
            "S_children_in_shelter": demand * per_cap("S_age_17_under"),
            "households_in_shelter": demand / pph if pph else 0.0,
        })
    return rows


# ---------------------------------------------------------------- resources

def resources(demand: float, children: float, power_dep: float, households: float,
              cfg: dict) -> dict:
    pp = cfg["per_person"]
    r = {
        "cots": math.ceil(demand),
        "floor_sqft_72h": math.ceil(demand * val(pp["floor_sqft_72h"])),
        "floor_sqft_2wk": math.ceil(demand * val(pp["floor_sqft_2wk"])),
        "water_gal_per_day": math.ceil(demand * val(pp["water_gal_per_day"])),
        "meals_per_day": math.ceil(demand * val(pp["meals_per_day"])),
        "toilets": math.ceil(demand / val(pp["persons_per_toilet_short_term"])),
        "power_outlets": math.ceil(power_dep * val(pp["power_outlets_per_power_dependent_person"])),
        "dog_households": math.ceil(households * val(cfg["pets"]["dog_owning_household_share"])),
        "cat_households": math.ceil(households * val(cfg["pets"]["cat_owning_household_share"])),
    }
    staff = 0
    if demand > 0:
        for role, n in cfg["staff_per_shift"].items():
            if role.startswith("_"):
                continue
            if isinstance(n, dict):
                staff += math.ceil(children / n["per_children"]) if children else 0
            else:
                staff += max(1, math.ceil(demand / n))
    r["staff_per_shift"] = staff
    return r


# ---------------------------------------------------------------- sites

def usable_sites(shelters: list, schools: list, county: str, hazard: str) -> dict:
    def ok(p):
        if hazard == "tsunami" and p.get("in_tsunami_zone"):
            return "exclude"
        if hazard in ("inland_flood", "coastal_flood") and \
                p.get(f"nri_{hazard}_rating") in HIGH:
            return "check"
        return "ok"

    s = [f["properties"] for f in shelters
         if f["properties"]["county"] == county and f.get("geometry")]
    c = [f["properties"] for f in schools if f["properties"]["county"] == county]
    s_status = [(p["name"], ok(p)) for p in s]
    c_ok = sum(1 for p in c if not (hazard == "tsunami" and p.get("hazard_excluded")))
    return {
        "known_sites_usable": sum(1 for _, st in s_status if st == "ok"),
        "known_sites_check_flood": sum(1 for _, st in s_status if st == "check"),
        "known_sites_excluded": [n for n, st in s_status if st == "exclude"],
        "candidate_schools_usable": c_ok,
    }


# ---------------------------------------------------------------- scenarios

def run(tracts: list, shelters: list, schools: list, cfg: dict):
    scenarios, tract_out = [], []
    for hz in HAZARDS:
        shares, rule = footprint_shares(tracts, hz, cfg)
        rates = cfg["shelter_seeking_rate"][hz]
        central = tract_rows(tracts, hz, shares, rates["central"])
        tract_out.extend(central)
        for county in COUNTIES:
            rows = [r for r in central if r["county"] == county]
            at_risk = sum(r["at_risk_pop"] for r in rows)
            agg = {k: sum(r[k] for r in rows) for k in (
                "shelter_demand", "C_lep_at_risk", "M_power_dependent_at_risk",
                "I_disability_at_risk", "I_age65_at_risk", "T_no_vehicle_persons_at_risk",
                "highrise_units_at_risk", "C_lep_in_shelter", "M_power_dependent_in_shelter",
                "I_disability_in_shelter", "S_children_in_shelter", "households_in_shelter")}
            sc = {
                "county": county, "hazard": hz, "footprint_rule": rule,
                "tracts_at_risk": len(rows),
                "at_risk_pop": round(at_risk),
                "shelter_demand_low": round(at_risk * rates["low"]),
                "shelter_demand_central": round(at_risk * rates["central"]),
                "shelter_demand_high": round(at_risk * rates["high"]),
                "rate_low": rates["low"], "rate_central": rates["central"],
                "rate_high": rates["high"],
            }
            sc.update({k: round(v) for k, v in agg.items() if k != "shelter_demand"})
            sc.update(resources(agg["shelter_demand"], agg["S_children_in_shelter"],
                                agg["M_power_dependent_in_shelter"],
                                agg["households_in_shelter"], cfg))
            sites = usable_sites(shelters, schools, county, hz)
            sc.update({k: v for k, v in sites.items() if k != "known_sites_excluded"})
            sc["known_sites_excluded"] = "; ".join(sites["known_sites_excluded"])
            scenarios.append(sc)
    return scenarios, tract_out


def backtest(cfg: dict, events_path: Path = EVENTS) -> list:
    if not events_path.exists():
        return []
    out = []
    with open(events_path, newline="", encoding="utf-8") as fh:
        for e in csv.DictReader(fh):
            r = cfg["shelter_seeking_rate"][e["hazard"]]
            pop, obs = float(e["affected_population"]), float(e["observed_sheltered"])
            row = {"event": e["event"], "date": e["date"], "hazard": e["hazard"],
                   "observed": int(obs)}
            for band in ("low", "central", "high"):
                est = pop * r[band]
                row[f"model_{band}"] = round(est)
                row[f"error_{band}_pct"] = round(100 * (est - obs) / obs, 1) if obs else None
            row["observed_within_band"] = row["model_low"] <= obs <= row["model_high"]
            row["calibration_event"] = "Calibration" in e.get("notes", "")
            out.append(row)
    return out


def write_csv(path: Path, rows: list) -> None:
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()})


def main() -> int:
    t0 = time.perf_counter()
    cfg = load_json(CONFIG)
    afn = load_json(PROC / "afn_tracts.geojson")
    if not cfg or not afn:
        print("Missing config/planning_factors.json or data/processed/afn_tracts.geojson",
              file=sys.stderr)
        return 1
    tracts = [f["properties"] for f in afn["features"]]
    shelters = (load_json(PROC / "shelters_2026.geojson") or {}).get("features", [])
    schools = (load_json(PROC / "candidates.geojson") or {}).get("features", [])

    scenarios, tract_out = run(tracts, shelters, schools, cfg)
    bt = backtest(cfg)
    secs = time.perf_counter() - t0

    write_csv(PROC / "needs_by_scenario.csv", scenarios)
    write_csv(PROC / "needs_by_tract.csv", tract_out)
    write_csv(PROC / "backtest.csv", bt)
    (PROC / "needs_by_scenario.json").write_text(json.dumps({
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "data_as_of": afn.get("metadata", {}).get("built_at"),
        "runtime_seconds": round(secs, 2),
        "privacy": "Aggregate tract estimates only. No individual records.",
        "planning_factors": cfg,
        "scenarios": scenarios,
        "backtest": bt,
    }, indent=1, ensure_ascii=False), encoding="utf-8")

    print(f"Modeled {len(scenarios)} county x hazard scenarios in {secs:.2f} s\n")
    print(f"{'Hazard':<14}{'County':<10}{'Tracts':>7}{'At risk':>10}"
          f"{'Shelter (low-central-high)':>28}{'Power-dep':>11}{'LEP':>8}{'Sites ok':>10}")
    for s in scenarios:
        band = f"{s['shelter_demand_low']:,}-{s['shelter_demand_central']:,}-" \
               f"{s['shelter_demand_high']:,}"
        print(f"{s['hazard']:<14}{s['county']:<10}{s['tracts_at_risk']:>7}"
              f"{s['at_risk_pop']:>10,}{band:>28}{s['M_power_dependent_at_risk']:>11,}"
              f"{s['C_lep_at_risk']:>8,}{s['known_sites_usable']:>10}")
    if bt:
        print("\nBacktest (model vs observed people in shelters):")
        for b in bt:
            tag = " [calibration event]" if b["calibration_event"] else ""
            print(f"  {b['event']} {b['date']}: observed {b['observed']:,}; model "
                  f"{b['model_low']:,} / {b['model_central']:,} / {b['model_high']:,} "
                  f"(central error {b['error_central_pct']}%){tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
