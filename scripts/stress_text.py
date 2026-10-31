#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – plain words for the stress tests (app bundle and PDF playbooks).

Turns each finding's evidence (data/processed/stress_tests.json) into [label, value] lines and
a one-line summary, picks the top 10 per county, and holds the "Questions for counties" (no
data, no numbers). Visible text never shows file names, snake_case keys, null or NaN.
"""
from __future__ import annotations

LABEL = "Stress test, not a forecast"
WHATIF_LABEL = "What-if, not a forecast"
TOP = 10
PER_TEST = 2                  # at most 2 findings of one test in a county's top 10
NEEDS_DATA = "needs county data"

QUESTIONS = [
    ["Shelter buildings in an earthquake or a strong hurricane",
     "Which shelter buildings have been assessed for earthquake and hurricane-wind resilience, "
     "and which need a check before they are used after a strong event?"],
    ["Resupply for Molokaʻi and Lānaʻi",
     "How would water, food, cots, fuel and medical supplies reach Molokaʻi and Lānaʻi if the "
     "harbours or airports close for several days, and who decides the order of shipments?"],
    ["Cell network outages",
     "Which areas lose mobile phone service first in a long power outage or after wind damage, "
     "and how will warnings and shelter information reach them (radio, sirens, door-to-door)?"],
    ["Schools used as shelters",
     "When a school is used as a shelter, how long can it stay open before classes must "
     "restart, and where do residents go next?"],
    ["Partner capacity",
     "Could each county collect partner capacity (cots, meals, staff, vehicles, interpreters) "
     "with a county-run form such as Survey123, with no personal data, so the plan can show "
     "pledged capacity instead of 'confirm with partner'?"],
]

EV = {  # evidence key -> plain words
    "areas_pushed_outside": "Census areas pushed outside a 15-minute drive",
    "areas_left_with_no_usable_site_on_island": "Census areas left with no usable 2026 site on the island",
    "people_left_with_no_usable_site_on_island": "People left with no usable 2026 site on the island",
    "more_than_worst_single_loss": "People more than losing either site alone",
    "drive_limit_min": "Drive limit (minutes)", "island": "Island", "site": "Site", "sites": "Sites",
    "shelter_demand_likely": "May need a public shelter (likely)",
    "agreement": "Areas high in both, of all areas high in either",
    "areas_both": "Census areas high in both", "areas_state_high_only": "Census areas high in the State layer only",
    "areas_nri_only": "Census areas in the plan's wildfire areas only",
    "people_state_high": "People in State High fire risk areas",
    "people_plan_wildfire_areas": "People in the plan's wildfire areas (FEMA National Risk Index)",
    "people_in_state_only_areas": "People in State-only areas", "people_in_nri_only_areas": "People in plan-only areas",
    "state_only_areas": "Largest State-only areas", "nri_only_areas": "Largest plan-only areas",
    "people_in_extreme_zone": "People in the extreme tsunami zone",
    "people_in_standard_zone": "People in the standard tsunami zone",
    "shelter_demand_low": "May need a shelter (low)", "shelter_demand_high": "May need a shelter (high)",
    "sites_inside_extreme_zone": "2026 sites inside the extreme zone",
    "sites_usable_outside_both_zones": "2026 sites usable outside both zones",
    "sites_needed_at_250": "Sites needed at 250 people per site (team assumption)",
    "detail": "Detail", "peak_day": "Peak day", "visitors_average_day_2025": "Visitors on an average day (2025)",
    "visitors_in_tsunami_zone": "Visitors inside the tsunami zone", "by_stay": "By length of stay",
    "areas_routed": "Census areas routed", "areas_with_longer_trip_to_2026_site": "Census areas with a longer drive to a 2026 site",
    "areas_losing_sites_within_reach": "Census areas losing known sites within reach",
    "areas_isolated": "Census areas cut off (over the limit or no route)",
    "areas_isolated_from_2026_sites": "Census areas cut off from every 2026 site",
    "areas_no_route": "Census areas with no route at all", "isolated_rule": "Cut off means",
    "reach": "Within reach means",
    "max_added_min_to_2026_site": "Most minutes added to the nearest 2026 site",
    "max_added_min_any_site": "Most minutes added to any known site",
    "median_added_min": "Typical minutes added (median, where longer)",
    "people_isolated": "People in areas cut off", "people_longer_trip": "People with a longer trip",
    "people_losing_sites": "People losing known sites within reach", "why_this_road": "Why this road",
    "counties": "Counties", "people_in_shelter_likely": "People in shelter (likely)", "cots": "Cots",
    "meals_per_day": "Meals per day", "water_gal_per_day": "Water (gallons per day)",
    "staff_per_shift": "Shelter staff per shift",
    "interpreters_people_with_limited_english": "People with limited English in shelter, by language (interpreters)",
    "areas": "Census areas", "if_counted_separately": "People if each hazard is counted separately",
    "people_in_union": "People in either footprint (counted once)", "site_gap": "Site gap",
    "sites_usable_in_every_hazard": "2026 sites usable for every hazard in the pair",
    "per_day": "Per person per day", "known_2026_sites": "Known 2026 sites in the county",
    "not_reached_by": "Not reached by", "people_in_risk_area": "People in the risk area",
    "rate_likely_in_plan": "Likely rate in the plan", "rate_when_sites_run_out": "Rate when usable sites run out",
    "sites_needed_by_rate": "Sites needed by rate (250 people per site)", "usable_2026_sites": "Usable 2026 sites",
    "outlets_per_day_if_power_out": "Outlets per day if the power is out",
    "outlets_plan_in_shelter": "Outlets in the plan (people in shelter)",
    "power_dependent_in_risk_area": "Power-dependent residents in the risk area",
    "power_loss_area": "Power outage area", "site_backup_power": "Backup power at sites",
    "age65_alone_in_those_areas": "Age 65+ living alone in those areas",
    "areas_outside": "Census areas outside a 15-minute drive",
    "no_car_in_those_areas": "People without a car in those areas",
    "charge_point_days": "Charge-point days", "outlets_per_day_while_out": "Outlets per day while the power is out",
    "already_not_usable_in_plan": "Already treated as not usable in the plan",
    "zone_d_schools_in_county": "DOE schools in FEMA zone D (flood risk not mapped)",
    "zone_d_sites_2026": "2026 sites in FEMA zone D",
    "areas_checked": "Census areas checked", "areas_over_15_min": "Census areas over 15 minutes' walk",
    "areas_over_30_min": "Census areas over 30 minutes' walk", "longest_walk_min": "Longest walk (minutes)",
    "maui_zones_2013": "Maui County safe zones date from 2013", "median_walk_min": "Typical walk (median, minutes)",
    "method": "Method", "no_car_in_tsunami_zone": "People without a car in the tsunami zone",
    "no_car_over_30_min": "People without a car over 30 minutes' walk",
    "area": "Survey area", "coefficient_of_variation": "Coefficient of variation",
    "messages_in_library": "Messages in the library", "messages_translated": "Messages translated",
    "moe_90": "Margin of error (90%)", "people_limited_english": "People who speak English less than very well",
    "reliable": "Reliable count", "count_date": "Count date", "increase_pct": "Increase over the likely demand",
    "people_added": "People added", "pit_total": "Point-in-Time total",
    "shelter_demand_with_pit": "May need a shelter, with the count added",
    "unsheltered_only": "Unsheltered people only",
    "power_dependent_in_those_areas": "Power-dependent residents in those areas",
    "hearing_difficulty_in_tsunami_zone": "People with hearing difficulty in the tsunami zone",
    "cat_households_in_shelter": "Households with a cat in shelter",
    "dog_households_in_shelter": "Households with a dog in shelter",
    "households_per_pet_friendly_site": "Pet households per pet-friendly site",
    "pet_friendly_sites": "Usable sites that took pets in 2026",
    "usable_sites_accepting_pets_2026": "Usable sites that took pets in 2026 (count)",
    "usable_sites_pet_policy_unknown": "Usable sites with no announced pet policy",
    "centres_in_county": "Childcare centres in the county", "centres_in_zone": "Childcare centres in the zone",
    "children_enrolled": "Children enrolled", "how": "In the zone means", "drive_from": "Drive measured from",
    "facilities": "Facilities", "over_15_min_or_no_site": "Facilities over 15 minutes from a usable site, or none on the island",
    "residents_or_patients": "Residents or patients", "finding": "Result", "people": "People",
}
SKIP = {"note", "upper_bound", "island_level"}
UNIT = {"water_gal": "gallons of water", "meals": "meals", "toilets": "toilets",
        "floor_sqft": "sq ft of floor space"}
PCT_KEYS = {"rate_likely_in_plan", "rate_when_sites_run_out"}
SUMMARY_KEYS = {  # one or two extra numbers for the one-line summary
    "1": ["areas_pushed_outside"], "2": ["areas_pushed_outside", "more_than_worst_single_loss"],
    "3": ["areas_pushed_outside"], "4": ["sites_usable_in_every_hazard", "site_gap"],
    "5": ["sites_usable_in_every_hazard", "site_gap"], "6": ["outlets_per_day_if_power_out"],
    "7": ["sites_usable_in_every_hazard", "site_gap"], "8": ["shelter_demand_likely", "sites_inside_extreme_zone"],
    "9": ["cots", "staff_per_shift"], "10": ["rate_when_sites_run_out", "usable_2026_sites"],
    "11": [], "12": ["outlets_per_day_while_out"], "13": ["areas_outside"], "14": [],
    "15": ["areas_outside"], "16": ["messages_translated"], "17": ["usable_sites_accepting_pets_2026"],
    "18": ["increase_pct"], "19": ["centres_in_county"], "20": ["visitors_in_tsunami_zone"],
    "21": [], "22": ["over_15_min_or_no_site"], "23a": ["areas_over_15_min", "longest_walk_min"],
    "23b": ["areas_state_high_only", "areas_nri_only"],
    "24": ["areas_isolated_from_2026_sites", "max_added_min_any_site"],
    "25": ["areas_with_longer_trip_to_2026_site", "max_added_min_to_2026_site"],
}


def num(v) -> str:
    if v is None:
        return NEEDS_DATA
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, float) and not v.is_integer():
        return f"{v:,.1f}"
    if isinstance(v, (int, float)):
        return f"{int(round(v)):,}"
    return str(v)


def value(key: str, v) -> str:
    if v is None:
        return {"not_reached_by": "–", "households_per_pet_friendly_site": "no pet-friendly usable site",
                "rate_when_sites_run_out": "not reached by 20%"}.get(key, NEEDS_DATA)
    if key in PCT_KEYS:
        return f"{round(v * 100, 1):g}%"
    if key == "agreement":
        return f"{round(v * 100):g}%"
    if key == "increase_pct":
        return f"{v:g}%"
    if key == "coefficient_of_variation":
        return f"{round(v * 100):g}%"
    if isinstance(v, list):
        if v and isinstance(v[0], dict):            # care facilities
            return "; ".join(f"{x['name']} ({x['type'].lower()}, {x['zone']}): "
                             + (f"{x['nearest_usable_site']}, {x['drive_min']} min drive"
                                if x["nearest_usable_site"] else "no usable 2026 site on the island")
                             for x in v) or "none"
        return ", ".join(map(str, v)) or "none"
    if isinstance(v, dict):
        parts = []
        for k, x in v.items():
            if isinstance(x, dict):
                parts.append(f"{k}: " + ", ".join(f"{num(y)} {UNIT.get(k2, k2)}" for k2, y in x.items()))
            elif k in UNIT:
                parts.append(f"{num(x)} {UNIT[k]}")
            else:
                parts.append(f"{k}: {num(x)}")
        return "; ".join(parts)
    return num(v)


def evidence_lines(f: dict) -> list:
    return [[EV[k], value(k, v)] for k, v in f["evidence"].items() if k not in SKIP and k in EV]


def headline(f: dict) -> str:
    if f["people_affected"] is None:
        return f"{f['measure'] or 'People affected'}: {NEEDS_DATA}"
    return f"{f['people_affected']:,} {f['measure']}"


PROPER = {"Census", "State", "FEMA", "DOE", "People"}


def lower1(label: str) -> str:
    """Lower-case the first letter only, never a proper name ("Census areas …")."""
    first = label.split(" ", 1)[0]
    return label if first in PROPER - {"People"} else label[0].lower() + label[1:]


def extra(f: dict) -> str:
    """The one or two extra numbers of the one-line summary ("" when none)."""
    return "; ".join(f"{lower1(EV[k])}: {value(k, f['evidence'][k])}" for k in SUMMARY_KEYS.get(f["test"], [])
                     if k in f["evidence"])


def summary(f: dict) -> str:
    x = extra(f)
    return headline(f) + (f" ({x})" if x else "")


def in_county(f: dict, county: str) -> bool:
    return f["county"] == county or (f["county"] == "Statewide" and county in f["evidence"].get("counties", []))


def top(findings: list, county: str, hazard: str | None = None, n: int = TOP) -> list:
    """Top n findings for a county (optionally one hazard, plus 'all hazards' findings), in
    rank order (people affected), at most PER_TEST of one test so different risks show."""
    out, seen = [], {}
    for f in sorted(findings, key=lambda f: f["rank"]):
        if not in_county(f, county) or not f["people_affected"]:
            continue
        if hazard and not ({hazard, "all"} & set(f["hazard"].split("+"))):
            continue
        if seen.get(f["test"], 0) >= PER_TEST:
            continue
        seen[f["test"]] = seen.get(f["test"], 0) + 1
        out.append(f)
        if len(out) == n:
            break
    return out
