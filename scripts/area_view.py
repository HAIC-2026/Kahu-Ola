#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – per-area figures computed at build time (privacy).

No per-area count from 1 to 9 is shipped in any file the app serves. Everything that needs
small per-area values runs here, and the app receives finished display tokens:

  token   an integer of 10 or more (already rounded the way the app rounds), 0, or the marker
          "lt10" (a count above 0 that rounds below 10); areas with fewer than 100 residents
          ship their population only (no token at all)
  cell    a token, or [token, margin of error] when the source has an MOE and the count is shown

Shipped instead of raw values:
  bundle   per scenario: the Census areas in the risk area in display order, each with its map
           class and its "people with needs" token; the legend bounds as tokens; the community
           and priority tables as cells. The whole-area count arrays ("n", "m") are dropped.
  areas    data/areas.json (fetched when an area panel opens): the panel cells, risk-area
           scaling done here
  what-if  per area: people in shelter at the plan rate (only when 10 or more; else "lt10"),
           people without a car (same rule); per site and county: the plan-rate load of each
           site and the unassigned total (same rule). The app scales these linearly; a value
           shipped as "lt10" is never scaled (see app/whatif.js).

The arithmetic mirrors the app's earlier JavaScript exactly (JavaScript rounding, the same
order of addition), so the numbers people see do not change.
"""
from __future__ import annotations

import math

MIN = 10
SMALL_AREA = 100
LT10 = "lt10"
# community / priority table fields -> MOE field (None: no margin of error published)
LARGEST = {"at_risk_pop": "population", "low": None, "central": None, "high": None,
           "C_lep_at_risk": "lep", "M_power_dependent_at_risk": "power",
           "I_disability_at_risk": "disability", "I_age65_at_risk": "age65",
           "T_no_vehicle_persons_at_risk": "no_car", "C_hearing_at_risk": "hearing",
           "C_vision_at_risk": "vision", "I_cognitive_at_risk": "cognitive",
           "S_age65_alone_at_risk": "age65_alone"}
PRIORITY = {"at_risk_pop": "population", "power_dependent": "power", "disability": "disability",
            "limited_english": "lep", "no_vehicle": "no_car", "afn_need_sum": None}


def js_round(x: float) -> int:
    """JavaScript Math.round (halves go up)."""
    return math.floor(x + 0.5)


def small(pop) -> bool:
    return pop is not None and pop < SMALL_AREA


def token(v, pop=None):
    """What the app may show for a per-area count (None: nothing shipped)."""
    if small(pop) or v is None:
        return None
    if v == 0:
        return 0
    r = js_round(v)
    return LT10 if r < MIN else r


def cell(v, pop=None, moe=None):
    t = token(v, pop)
    if isinstance(t, int) and moe is not None:
        return [t, js_round(moe)]
    return t


def value_or_flag(v, pop=None):
    """A value the app scales (what-if): the plan-rate value itself when it shows as 10 or
    more, else the flag (0 stays 0; small areas ship nothing)."""
    t = token(v, pop)
    return v if isinstance(t, int) and t >= MIN else t


def quantiles(values: list, n: int = 5) -> list:
    """app.js quantiles(): positive values, ascending, n upper bounds."""
    v = sorted(x for x in values if x > 0)
    if not v:
        return []
    return [v[min(len(v) - 1, math.ceil(len(v) * (i + 1) / n) - 1)] for i in range(n)]


def map_view(county_tracts: list, sc_tracts: dict) -> dict:
    """{"in": [[fips, class or -1, people-with-needs token]] in the app's list order (most
    people with needs first, ties in bundle order), "bounds": legend bound tokens}."""
    afn = {f: v[2] for f, v in sc_tracts.items()}
    bounds = quantiles(list(afn.values()))
    risk = [t for t in county_tracts if t["f"] in sc_tracts]
    risk.sort(key=lambda t: -(afn.get(t["f"]) or 0))          # stable, as Array.sort
    rows = []
    for t in risk:
        a = afn[t["f"]]
        cls = next((i for i, b in enumerate(bounds) if a <= b), -1) if a > 0 else -1
        rows.append([t["f"], cls, token(a, t["n"][0])])
    return {"in": rows, "bounds": [token(b) for b in bounds]}


def panel(t: dict, v: list | None) -> list | None:
    """The area panel's cells. Whole area (v None): the 9 fields. In the risk area: [people
    in the risk area, likely shelter, [9 fields scaled by the share in the risk area]]."""
    n, m = t["n"], t.get("m") or [None] * len(t["n"])
    pop = n[0]
    if small(pop):
        return None
    if v is None:
        return [cell(n[i + 1], pop, m[i + 1]) for i in range(len(n) - 1)]
    share = v[0] / pop if pop else 0
    return [cell(v[0], pop, None if m[0] is None else m[0] * share), cell(v[1], pop),
            [cell(n[i + 1] * share, pop, None if m[i + 1] is None else m[i + 1] * share)
             for i in range(len(n) - 1)]]


def table_row(row: dict, t: dict | None, fields: dict, field_index: dict) -> dict:
    """A community / priority row with its counts as cells (areaCount in the earlier app)."""
    out = dict(row)
    pop = t["n"][0] if t else None
    for k, field in fields.items():
        if k not in row:
            continue
        moe = None
        if t and field and t.get("m") and pop:
            mm = t["m"][field_index[field]]
            if mm is not None:
                moe = mm * (row["at_risk_pop"] / pop)
        out[k] = cell(row[k], pop, moe)
        if k == "at_risk_pop":
            out["at_risk_plain"] = token(row[k], pop)          # the help panel shows no MOE
    return out


def whatif_view(county_tracts: list, sc_tracts: dict, sites: list, hazard: str) -> dict:
    """What-if inputs for one county x hazard (the earlier app's allocate() at the plan rate):
    per area [people in shelter, people without a car] as values or flags, each site's load
    and the unassigned total."""
    usable = {s["id"]: s for s in sites if s["lon"] is not None and (s["status"].get(hazard) or [""])[0] == "ok"}
    areas, load, unassigned = {}, {}, 0.0
    for t in county_tracts:
        if t["f"] not in sc_tracts:
            continue
        v = sc_tracts[t["f"]]
        pop = t["n"][0]
        nc = t["n"][5] * (v[0] / pop) if pop else 0
        areas[t["f"]] = [value_or_flag(v[1], pop), value_or_flag(nc, pop)]
        cands = sorted((r for r in t.get("a") or [] if r[0] in usable and r[1] is not None
                        and usable[r[0]]["island"] == t.get("i", "")), key=lambda r: (r[1], r[0]))
        if cands:
            load[cands[0][0]] = load.get(cands[0][0], 0) + v[1]
        else:
            unassigned += v[1]
    order = sorted(usable, key=lambda i: (-load.get(i, 0), i))   # by load; scaling keeps the order
    return {"areas": areas, "load": {str(k): value_or_flag(x) for k, x in load.items()},
            "order": order, "unassigned": value_or_flag(unassigned)}


def privatize(bundle: dict, detail_keys: list) -> dict:
    """Replace every shipped per-area count with tokens; return the panel file content."""
    fields = ["population", *bundle["area_fields"]]
    fidx = {k: i for i, k in enumerate(fields)}
    by_f = {t["f"]: t for t in bundle["tracts"]}
    panels = {"w": {}, "s": {}}
    for t in bundle["tracts"]:
        p = panel(t, None)
        if p is not None:
            panels["w"][t["f"]] = p
    sites = bundle["sites"]
    whatif = {}
    for key, sc in bundle["scenarios"].items():
        county, hazard = key.split("|")
        ct = [t for t in bundle["tracts"] if t["c"] == county]
        st = sc.pop("tracts")
        sc["map"] = map_view(ct, st)
        panels["s"][key] = {f: panel(by_f[f], v) for f, v in st.items() if f in by_f and panel(by_f[f], v) is not None}
        sc["largest"] = [table_row(r, by_f.get(r["tract_fips"]), LARGEST, fidx) for r in sc["largest"]]
        sc["priority_tracts"] = [table_row(r, by_f.get(r["tract_fips"]), PRIORITY, fidx) for r in sc["priority_tracts"]]
        whatif[key] = whatif_view(ct, st, sites, hazard)
    for t in bundle["tracts"]:                                  # population only; no count arrays
        t["pop"] = t["n"][0]
        t.pop("n")
        t.pop("m", None)
    return {"panels": panels, "whatif_areas": whatif}
