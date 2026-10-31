#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – stress tests: "what could break" (deterministic, build time).

The scenario list was proposed during planning (see PLAN.md §9); this script computes every
number from the plan's data files, deterministically and with no network. Each finding is labelled "stress test, not a forecast".

Group A (existing data, tests 1-23) and group B (ArcGIS road-closure routing, tests 24-25:
summarised from data/raw/arcgis/ into the committed data/sources/road_closures_summary.json).

Output: data/processed/stress_tests.json and .csv. Every finding has
  id, test, scenario, county, hazard, people_affected (+ unit), evidence (numbers),
  sources (plain words), assumptions ({text, value}), rank (stable: people affected, then id),
  areas / sites (for deep links), label.
A test without data says "needs county data" and carries no number.

Usage:  python3 scripts/build_stress_tests.py
"""
from __future__ import annotations

import csv
import itertools
import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import block_shares  # noqa: E402
import build_access as ba  # noqa: E402
import build_hub_layers as bhl  # noqa: E402
import build_state_layers as bsl  # noqa: E402
import fetch_arcgis as fa  # noqa: E402
from fetch_data import COUNTIES  # noqa: E402
from geo import ZoneIndex  # noqa: E402
from hawaii_time import now_hst  # noqa: E402
from model_needs import HAZARDS, site_status  # noqa: E402
from raw_inputs import MissingInput, load_geojson, load_json, rel, require_all_or_none  # noqa: E402

ROOT = fa.ROOT
PROC = ROOT / "data" / "processed"
SOURCES_DIR = ROOT / "data" / "sources"
OUT = PROC / "stress_tests.json"
OUT_CSV = PROC / "stress_tests.csv"
ROADS_OUT = SOURCES_DIR / "road_closures_summary.json"
CFG = ROOT / "config" / "stress_tests.json"
PF = ROOT / "config" / "planning_factors.json"
ROADS_CFG = ROOT / "config" / "stress_roads.json"
RAW_ROADS = ("od_closures_drive.json", "od_closures_walk.json", "od_flooded_drive.json")
HZ_LABEL = {"hurricane": "hurricane", "wildfire": "wildfire", "tsunami": "tsunami",
            "inland_flood": "inland flooding", "coastal_flood": "coastal flooding",
            "dam": "dam failure", "all": "all hazards"}
COUNTY_LABEL = {"Kauai": "Kauaʻi", "Honolulu": "Honolulu", "Maui": "Maui", "Hawaii": "Hawaiʻi"}
NOT_NO_SHELTER = ba.NOT_NO_SHELTER
SRC = {  # plain-words sources (no file names)
    "people": "CDC/ATSDR Social Vulnerability Index 2022 (ACS 2018–2022), HHS emPOWER, FEMA National Risk Index; 2020 Census blocks",
    "detail": "ACS 2020–2024 5-year Census-area tables (hearing, vision, cognitive difficulty; age 65 and older living alone)",
    "sites": "county announcements of sites opened in 2026; FEMA flood zones and tsunami evacuation zones (Hawaiʻi Statewide GIS)",
    "schools": "Hawaiʻi DOE public schools (Hawaiʻi Statewide GIS)",
    "drive": "Esri ArcGIS routing (drive-time matrix, normal traffic, build time)",
    "walk": "Esri ArcGIS routing (walking time, build time)",
    "barriers": "Esri ArcGIS routing with road closures (build time); highway centrelines: Hawaiʻi DOT HPMS and surveyed mile markers (Hawaiʻi Statewide GIS)",
    "flooded": "Hawaiʻi Sea Level Rise Viewer, potential flooded highways at 3.2 ft (PacIOOS, via Hawaiʻi Statewide GIS)",
    "factors": "Florida Division of Emergency Management, Sheltering Guidance Aid (2010)",
    "rates": "shelter-seeking rates in the plan (South Carolina EMD 2026 Annex G; Maui 2023 observed; team assumptions)",
    "tsunami": "State tsunami evacuation zones and extreme tsunami evacuation zones (Hawaiʻi Statewide GIS)",
    "safe_zones": "Tsunami Safe Zones (Hawaiʻi Statewide GIS; Maui County zones from 2013)",
    "dams": "State of Hawaiʻi dam evacuation zones (Hawaiʻi Statewide GIS)",
    "sirens": "Hawaiʻi Emergency Management Agency public siren map; rated range 3,400 ft",
    "fire": "State Fire Risk Areas (DLNR Division of Forestry and Wildlife, via Hawaiʻi Statewide GIS); FEMA National Risk Index wildfire scores",
    "languages": "ACS PUMS 2019–2023 5-year (limited-English speakers by language)",
    "messages": "the plan's multilingual message library",
    "pets": "AVMA pet ownership (2020 data); pet policies announced with the 2026 site openings",
    "pit": "2026 Point-in-Time counts (Bridging the Gap; Partners In Care via the City and County of Honolulu)",
    "visitors": "DBEDT State of Hawaiʻi Data Book 2025, Table 7.06 (average daily visitor census, 2025)",
    "childcare": "Ready Keiki Locator, centre-based childcare and pre-K sites (Office of the Lieutenant Governor)",
    "care": "CMS Provider Data Catalog (dialysis facilities, nursing homes, hospitals)",
}


# ---------------------------------------------------------------- inputs

class Inputs:
    def __init__(self):
        self.cfg = load_json(CFG, "stress test settings")
        self.pf = load_json(PF, "planning factors")
        self.afn = load_geojson(fa.AFN, "Census areas (build_map.py)")
        self.tracts = {f["properties"]["tract_fips"]: f["properties"] for f in self.afn["features"]}
        self.labels = {}
        with open(SOURCES_DIR / "tract_communities.csv", newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                self.labels[r["tract_fips"]] = r.get("tract_label") or r["tract_fips"]
        self.needs = {}                                     # (fips, hazard) -> row
        with open(fa.NEEDS_BY_TRACT, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                self.needs[(r["tract_fips"], r["hazard"])] = {
                    k: (float(v) if k not in ("tract_fips", "tract_label", "label_main", "label_sub",
                                              "community", "island", "county", "hazard") else v)
                    for k, v in r.items()}
        self.scen = {(s["county"], s["hazard"]): s for s in
                     load_json(PROC / "needs_by_scenario.json", "needs by scenario")["scenarios"]}
        self.match = {(s["county"], s["hazard"]): s for s in
                      load_json(PROC / "match_plan.json", "match plan")["scenarios"]}
        self.access = load_json(SOURCES_DIR / "arcgis_summary.json", "ArcGIS travel-time summary")
        self.state = load_json(SOURCES_DIR / "state_layers_summary.json", "State layer summary")
        self.hub = load_json(SOURCES_DIR / "hub_layers_summary.json", "State Hub layer summary")
        self.island = {}
        self.area_county = {}
        with open(fa.ISLANDS, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["kind"] == "area":
                    self.island[r["id"]] = r["island"]
                    self.area_county[r["id"]] = r["county"]
                else:
                    self.island["site:" + r["id"]] = r["island"]
        self.sites = {}
        for f in load_json(fa.SHELTERS, "2026 shelter sites")["features"]:
            p = f["properties"]
            if not f.get("geometry"):
                continue
            key = f"{p['name']}|{p['county']}"
            self.sites[key] = {**p, "key": key, "lon": f["geometry"]["coordinates"][0],
                               "lat": f["geometry"]["coordinates"][1],
                               "island": self.island.get("site:" + key, "")}
        self.foot = ba.footprints()
        self.usable = {k: [h for h in HAZARDS if site_status(s, h, self.foot.get((s["county"], h), set()))[0] == "ok"]
                       for k, s in self.sites.items()}
        self.rates = {h: self.pf["shelter_seeking_rate"][h] for h in HAZARDS}
        self.limit = self.cfg["drive_limit_min"]["value"]
        self.per_site = self.cfg["people_per_site"]["value"]

    def label(self, fips: str) -> str:
        return self.labels.get(fips, fips)

    def at_risk(self, fips: str, h: str) -> float:
        r = self.needs.get((fips, h))
        return r["at_risk_pop"] if r else 0.0

    def in_foot(self, h: str, county: str | None = None) -> list:
        return sorted(f for (f, hz) in self.needs if hz == h and (
            county is None or self.needs[(f, hz)]["county"] == county))

    def best_site(self, fips: str, h: str, removed=frozenset()) -> float | None:
        """Shortest drive (min) from the area to a 2026 activated site usable for h on the
        same island, without the removed sites."""
        a = self.access["areas"].get(fips)
        if not a:
            return None
        return min((v[0] for k, v in a["sites"].items()
                    if v[0] is not None and h in self.usable.get(k, []) and k not in removed),
                   default=None)


def school_times() -> dict:
    """{area: {school id: minutes}} from the raw DOE-school matrix (fetch_arcgis.py)."""
    return {a: {k: v[0] for k, v in row.items()} for a, row in ba.parse_od(fa.RAW / "od_schools.json").items()}


def outside(v) -> bool:
    return v is None or v > 15


def ceil(x: float) -> int:
    return int(math.ceil(round(x, 9)))


def finding(test: int, code: str, scenario: str, county: str, hazard: str, people,
            evidence: dict, sources: list, assumptions: list | None = None, unit: str = "people",
            areas: list | None = None, sites: list | None = None, title: str = "") -> dict:
    num = f"{test:02d}" if isinstance(test, int) else test
    return {"id": f"T{num}-{code}", "test": str(test), "title": title, "scenario": scenario,
            "county": county, "hazard": hazard,
            "people_affected": None if people is None else int(round(people)), "unit": unit,
            "measure": MEASURE.get(str(test), ""),
            "evidence": evidence, "sources": [SRC[s] for s in sources],
            "assumptions": assumptions or [], "areas": areas or [], "sites": sites or [],
            "label": "stress test, not a forecast"}


def assume(text: str, value) -> dict:
    return {"text": text, "value": value, "kind": "team assumption"}


def top_areas(rows: dict, n: int = 5) -> list:
    return [f for f, _v in sorted(rows.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


# ---------------------------------------------------------------- tests 1-3: site loss

TITLES = {
    1: "One site lost", 2: "Two sites lost", 3: "FEMA zone D schools not usable",
    4: "Tsunami and coastal flooding together", 5: "Hurricane and inland flooding together",
    6: "Wildfire and power loss together", 7: "Dam failure and inland flooding together",
    8: "Extreme tsunami zone (worst case)", 9: "Several counties at once",
    10: "Shelter-seeking rate higher than planned", 11: "Longer stays",
    12: "Long power outage", 13: "Kūpuna living alone, no car, far from a site",
    14: "Hearing difficulty and outside siren range (tsunami, at night)",
    15: "Power-dependent and far from a site", 16: "Languages with no translated messages",
    17: "Pets and pet-friendly sites", 18: "People experiencing homelessness",
    19: "Childcare centres in hazard zones (daytime event)", 20: "Visitors in tsunami zones",
    21: "Stranded visitors", 22: "Care facilities in hazard zones",
    "23a": "Walking to a tsunami safe zone without a car", 24: "Road closures (driving)",
    25: "Road closures (walking)", "23b": "State Fire Risk Areas vs the plan's wildfire areas",
}


MEASURE = {
    "1": "people in the risk area pushed outside a 15-minute drive to a usable 2026 site",
    "2": "people in the risk area pushed outside a 15-minute drive to a usable 2026 site",
    "3": "people in the risk area pushed outside a 15-minute drive to a usable site or candidate school",
    "4": "people who may need a public shelter (likely)", "5": "people who may need a public shelter (likely)",
    "6": "people who may need a public shelter (likely)", "7": "people who may need a public shelter (likely)",
    "8": "people in the extreme tsunami evacuation zone",
    "9": "people who may need a public shelter (likely), counties together",
    "10": "people who may need a shelter at the rate where usable sites run out",
    "11": "people who may need a public shelter (likely)", "12": "power-dependent residents in the risk area",
    "13": "kūpuna living alone without a car, outside a 15-minute drive (upper bound)",
    "14": "people with hearing difficulty outside rated siren range (upper bound)",
    "15": "power-dependent residents outside a 15-minute drive",
    "16": "people who speak English less than very well", "17": "households with a dog or a cat in shelter",
    "18": "people added by the 2026 Point-in-Time count", "19": "childcare centres in the zone",
    "20": "visitors on an average day (island level)", "21": "visitors on an average day (island level)",
    "22": "care facilities in the zone",
    "23a": "people without a car more than 15 minutes' walk from a tsunami safe zone",
    "23b": "people in areas rated high only by the State Fire Risk layer",
    "24": "people in areas with a longer drive, fewer known sites within 45 minutes, or cut off",
    "25": "people in areas with a longer walk to a 2026 site or cut off on foot",
}


def site_loss(inp: Inputs) -> list:
    out = []
    by_isl = {}
    for k, s in inp.sites.items():
        by_isl.setdefault(s["island"], []).append(k)
    for h in HAZARDS:
        foot = inp.in_foot(h)
        base = {f: inp.best_site(f, h) for f in foot}
        for isl, keys in sorted(by_isl.items()):
            usable = sorted(k for k in keys if h in inp.usable[k])
            areas = [f for f in foot if inp.island.get(f) == isl]
            singles = {}
            for k in usable:
                hit = {f: inp.at_risk(f, h) for f in areas
                       if not outside(base[f]) and outside(inp.best_site(f, h, frozenset([k])))}
                singles[k] = hit
                s = inp.sites[k]
                out.append(finding(1, f"{h}-{fa.plain(k).lower().replace(' ', '_').replace('|', '-')}",
                                   f"Lose {s['name']} ({HZ_LABEL[h]})", s["county"], h, sum(hit.values()),
                                   {"site": s["name"], "island": isl, "areas_pushed_outside": len(hit),
                                    "shelter_demand_likely": round(sum(inp.needs[(f, h)]["shelter_demand"] for f in hit), 1),
                                    "drive_limit_min": inp.limit, "note": NOT_NO_SHELTER},
                                   ["people", "sites", "drive"], areas=top_areas(hit), sites=[k],
                                   title=TITLES[1]))
            for a, b in itertools.combinations(usable, 2):
                gone = frozenset([a, b])
                hit = {f: inp.at_risk(f, h) for f in areas
                       if not outside(base[f]) and outside(inp.best_site(f, h, gone))}
                none_left = {f: inp.at_risk(f, h) for f in areas
                             if base[f] is not None and inp.best_site(f, h, gone) is None}
                extra = sum(hit.values()) - max(sum(singles[a].values()), sum(singles[b].values()))
                sa, sb = inp.sites[a], inp.sites[b]
                out.append(finding(2, f"{h}-{fa.plain(a + b).lower().replace(' ', '_').replace('|', '-')}",
                                   f"Lose {sa['name']} and {sb['name']} ({HZ_LABEL[h]})", sa["county"], h,
                                   sum(hit.values()),
                                   {"sites": [sa["name"], sb["name"]], "island": isl,
                                    "areas_pushed_outside": len(hit),
                                    "more_than_worst_single_loss": round(extra),
                                    "areas_left_with_no_usable_site_on_island": len(none_left),
                                    "people_left_with_no_usable_site_on_island": round(sum(none_left.values())),
                                    "drive_limit_min": inp.limit, "note": NOT_NO_SHELTER},
                                   ["people", "sites", "drive"], areas=top_areas(hit), sites=[a, b],
                                   title=TITLES[2]))
    return out


def zone_d_schools(inp: Inputs, st: dict, island_of) -> list:
    schools = {s["id"]: s for s in fa.candidate_schools(island_of)}
    props = {f["properties"]["id"]: f["properties"] for f in
             load_json(fa.CANDIDATES, "DOE candidate schools")["features"]}
    zone_d = {k for k, p in props.items() if (p.get("fld_zone") or "").strip().upper() == "D"}
    out = []
    for h in HAZARDS:
        for c in COUNTIES:
            hit, base_n = {}, 0
            for f in inp.in_foot(h, c):
                act = inp.best_site(f, h)
                sch = [m for k, m in st.get(f, {}).items() if m is not None and h in schools.get(k, {}).get("usable", [])]
                sch_nod = [m for k, m in st.get(f, {}).items() if m is not None and k not in zone_d
                           and h in schools.get(k, {}).get("usable", [])]
                before = min([x for x in [act] + sch if x is not None], default=None)
                after = min([x for x in [act] + sch_nod if x is not None], default=None)
                if not outside(before) and outside(after):
                    hit[f] = inp.at_risk(f, h)
                base_n += 1
            n_d = sum(1 for k in zone_d if props[k]["county"] == c)
            already = h in ("inland_flood", "coastal_flood")
            out.append(finding(3, f"{h}-{c.lower()}", f"Treat DOE schools in FEMA zone D as not usable ({HZ_LABEL[h]})",
                               c, h, 0 if already else sum(hit.values()),
                               {"zone_d_schools_in_county": n_d, "areas_pushed_outside": 0 if already else len(hit),
                                "already_not_usable_in_plan": already, "zone_d_sites_2026": 0,
                                "drive_limit_min": inp.limit,
                                "note": ("For flooding the plan already treats zone D (flood risk not mapped) as not usable."
                                         if already else "No 2026 activated site is in zone D; this tests the DOE candidate schools.")},
                               ["schools", "sites", "drive"], areas=top_areas(hit), title=TITLES[3]))
    return out


# ---------------------------------------------------------------- tests 4-8: combined hazards

def union(inp: Inputs, parts: list, zones: dict, blocks) -> dict:
    """Per area: (people in the union of footprints, likely demand). Block-weighted: a person
    is counted once, at the highest rate of the footprints that cover their block."""
    rate = {h: inp.rates["inland_flood" if h == "dam" else h]["central"] for h in parts}
    tract_level = {h: {f for f in inp.tracts if (f, h) in inp.needs} for h in parts if h not in zones}
    out = {}
    for f, p in inp.tracts.items():
        pop = p.get("population") or 0
        if not pop:
            continue
        cover_all = [h for h in tract_level if f in tract_level[h]]
        rows = (blocks or {}).get("blocks", {}).get(f)
        if rows:
            tot = cov = w = 0.0
            for x, y, bp in rows:
                hs = cover_all + [h for h, z in zones.items() if z.contains(x, y)]
                tot += bp
                if hs:
                    cov += bp
                    w += bp * max(rate[h] for h in hs)
            share, wr = (cov / tot, w / tot) if tot else (0.0, 0.0)
        else:                                   # no blocks: the larger share, its rate (labelled)
            shares = [(1.0, rate[h]) for h in cover_all] + [
                (inp.needs[(f, h)]["share_at_risk"], rate[h]) for h in zones if (f, h) in inp.needs]
            share, wr = max(shares, default=(0.0, 0.0))
            wr *= share
        if share > 0:
            out[f] = (pop * share, pop * wr, share)
    return out


def combined(inp: Inputs, blocks) -> list:
    tsu = ZoneIndex(load_geojson(ba.TSUNAMI, "State tsunami evacuation zones"))
    dams = ZoneIndex(load_geojson(ROOT / "data" / "raw" / "state_layers" / "dams.geojson", "State dam evacuation zones"))
    dam_sites = set(inp.state["site_dam_zones"])
    combos = [(4, ["tsunami", "coastal_flood"], {"tsunami": tsu}),
              (5, ["hurricane", "inland_flood"], {}),
              (6, ["wildfire"], {}),
              (7, ["dam", "inland_flood"], {"dam": dams})]
    out = []
    for test, parts, zones in combos:
        u = union(inp, parts, zones, blocks)
        for c in COUNTIES:
            rows = {f: v for f, v in u.items() if inp.tracts[f]["county"] == c}
            people = sum(v[0] for v in rows.values())
            demand = sum(v[1] for v in rows.values())
            sep_people = sum(inp.at_risk(f, h) for h in parts if h != "dam" for f in inp.in_foot(h, c))
            if "dam" in parts:
                sep_people += sum(a["dam_people"] for f, a in inp.state["areas"].items() if a["county"] == c)
            usable = [k for k, s in inp.sites.items() if s["county"] == c
                      and all((h == "dam" and k not in dam_sites) or (h != "dam" and h in inp.usable[k]) for h in parts)]
            need = ceil(demand / inp.per_site)
            ev = {"people_in_union": round(people), "if_counted_separately": round(sep_people),
                  "shelter_demand_likely": round(demand),
                  "sites_usable_in_every_hazard": len(usable),
                  "sites_needed_at_250": need, "site_gap": max(0, need - len(usable)),
                  "areas": len(rows)}
            asm = [assume("Sites needed at a given number of people per site (capacity unknown)", inp.per_site),
                   assume("A person in two footprints is counted once, at the higher rate", "highest rate")]
            src = ["people", "sites", "rates"]
            hz = "+".join(parts)
            if test == 6:
                pd = sum(inp.needs[(f, "wildfire")]["M_power_dependent_at_risk"] for f in inp.in_foot("wildfire", c))
                ev.update(power_dependent_in_risk_area=round(pd),
                          outlets_plan_in_shelter=inp.scen[(c, "wildfire")]["power_outlets"],
                          outlets_per_day_if_power_out=ceil(pd * inp.cfg["charges_per_day"]["value"]),
                          power_loss_area="needs county data (utility outage areas)",
                          site_backup_power="needs county data")
                asm.append(assume("Power is out across the wildfire risk area; every power-dependent resident needs one charge a day", inp.cfg["charges_per_day"]["value"]))
                hz = "wildfire+power"
            if test == 7:
                asm.append(assume("Dam failure uses the inland flooding shelter-seeking rate", f"{inp.rates['inland_flood']['central']:.0%}"))
                src.append("dams")
            if test == 4:
                src.append("tsunami")
            out.append(finding(test, f"{c.lower()}", f"{TITLES[test]} – {COUNTY_LABEL[c]}", c, hz, demand, ev, src,
                               asm, areas=top_areas({f: v[0] for f, v in rows.items()}), sites=usable,
                               title=TITLES[test]))
    # 8 extreme tsunami zone
    ext = ZoneIndex(load_geojson(ROOT / "data" / "raw" / "tsunami_extreme.geojson", "extreme tsunami evacuation zones"))
    for c in COUNTIES:
        sc = inp.scen[(c, "tsunami")]
        pop = sc.get("at_risk_pop_extreme_zone") or 0
        r = inp.rates["tsunami"]
        in_ext = [k for k, s in inp.sites.items() if s["county"] == c and ext.contains(s["lon"], s["lat"])]
        usable = [k for k, s in inp.sites.items() if s["county"] == c and "tsunami" in inp.usable[k] and k not in in_ext]
        dem = {b: round(pop * r[b]) for b in ("low", "central", "high")}
        out.append(finding(8, c.lower(), f"{TITLES[8]} – {COUNTY_LABEL[c]}", c, "tsunami", pop,
                           {"people_in_extreme_zone": pop, "people_in_standard_zone": sc["at_risk_pop"],
                            "shelter_demand_low": dem["low"], "shelter_demand_likely": dem["central"],
                            "shelter_demand_high": dem["high"],
                            "sites_inside_extreme_zone": len(in_ext),
                            "sites_usable_outside_both_zones": len(usable),
                            "sites_needed_at_250": ceil(dem["central"] / inp.per_site)},
                           ["people", "tsunami", "sites", "rates"],
                           [assume("Sites needed at a given number of people per site (capacity unknown)", inp.per_site)],
                           sites=in_ext, title=TITLES[8]))
    return out


# ---------------------------------------------------------------- tests 9-12: scale

def need_qty(m: dict, name: str) -> int:
    return sum(n["quantity"] for n in m["needs"] if n["need"] == name)


def several_counties(inp: Inputs) -> list:
    from build_playbooks import lang_label
    out = []
    groups = [list(p) for p in itertools.combinations(COUNTIES, 2)] + [list(COUNTIES)]
    for h in HAZARDS:
        for g in groups:
            ms = [inp.match[(c, h)] for c in g]
            interp = {}
            for m in ms:
                for n in m["needs"]:
                    if n.get("language"):
                        lab = lang_label(n["language"])
                        interp[lab] = interp.get(lab, 0) + n["quantity"]
            people = sum(m["shelter_demand_central"] for m in ms)
            code = "all" if len(g) == 4 else "-".join(c.lower() for c in g)
            name = "All four counties" if len(g) == 4 else " and ".join(COUNTY_LABEL[c] for c in g)
            out.append(finding(9, f"{h}-{code}", f"{name} at once ({HZ_LABEL[h]})", "Statewide", h, people,
                               {"counties": g, "people_in_shelter_likely": people,
                                "cots": sum(need_qty(m, "Cots / sleeping space") for m in ms),
                                "meals_per_day": sum(need_qty(m, "Meals") for m in ms),
                                "water_gal_per_day": sum(need_qty(m, "Water") for m in ms),
                                "staff_per_shift": sum(need_qty(m, "Shelter staff") for m in ms),
                                "interpreters_people_with_limited_english": dict(sorted(interp.items(), key=lambda kv: -kv[1]))},
                               ["people", "factors", "languages", "rates"], title=TITLES[9]))
    return out


def rate_sweep(inp: Inputs) -> list:
    sw = inp.cfg["rate_sweep"]
    steps = [round(sw["from"] + i * sw["step"], 2) for i in range(int(round((sw["to"] - sw["from"]) / sw["step"])) + 1)]
    out = []
    for c in COUNTIES:
        n_sites = sum(1 for s in inp.sites.values() if s["county"] == c)
        for h in HAZARDS:
            sc = inp.scen[(c, h)]
            usable = sc["known_sites_usable"]
            need = {r: ceil(sc["at_risk_pop"] * r / inp.per_site) for r in steps}
            hit = next((r for r in steps if need[r] > usable), None)
            out.append(finding(10, f"{h}-{c.lower()}", f"Rate at which demand needs more sites than are usable – {COUNTY_LABEL[c]} ({HZ_LABEL[h]})",
                               c, h, sc["at_risk_pop"] * hit if hit else 0,
                               {"rate_when_sites_run_out": hit, "rate_likely_in_plan": sc["rate_central"],
                                "usable_2026_sites": usable, "known_2026_sites": n_sites,
                                "people_in_risk_area": sc["at_risk_pop"],
                                "sites_needed_by_rate": {f"{int(round(r * 100))}%": need[r] for r in steps},
                                "not_reached_by": None if hit else f"{int(round(steps[-1] * 100))}%"},
                               ["people", "sites", "rates"],
                               [assume("Sites needed at a given number of people per site (capacity unknown)", inp.per_site),
                                assume("Rates tested", f"{int(steps[0] * 100)}–{int(steps[-1] * 100)}% in 1-point steps")],
                               title=TITLES[10]))
    return out


def stays(inp: Inputs) -> list:
    pp = inp.pf["per_person"]
    v = lambda k: pp[k]["value"]  # noqa: E731
    out = []
    for c in COUNTIES:
        for h in HAZARDS:
            sc = inp.scen[(c, h)]
            d = sc["shelter_demand_central"]
            rows = {}
            for days in inp.cfg["stay_days"]["value"]:
                short = days <= 3
                rows[f"{days} days"] = {
                    "water_gal": sc["water_gal_per_day"] * days, "meals": sc["meals_per_day"] * days,
                    "toilets": sc["toilets_72h"] if short else sc["toilets_2wk"],
                    "floor_sqft": sc["floor_sqft_72h"] if short else sc["floor_sqft_2wk"]}
            out.append(finding(11, f"{h}-{c.lower()}", f"Stays of 3 to 30 days – {COUNTY_LABEL[c]} ({HZ_LABEL[h]})",
                               c, h, d, {"people_in_shelter_likely": d, "by_stay": rows,
                                         "per_day": {"water_gal": v("water_gal_per_day"), "meals": v("meals_per_day")}},
                               ["factors", "people", "rates"],
                               [assume("Floor space and toilets use the 2-week factors for stays over 3 days, also past 14 days", "40 sq ft; 1 toilet per 20")],
                               title=TITLES[11]))
    return out


def outages(inp: Inputs) -> list:
    k = inp.cfg["charges_per_day"]["value"]
    out = []
    for c in COUNTIES:
        for h in HAZARDS:
            sc = inp.scen[(c, h)]
            pd = sc["M_power_dependent_at_risk"]
            out.append(finding(12, f"{h}-{c.lower()}", f"Power out 1 to 14 days – {COUNTY_LABEL[c]} ({HZ_LABEL[h]})", c, h, pd,
                               {"power_dependent_in_risk_area": pd, "outlets_plan_in_shelter": sc["power_outlets"],
                                "outlets_per_day_while_out": ceil(pd * k),
                                "charge_point_days": {f"{d} {'day' if d == 1 else 'days'}": ceil(pd * k) * d for d in inp.cfg["outage_days"]["value"]}},
                               ["people"], [assume("Charges per power-dependent resident per day while the power is out (upper bound)", k)],
                               title=TITLES[12]))
    return out


# ---------------------------------------------------------------- tests 13-15: who is far

def far(inp: Inputs) -> list:
    out = []
    for h in HAZARDS:
        for c in COUNTIES:
            o = [f for f in inp.in_foot(h, c) if outside(inp.best_site(f, h))]
            k13 = {f: min(inp.needs[(f, h)]["S_age65_alone_at_risk"], inp.needs[(f, h)]["T_no_vehicle_persons_at_risk"]) for f in o}
            k15 = {f: inp.needs[(f, h)]["M_power_dependent_at_risk"] for f in o}
            common = {"areas_outside": len(o), "drive_limit_min": inp.limit, "note": NOT_NO_SHELTER}
            out.append(finding(13, f"{h}-{c.lower()}", f"{TITLES[13]} – {COUNTY_LABEL[c]} ({HZ_LABEL[h]})", c, h, sum(k13.values()),
                               {**common, "age65_alone_in_those_areas": round(sum(inp.needs[(f, h)]["S_age65_alone_at_risk"] for f in o)),
                                "no_car_in_those_areas": round(sum(inp.needs[(f, h)]["T_no_vehicle_persons_at_risk"] for f in o)),
                                "upper_bound": True},
                               ["detail", "people", "sites", "drive"],
                               [assume("Upper bound: the smaller of the two counts in each area (the overlap is not published)", "min of the two")],
                               areas=top_areas(k13), title=TITLES[13]))
            out.append(finding(15, f"{h}-{c.lower()}", f"{TITLES[15]} – {COUNTY_LABEL[c]} ({HZ_LABEL[h]})", c, h, sum(k15.values()),
                               {**common, "power_dependent_in_those_areas": round(sum(k15.values()))},
                               ["people", "sites", "drive"], areas=top_areas(k15), title=TITLES[15]))
    for c in COUNTIES:
        rows = {}
        for f in inp.in_foot("tsunami", c):
            n = inp.needs[(f, "tsunami")]
            a = inp.state["areas"].get(f)
            if not a:
                continue
            out_people = n["at_risk_pop"] * (1 - a["siren_share"])
            rows[f] = min(n["C_hearing_at_risk"], out_people)
        out.append(finding(14, c.lower(), f"{TITLES[14]} – {COUNTY_LABEL[c]}", c, "tsunami", sum(rows.values()),
                           {"hearing_difficulty_in_tsunami_zone": round(sum(inp.needs[(f, 'tsunami')]['C_hearing_at_risk'] for f in inp.in_foot('tsunami', c))),
                            "areas": len([f for f, v in rows.items() if v > 0]), "upper_bound": True,
                            "note": "At night most people are indoors; sirens are an outdoor warning. Plan WEA, radio, door-to-door and trusted messengers."},
                           ["detail", "sirens", "tsunami"],
                           [assume("Upper bound: the smaller of 'hearing difficulty' and 'people outside the rated siren range' in each area", "min of the two"),
                            assume("People outside rated range = people in the tsunami zone x share of the area's people outside 3,400 ft of a siren", "independence")],
                           areas=top_areas(rows), title=TITLES[14]))
    return out


# ---------------------------------------------------------------- tests 16-22: groups

def languages(inp: Inputs) -> list:
    from build_playbooks import CV_LIMIT, Z90
    msgs = {}
    for lang in ("Chuukese", "Marshallese"):
        with open(SOURCES_DIR / "messages" / f"{lang.lower()}.csv", newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        msgs[lang] = (sum(1 for r in rows if (r.get("text") or "").strip()), len(rows))
    out = []
    with open(SOURCES_DIR / "languages_by_county.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["language"] not in msgs:
                continue
            done, total = msgs[r["language"]]
            if r["suppressed"] == "True":
                ev = {"area": r["area"], "reliable": False, "people": None,
                      "note": "too few to estimate (ACS suppression): needs county data"}
                people, reliable = None, False
            else:
                n, moe = int(r["speak_english_less_than_very_well"]), int(r["moe_90"])
                cv = moe / Z90 / n if n else 1
                reliable = cv <= CV_LIMIT
                people = n if reliable else None
                ev = {"area": r["area"], "reliable": reliable, "people_limited_english": n, "moe_90": moe,
                      "coefficient_of_variation": round(cv, 3)}
            ev.update(messages_translated=done, messages_in_library=total)
            if not reliable or done:
                ev["finding"] = "count not reliable" if not reliable else "translated messages exist"
            for c in r["counties"].split(";"):
                out.append(finding(16, f"{fa.plain(r['language']).lower()}-{c.lower()}",
                                   f"{r['language']}: {'reliable count, ' if reliable else ''}{done} of {total} messages translated – {COUNTY_LABEL[c]}",
                                   c, "all", people if (reliable and not done) else None, ev,
                                   ["languages", "messages"], unit="people" if reliable else "needs county data",
                                   title=TITLES[16]))
    return out


def pets(inp: Inputs) -> list:
    ok_words = {"allowed", "leashed or carrier", "crated only"}
    out = []
    for c in COUNTIES:
        for h in HAZARDS:
            sc = inp.scen[(c, h)]
            usable = [s for k, s in inp.sites.items() if s["county"] == c and h in inp.usable[k]]
            yes = [s["name"] for s in usable if s.get("pets") in ok_words]
            unk = [s["name"] for s in usable if s.get("pets") not in ok_words]
            hh = sc["dog_households"] + sc["cat_households"]
            out.append(finding(17, f"{h}-{c.lower()}", f"Pet households vs pet-friendly sites – {COUNTY_LABEL[c]} ({HZ_LABEL[h]})",
                               c, h, hh, {"dog_households_in_shelter": sc["dog_households"],
                                          "cat_households_in_shelter": sc["cat_households"],
                                          "usable_sites_accepting_pets_2026": len(yes),
                                          "usable_sites_pet_policy_unknown": len(unk),
                                          "households_per_pet_friendly_site": round(hh / len(yes)) if yes else None,
                                          "pet_friendly_sites": yes,
                                          "note": "Service animals are always allowed."},
                               ["pets", "sites", "people"], unit="households (a household can have a dog and a cat)",
                               title=TITLES[17]))
    return out


def homeless(inp: Inputs) -> list:
    out = []
    with open(SOURCES_DIR / "county_lines.csv", newline="", encoding="utf-8") as fh:
        pit = {r["county"]: r for r in csv.DictReader(fh) if r["line"] == "homelessness"}
    for c in COUNTIES:
        r = pit[c]
        import re
        m = re.search(r"unsheltered (\d[\d,]*)", r["detail"])
        add = int(m.group(1).replace(",", "")) if m else int(r["value"])
        for h in HAZARDS:
            sc = inp.scen[(c, h)]
            out.append(finding(18, f"{h}-{c.lower()}", f"Add the 2026 Point-in-Time count – {COUNTY_LABEL[c]} ({HZ_LABEL[h]})", c, h, add,
                               {"shelter_demand_likely": sc["shelter_demand_central"], "people_added": add,
                                "unsheltered_only": bool(m), "pit_total": int(r["value"]),
                                "shelter_demand_with_pit": sc["shelter_demand_central"] + add,
                                "increase_pct": round(100 * add / sc["shelter_demand_central"], 1) if sc["shelter_demand_central"] else None,
                                "count_date": r["period"]},
                               ["pit", "people", "rates"],
                               [assume("Every unsheltered person may seek a public shelter (upper bound); Oʻahu: total count (split not released)", "100%")],
                               title=TITLES[18]))
    return out


def childcare(inp: Inputs) -> list:
    fr = load_geojson(ROOT / "data" / "raw" / "hub" / "fire_risk.geojson", "State Fire Risk Areas")
    high = ZoneIndex({"type": "FeatureCollection", "features": [
        f for f in fr["features"] if (f["properties"].get("risk_rating") or "").strip() == "High" and f.get("geometry")]})
    out = []
    for c in COUNTIES:
        cc = [x for x in inp.state["childcare"] if x["county"] == c]
        for h in HAZARDS:
            if h == "hurricane":
                inz = cc
                how = "a hurricane affects the whole county"
            elif h == "wildfire":
                inz = [x for x in cc if high.contains(x["lon"], x["lat"])]
                how = "inside a State Fire Risk Area rated High"
            else:
                inz = [x for x in cc if x["zones"].get(h)]
                how = "inside the tsunami evacuation zone" if h == "tsunami" else "inside a FEMA high-risk flood zone"
            out.append(finding(19, f"{h}-{c.lower()}", f"Childcare centres in the {HZ_LABEL[h]} zone – {COUNTY_LABEL[c]}",
                               c, h, len(inz), {"centres_in_zone": len(inz), "centres_in_county": len(cc), "how": how,
                                                "children_enrolled": "needs county data (enrolment by centre)"},
                               ["childcare", "fire" if h == "wildfire" else ("tsunami" if h == "tsunami" else "sites")],
                               unit="childcare centres", areas=sorted({x["tract"] for x in inz if x["tract"]})[:5],
                               title=TITLES[19]))
    return out


def visitors(inp: Inputs) -> list:
    out = []
    with open(SOURCES_DIR / "county_lines.csv", newline="", encoding="utf-8") as fh:
        vis = {r["county"]: r for r in csv.DictReader(fh) if r["line"] == "visitors"}
    pp = inp.pf["per_person"]
    for c in COUNTIES:
        r = vis[c]
        n = int(r["value"])
        out.append(finding(20, c.lower(), f"Visitors on the island(s) – {COUNTY_LABEL[c]} (tsunami)", c, "tsunami", n,
                           {"visitors_average_day_2025": n, "detail": r["detail"],
                            "visitors_in_tsunami_zone": "needs county data (hotel and rental locations)",
                            "peak_day": "needs DBEDT monthly data (the Data Book gives the annual average)",
                            "island_level": True},
                           ["visitors"], title=TITLES[20]))
        rows = {f"{d} days": {"meals": n * pp["meals_per_day"]["value"] * d,
                              "water_gal": n * pp["water_gal_per_day"]["value"] * d} for d in (3, 7)}
        out.append(finding(21, c.lower(), f"Stranded visitors for 3 or 7 days – {COUNTY_LABEL[c]}", c, "all", n,
                           {"visitors_average_day_2025": n, "by_stay": rows, "island_level": True},
                           ["visitors", "factors"],
                           [assume("Every visitor on the island is stranded and needs meals and water from mass care (upper bound)", "100%")],
                           title=TITLES[21]))
    return out


def care(inp: Inputs) -> list:
    out = []
    for h in HAZARDS:
        for c in COUNTIES:
            rows = []
            for f in inp.access["facilities"]:
                if f["county"] != c or not f["zones"].get(h):
                    continue
                a = inp.access["areas"].get(f["tract"], {})
                best = min(((v[0], k) for k, v in a.get("sites", {}).items()
                            if v[0] is not None and h in inp.usable.get(k, [])), default=(None, None))
                rows.append({"name": f["name"], "type": f["type_label"], "zone": f["zones"][h],
                             "nearest_usable_site": inp.sites[best[1]]["name"] if best[1] else None,
                             "drive_min": None if best[0] is None else round(best[0]), "area": f["tract"]})
            if h in ("hurricane", "wildfire"):
                continue                     # no facility-level zone screen (as in the plan)
            out.append(finding(22, f"{h}-{c.lower()}", f"Care facilities in the {HZ_LABEL[h]} zone – {COUNTY_LABEL[c]}",
                               c, h, len(rows), {"facilities": rows,
                                                 "over_15_min_or_no_site": sum(1 for r in rows if r["drive_min"] is None or r["drive_min"] > 15),
                                                 "residents_or_patients": "needs county data (census of each facility)",
                                                 "drive_from": "the facility's Census area land point (normal traffic)"},
                               ["care", "sites", "drive", "tsunami" if h == "tsunami" else "sites"],
                               unit="care facilities", areas=sorted({r["area"] for r in rows})[:5],
                               title=TITLES[22]))
    return out


def safe_walk(inp: Inputs) -> list:
    out = []
    w = inp.hub["safe_zone_walk"]
    for c in COUNTIES:
        rows = {f: a for f, a in w.items() if a["county"] == c}
        o15 = {f: a["no_car"] for f, a in rows.items() if a["walk_min"] is not None and a["walk_min"] > 15}
        o30 = {f: a["no_car"] for f, a in rows.items() if a["walk_min"] is not None and a["walk_min"] > 30}
        times = [a["walk_min"] for a in rows.values() if a["walk_min"] is not None]
        out.append(finding("23a", f"walk-{c.lower()}", f"No car, inside the tsunami zone, over 15 minutes' walk to a safe zone – {COUNTY_LABEL[c]}",
                           c, "tsunami", sum(o15.values()),
                           {"areas_checked": len(rows), "areas_over_15_min": len(o15), "areas_over_30_min": len(o30),
                            "no_car_over_30_min": round(sum(o30.values())),
                            "no_car_in_tsunami_zone": round(sum(a["no_car"] for a in rows.values())),
                            "median_walk_min": round(statistics.median(times), 1) if times else None,
                            "longest_walk_min": round(max(times), 1) if times else None,
                            "maui_zones_2013": c == "Maui",
                            "method": "ArcGIS walking time" if all(a["method"] != "straight_line" for a in rows.values()) else "some areas straight-line (labelled)"},
                           ["safe_zones", "walk", "people", "tsunami"],
                           [assume("Walking starts at a populated point inside each area's tsunami zone (2020 Census block)", "1 point per area")],
                           areas=top_areas(o15), title=TITLES["23a"]))
    fc = inp.hub["fire_compare"]
    for c in COUNTIES:
        v = fc[c]
        so = {f: inp.hub["fire_risk"][f]["high_people"] for f in v["state_only"]}
        no = {f: (inp.tracts[f].get("population") or 0) for f in v["nri_only"]}
        out.append(finding("23b", f"fire-{c.lower()}", f"Areas high in the State Fire Risk layer but not in the plan's wildfire areas, and the reverse – {COUNTY_LABEL[c]}",
                           c, "wildfire", sum(so.values()),
                           {"areas_both": len(v["both"]), "areas_state_high_only": len(v["state_only"]),
                            "areas_nri_only": len(v["nri_only"]), "agreement": v["agreement"],
                            "people_state_high": v["people_state_high"], "people_plan_wildfire_areas": v["people_nri"],
                            "people_in_state_only_areas": round(sum(so.values())),
                            "people_in_nri_only_areas": round(sum(no.values())),
                            "state_only_areas": [inp.label(f) for f in top_areas(so, 5)],
                            "nri_only_areas": [inp.label(f) for f in top_areas(no, 5)]},
                           ["fire", "people"],
                           [assume("An area is 'high' in the State layer when at least half its people live in a High fire risk area", f"{int(inp.hub['meta']['state_high_share'] * 100)}%")],
                           areas=top_areas(so), title=TITLES["23b"]))
    return out


# ---------------------------------------------------------------- group B: roads

def road_summary(inp: Inputs) -> dict:
    """Committed per-area summary of the road-closure answers (raw answers stay local)."""
    if not require_all_or_none(fa.RAW, RAW_ROADS, "raw road-closure answers"):
        s = load_json(ROADS_OUT, "committed road-closure summary") if ROADS_OUT.exists() else None
        if not s:
            raise MissingInput(f"Build stopped: no raw road-closure answers in {rel(fa.RAW)} and no committed {rel(ROADS_OUT)}.")
        return s
    cfg = load_json(ROADS_CFG, "road-closure settings")
    iso = cfg["isolated_minutes"]
    st = ba.parse_od(fa.RAW / "od_schools.json")
    out = {"isolated_min": iso, "scenarios": {}}
    names = {c["id"]: c for c in cfg["closures"]}

    def parse(path):
        res = {}
        for v in fa.load_json(fa.RAW / path, {"results": {}})["results"].values():
            m = v.get("matrix") or {}
            cn = m.get("costAttributeNames") or []
            ti = 0 if not cn else cn.index("TravelTime" if "TravelTime" in cn else "WalkTime")
            times = {v["destinations"][int(i) - 1]: c[ti] for i, c in (m.get("1") or {}).items() if c[ti] is not None}
            res.setdefault(v["scenario"], {})[v["origin"]] = (v["destinations"], times)
        return res

    for mode, path in (("drive", "od_closures_drive.json"), ("walk", "od_closures_walk.json"), ("drive", "od_flooded_drive.json")):
        for scen, origins in parse(path).items():
            rows, pair_add = {}, []
            for o, (dests, times) in origins.items():
                a = inp.access["areas"].get(o, {}).get("sites", {})
                if mode == "drive":
                    base = {d: a[d][0] for d in dests if d in a and a[d][0] is not None}
                    base.update({d: st[o][d][0] for d in dests if d in st.get(o, {}) and st[o][d][0] is not None})
                else:
                    base = {d: a[d][2] for d in dests if d in a and a[d][2] is not None}
                act = [d for d in dests if "|" in d]            # 2026 activated sites (keys "name|county")
                mn = lambda t, ks: min((t[k] for k in ks if k in t), default=None)  # noqa: E731
                lim = iso if mode == "drive" else float("inf")
                lost = sum(1 for d, t in base.items() if t <= lim and (d not in times or times[d] > lim))
                pair_add += [times[d] - base[d] for d in base if d in times]
                r = [mn(base, dests), mn(times, dests), mn(base, act), mn(times, act), lost]
                rows[o] = [None if v is None else round(v, 1) for v in r[:4]] + [lost]
            key = f"{scen}|{mode}"
            pop = {o: inp.tracts.get(o, {}).get("population") or 0 for o in rows}
            lim = iso if mode == "drive" else float("inf")
            cut = lambda b, w: b is not None and (w is None or (w > lim and b <= lim))  # noqa: E731
            isolated = sorted(o for o, r in rows.items() if cut(r[0], r[1]))
            iso_act = sorted(o for o, r in rows.items() if cut(r[2], r[3]))
            no_route = sorted(o for o, r in rows.items() if r[0] is not None and r[1] is None)
            added = {o: r[3] - r[2] for o, r in rows.items() if r[2] is not None and r[3] is not None}
            longer = {o: v for o, v in added.items() if v >= 1}
            lost = {o for o, r in rows.items() if r[4] > 0}
            hit = set(longer) | lost | set(isolated) | set(iso_act)
            c = names.get(scen, {})
            isl = c.get("island") or next(iter({inp.island.get(o) for o in rows}), "")
            out["scenarios"][key] = {
                "id": scen, "mode": mode, "name": c.get("name") or f"All 'flooded highway' segments (sea level rise 3.2 ft) closed – {isl}",
                "short": c.get("short") or f"Flooded highways closed – {isl}", "why": c.get("why", ""),
                "island": isl, "county": c.get("county") or fa.ISLE_COUNTY.get(isl, ""),
                "row_fields": ["nearest known site, before (min)", "after", "nearest 2026 activated site, before",
                               "after", "known sites no longer within reach"],
                "areas": rows, "areas_routed": len(rows), "areas_longer": len(longer),
                "areas_losing_sites": len(lost), "isolated": isolated, "isolated_from_2026_sites": iso_act,
                "no_route": no_route,
                "people_isolated": round(sum(pop[o] for o in set(isolated) | set(iso_act))),
                "people_longer": round(sum(pop[o] for o in longer)),
                "people_losing_sites": round(sum(pop[o] for o in lost)),
                "people_affected": round(sum(pop[o] for o in hit)),
                "max_added_min": round(max(added.values()), 1) if added else 0,
                "median_added_min_where_longer": round(statistics.median(longer.values()), 1) if longer else 0,
                "max_added_any_site_min": round(max(pair_add), 1) if pair_add else 0}
    return out


def roads(inp: Inputs, rs: dict) -> list:
    out = []
    for key, s in sorted(rs["scenarios"].items()):
        test = 24 if s["mode"] == "drive" else 25
        people = s["people_affected"]        # longer trip, sites lost or isolated: each area once
        rows = {o: (inp.tracts.get(o, {}).get("population") or 0) for o, r in s["areas"].items()
                if r[4] > 0 or o in s["isolated"] or o in s["isolated_from_2026_sites"]
                or (r[2] is not None and r[3] is not None and r[3] - r[2] >= 1)}
        ev = {"areas_routed": s["areas_routed"], "areas_with_longer_trip_to_2026_site": s["areas_longer"],
              "areas_losing_sites_within_reach": s["areas_losing_sites"],
              "areas_isolated": len(s["isolated"]), "areas_isolated_from_2026_sites": len(s["isolated_from_2026_sites"]),
              "areas_no_route": len(s["no_route"]),
              "people_isolated": s["people_isolated"], "people_longer_trip": s["people_longer"],
              "people_losing_sites": s["people_losing_sites"],
              "max_added_min_to_2026_site": s["max_added_min"], "median_added_min": s["median_added_min_where_longer"],
              "max_added_min_any_site": s["max_added_any_site_min"],
              "isolated_rule": f"over {rs['isolated_min']} minutes or no route" if test == 24 else "no walking route",
              "reach": f"{rs['isolated_min']}-minute drive" if test == 24 else "walking route (sites within 12 km)",
              "why_this_road": s["why"], "note": NOT_NO_SHELTER}
        src = ["barriers", "walk" if test == 25 else "drive", "sites", "schools"]
        if s["id"].startswith("flooded_"):
            src.append("flooded")
        out.append(finding(test, key.replace("|", "-"), s["name"] + (" – walking" if test == 25 else ""),
                           s["county"], "all", people, ev, src,
                           [assume("Closure location along the highway (a stretch of about 0.8 km)", "team assumption")]
                           if not s["id"].startswith("flooded_") else
                           [assume("Every flooded-highway segment on the island closed at once (sea level rise 3.2 ft scenario)", "all segments")],
                           areas=top_areas(rows), title=TITLES[test]))
    return out


# ---------------------------------------------------------------- assemble

def rank(findings: list) -> list:
    key = lambda f: (f["unit"] != "people" or f["people_affected"] is None, -(f["people_affected"] or 0), f["id"])  # noqa: E731
    for i, f in enumerate(sorted(findings, key=key), 1):
        f["rank"] = i
    by_c = {}
    for f in sorted(findings, key=lambda f: f["rank"]):
        by_c.setdefault(f["county"], []).append(f)
    for rows in by_c.values():
        for i, f in enumerate(rows, 1):
            f["county_rank"] = i
    return sorted(findings, key=lambda f: f["rank"])


def build(groups: str = "AB") -> dict:
    inp = Inputs()
    coast = ZoneIndex(load_geojson(fa.COAST, "State coastline (island outlines)"))
    from build_islands import island_of as _island_of
    island_of = lambda x, y: _island_of(coast, x, y)  # noqa: E731
    if not (fa.RAW / "od_schools.json").exists():
        raise MissingInput(f"Build stopped: the DOE-school drive matrix ({rel(fa.RAW / 'od_schools.json')}) is missing.")
    st = school_times()
    blocks = block_shares.load()
    rs = road_summary(inp) if "B" in groups else {"isolated_min": None, "scenarios": {}}
    findings = (site_loss(inp) + zone_d_schools(inp, st, island_of) + combined(inp, blocks) +
                several_counties(inp) + rate_sweep(inp) + stays(inp) + outages(inp) + far(inp) +
                languages(inp) + pets(inp) + homeless(inp) + childcare(inp) + visitors(inp) +
                care(inp) + safe_walk(inp) + (roads(inp, rs) if "B" in groups else []))
    ids = [f["id"] for f in findings]
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        raise RuntimeError(f"duplicate finding ids: {sorted(dup)[:5]}")
    return {"label": inp.cfg["label"], "built_at": now_hst(),
            "method": "Deterministic code computes every number from the plan's data; people review the results.",
            "tests": {str(k): v for k, v in TITLES.items()}, "share_method": blocks["method"] if blocks else "area",
            "findings": rank(findings), "roads": rs}


def write_csv(path: Path, findings: list) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["rank", "county_rank", "id", "test", "title", "scenario", "county", "hazard",
                    "people_affected", "unit", "evidence", "sources", "assumptions", "label"])
        for f in findings:
            w.writerow([f["rank"], f["county_rank"], f["id"], f["test"], f["title"], f["scenario"], f["county"],
                        f["hazard"], "" if f["people_affected"] is None else f["people_affected"], f["unit"],
                        json.dumps(f["evidence"], ensure_ascii=False, sort_keys=True),
                        "; ".join(f["sources"]),
                        "; ".join(f"{a['text']}: {a['value']} ({a['kind']})" for a in f["assumptions"]),
                        f["label"]])


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Stress tests: what could break")
    ap.add_argument("--groups", default="AB", help="A = existing data (tests 1-23), B = road closures (24-25)")
    args = ap.parse_args(argv)
    try:
        s = build(args.groups)
    except MissingInput as e:
        print(e, file=sys.stderr)
        return 1
    if "B" in args.groups:
        ROADS_OUT.write_text(json.dumps(s["roads"], ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    s["groups"] = args.groups
    OUT.write_text(json.dumps(s, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    write_csv(OUT_CSV, s["findings"])
    from collections import Counter
    print(f"Wrote {rel(OUT)} ({len(s['findings'])} findings, {OUT.stat().st_size / 1024:.0f} KB), {rel(OUT_CSV)}" + (f", {rel(ROADS_OUT)}" if "B" in args.groups else ""))
    print("findings per test:", dict(sorted(Counter(f["test"] for f in s["findings"]).items(), key=lambda kv: (len(kv[0].rstrip("ab")), kv[0]))))
    for c in [*COUNTIES, "Statewide"]:
        top = [f for f in s["findings"] if f["county"] == c][:3]
        print(f"{c}:")
        for f in top:
            print(f"  #{f['rank']} {f['scenario']}: {f['people_affected']} {f['unit']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
