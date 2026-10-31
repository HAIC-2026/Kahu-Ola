#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – what-if engine: bundle data and a Python reference.

aggregates()  exact (unrounded) county x hazard sums from the plan's own model run
              (model_needs.run), shipped in the app bundle as "whatif"
compute()     the same arithmetic as app/whatif.js, for the tests (50 random input sets must
              match the JavaScript, and the plan defaults must reproduce the plan's numbers)
allocate()    nearest usable 2026 site on the same island by drive time, as in app/whatif.js

Deterministic and offline. Results are a what-if, not a forecast.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import COUNTIES  # noqa: E402
from model_needs import HAZARDS, load_json  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "config" / "planning_factors.json"
STRESS_CFG = ROOT / "config" / "stress_tests.json"
SUMS = {"demand": "shelter_demand", "children": "S_children_in_shelter",
        "power_in_shelter": "M_power_dependent_in_shelter", "households": "households_in_shelter",
        "lep_in_shelter": "C_lep_in_shelter", "disability_in_shelter": "I_disability_in_shelter",
        "at_risk": "at_risk_pop", "power_at_risk": "M_power_dependent_at_risk",
        "no_car_at_risk": "T_no_vehicle_persons_at_risk"}


def factors(cfg: dict, scfg: dict) -> dict:
    pp = {k: (v["value"] if isinstance(v, dict) else v) for k, v in cfg["per_person"].items()}
    staff = [[k, v["per_children"] if isinstance(v, dict) else v]
             for k, v in cfg["staff_per_shift"].items() if not k.startswith("_")]
    return {"floor_sqft_72h": pp["floor_sqft_72h"], "floor_sqft_2wk": pp["floor_sqft_2wk"],
            "water_gal_per_day": pp["water_gal_per_day"], "meals_per_day": pp["meals_per_day"],
            "persons_per_toilet_72h": pp["persons_per_toilet_72h"],
            "persons_per_toilet_2wk": pp["persons_per_toilet_short_term"],
            "outlets_per_person": pp["power_outlets_per_power_dependent_person"],
            "charges_per_day": scfg["charges_per_day"]["value"],
            "dog_share": cfg["pets"]["dog_owning_household_share"]["value"],
            "cat_share": cfg["pets"]["cat_owning_household_share"]["value"], "staff": staff}


def aggregates(inp_afn: dict, labels: dict, shelters: list, schools: list, cfg: dict,
               languages: dict) -> dict:
    """{"County|hazard": exact sums} from the plan's own model run (same order of addition)."""
    from model_needs import run
    tracts = [{**f["properties"], **{k: labels.get(f["properties"]["tract_fips"], {}).get(k, "")
                                     for k in ("tract_label", "label_main", "label_sub", "community", "island")}}
              for f in inp_afn["features"]]
    _sc, rows = run(tracts, shelters, schools, cfg)
    out = {}
    for h in HAZARDS:
        rate = cfg["shelter_seeking_rate"][h]["central"]
        for c in COUNTIES:
            mine = [r for r in rows if r["county"] == c and r["hazard"] == h]
            out[f"{c}|{h}"] = {**{k: sum(r[src] for r in mine) for k, src in SUMS.items()},
                               "rate": rate, "languages": languages.get(c, [])}
    return out


def roundhe(x: float) -> int:
    return int(round(x))          # Python rounds halves to even, as app/whatif.js roundHE


def compute(W: dict, key: str, inp: dict) -> dict:
    a, F = W["scenarios"][key], W["factors"]
    k = 1 if inp["rate"] == a["rate"] else inp["rate"] / a["rate"]
    D, CH, PD = a["demand"] * k, a["children"] * k, a["power_in_shelter"] * k
    HH, LEP, DIS = a["households"] * k, a["lep_in_shelter"] * k, a["disability_in_shelter"] * k
    short = inp["stay"] <= 3
    staff, total = {}, 0
    for role, n in F["staff"]:
        v = 0 if D <= 0 else ((math.ceil(CH / n) if CH else 0) if role == "children_area"
                              else max(1, math.ceil(D / n)))
        staff[role] = v
        total += v
    outlets = math.ceil(PD * F["outlets_per_person"])
    outlets_day = max(outlets, math.ceil(a["power_at_risk"] * F["charges_per_day"])) if inp["outage"] > 0 else outlets
    water, meals = math.ceil(D * F["water_gal_per_day"]), math.ceil(D * F["meals_per_day"])
    transport = roundhe(a["no_car_at_risk"])
    sup = inp.get("support")
    return {
        "people_in_shelter": roundhe(a["at_risk"] * inp["rate"]),
        "cots": math.ceil(D),
        "floor_sqft": math.ceil(D * (F["floor_sqft_72h"] if short else F["floor_sqft_2wk"])),
        "floor_basis": "72h" if short else "2wk",
        "water_per_day": water, "water_total": water * inp["stay"],
        "meals_per_day": meals, "meals_total": meals * inp["stay"],
        "toilets": math.ceil(D / (F["persons_per_toilet_72h"] if short else F["persons_per_toilet_2wk"])),
        "outlets_per_day": outlets_day, "charge_point_days": outlets_day * inp["outage"] if inp["outage"] > 0 else 0,
        "staff": staff, "staff_total": total,
        "interpreters": [[lang, roundhe(roundhe(LEP) * share)] for lang, share in a["languages"]],
        "support_people": roundhe(DIS) if sup is None else roundhe(D * sup),
        "support_share_plan": a["disability_in_shelter"] / a["demand"] if a["demand"] else 0,
        "transport_people": transport, "trips": math.ceil(transport / inp["trip"]),
        "dog_households": math.ceil(HH * F["dog_share"]), "cat_households": math.ceil(HH * F["cat_share"]),
        "children": roundhe(CH),
    }


def allocate(areas: list, sites: list, inp: dict, plan_rate: float) -> dict:
    k = 1 if inp["rate"] == plan_rate else inp["rate"] / plan_rate
    usable = {s["id"]: s for s in sites if s["usable"]}
    load, rows, unassigned = {}, [], 0.0
    for t in areas:
        people = t["people"] * k
        cands = sorted((r for r in t.get("a") or [] if r[0] in usable and r[1] is not None
                        and usable[r[0]]["island"] == t["island"]), key=lambda r: (r[1], r[0]))
        best = cands[0] if cands else None
        if best:
            load[best[0]] = load.get(best[0], 0) + people
        else:
            unassigned += people
        rows.append({"f": t["f"], "people": people, "site": best[0] if best else None,
                     "drive": best[1] if best else None})
    cap = inp.get("cap") or {}
    site_rows = []
    for sid in usable:
        l = load.get(sid, 0)
        c = cap.get(sid)
        site_rows.append({"id": sid, "load": l, "cap": c, "over": None if c is None else max(0, math.ceil(l) - c)})
    site_rows.sort(key=lambda s: (-s["load"], s["id"]))
    known = [s for s in site_rows if s["cap"] is not None]
    return {"areas": rows, "sites": site_rows, "unassigned": unassigned,
            "over_sites": sum(1 for s in known if s["over"] > 0),
            "shortfall": sum(s["over"] for s in known) if known else None}


def areas_for(bundle: dict, county: str, hazard: str) -> tuple[list, list]:
    """The allocation inputs the app builds from the bundle (same rules as app.js)."""
    sc = bundle["scenarios"][f"{county}|{hazard}"]
    areas = [{"f": t["f"], "island": t.get("i", ""), "people": sc["tracts"][t["f"]][1], "a": t.get("a", [])}
             for t in bundle["tracts"] if t["c"] == county and t["f"] in sc["tracts"]]
    sites = [{"id": s["id"], "island": s["island"],
              "usable": s["lon"] is not None and (s["status"].get(hazard) or [""])[0] == "ok"}
             for s in bundle["sites"] if s["county"] == county]
    return areas, sites


if __name__ == "__main__":
    W = json.loads((ROOT / "app" / "data" / "stress.json").read_text(encoding="utf-8"))["whatif"]
    for key in W["scenarios"]:
        c, h = key.split("|")
        r = compute(W, key, {"rate": W["scenarios"][key]["rate"], "stay": 3, "outage": 0,
                             "trip": W["defaults"]["people_per_trip"], "support": None, "cap": {}})
        print(key, r["people_in_shelter"], r["cots"], r["staff_total"])
