/* Hawaiʻi ESF-6 Planning – what-if engine (pure arithmetic: no page, no storage, no requests).
   Every input comes from the planner; every other number comes from the data bundle.
   The formulas are the plan's own (scripts/model_needs.py resources, scripts/match.py need
   lines), so the plan defaults reproduce the plan's numbers exactly. A Python copy
   (scripts/whatif.py) is checked against this file by the tests. Results are a what-if,
   not a forecast. */
(function (root) {
  "use strict";

  /* Python's round(): halves go to the even neighbour (match.py rounds need lines this way) */
  function roundHE(x) {
    const f = Math.floor(x), d = x - f;
    if (d > 0.5) return f + 1;
    if (d < 0.5) return f;
    return f % 2 === 0 ? f : f + 1;
  }
  const ceil = (x) => Math.ceil(x);

  /* plan defaults for one county x hazard (W = bundle.whatif, key = "County|hazard") */
  function defaults(W, key) {
    const a = W.scenarios[key], d = W.defaults;
    return { rate: a.rate, stay: d.stay_days, outage: d.outage_days, trip: d.people_per_trip,
      support: null, cap: {} };
  }

  /* county x hazard results. inp: {rate, stay, outage, trip, support (null = plan), cap} */
  function compute(W, key, inp) {
    const a = W.scenarios[key], F = W.factors;
    const k = inp.rate === a.rate ? 1 : inp.rate / a.rate;     // exact at the plan rate
    const D = a.demand * k, CH = a.children * k, PD = a.power_in_shelter * k;
    const HH = a.households * k, LEP = a.lep_in_shelter * k, DIS = a.disability_in_shelter * k;
    const short = inp.stay <= 3;
    const staff = {};
    let staffTotal = 0;
    if (D > 0) {
      for (const [role, n] of F.staff) {
        const v = role === "children_area" ? (CH ? ceil(CH / n) : 0) : Math.max(1, ceil(D / n));
        staff[role] = v; staffTotal += v;
      }
    } else {
      for (const [role] of F.staff) staff[role] = 0;
    }
    const outlets = ceil(PD * F.outlets_per_person);
    const outletsDay = inp.outage > 0 ? Math.max(outlets, ceil(a.power_at_risk * F.charges_per_day)) : outlets;
    const water = ceil(D * F.water_gal_per_day), meals = ceil(D * F.meals_per_day);
    const transport = roundHE(a.no_car_at_risk);
    return {
      people_in_shelter: roundHE(a.at_risk * inp.rate),
      cots: ceil(D),
      floor_sqft: short ? ceil(D * F.floor_sqft_72h) : ceil(D * F.floor_sqft_2wk),
      floor_basis: short ? "72h" : "2wk",
      water_per_day: water, water_total: water * inp.stay,
      meals_per_day: meals, meals_total: meals * inp.stay,
      toilets: short ? ceil(D / F.persons_per_toilet_72h) : ceil(D / F.persons_per_toilet_2wk),
      outlets_per_day: outletsDay, charge_point_days: inp.outage > 0 ? outletsDay * inp.outage : 0,
      staff, staff_total: staffTotal,
      interpreters: a.languages.map(([lang, share]) => [lang, roundHE(roundHE(LEP) * share)]),
      support_people: inp.support === null || inp.support === undefined ? roundHE(DIS) : roundHE(D * inp.support),
      support_share_plan: a.demand ? a.disability_in_shelter / a.demand : 0,
      transport_people: transport, trips: ceil(transport / inp.trip),
      dog_households: ceil(HH * F.dog_share), cat_households: ceil(HH * F.cat_share),
      children: roundHE(CH),
    };
  }

  /* allocation of each Census area's people in shelter to its nearest usable 2026 site on the
     SAME island by drive time. areas: [{f, island, people (at the plan rate), a: [[site id,
     drive min, ...]]}]; sites: [{id, island, usable}]. cap: {site id: people} (planner). */
  function allocate(areas, sites, inp, planRate) {
    const k = inp.rate === planRate ? 1 : inp.rate / planRate;
    const usable = new Map(sites.filter((s) => s.usable).map((s) => [s.id, s]));
    const load = new Map();
    const rows = [];
    let unassigned = 0;
    for (const t of areas) {
      const people = t.people * k;
      const best = (t.a || []).filter((r) => usable.has(r[0]) && r[1] !== null && usable.get(r[0]).island === t.island)
        .sort((x, y) => x[1] - y[1] || x[0] - y[0])[0];
      if (best) load.set(best[0], (load.get(best[0]) || 0) + people);
      else unassigned += people;
      rows.push({ f: t.f, people, site: best ? best[0] : null, drive: best ? best[1] : null });
    }
    const siteRows = [...usable.values()].map((s) => {
      const l = load.get(s.id) || 0, c = inp.cap ? inp.cap[s.id] : undefined;
      const has = typeof c === "number" && c >= 0;
      return { id: s.id, load: l, cap: has ? c : null, over: has ? Math.max(0, ceil(l) - c) : null };
    }).sort((x, y) => y.load - x.load || x.id - y.id);
    const known = siteRows.filter((s) => s.cap !== null);
    return { areas: rows, sites: siteRows, unassigned,
      over_sites: known.filter((s) => s.over > 0).length,
      shortfall: known.length ? known.reduce((n, s) => n + s.over, 0) : null };
  }

  /* inputs <-> URL query (only values that differ from the plan defaults are written) */
  const KEYS = { rate: "rate", stay: "stay", outage: "outage", trip: "trip", support: "support" };
  function toQuery(inp, dflt) {
    const q = {};
    for (const [k, name] of Object.entries(KEYS)) {
      if (inp[k] !== null && inp[k] !== undefined && inp[k] !== dflt[k]) q[name] = String(inp[k]);
    }
    const cap = Object.entries(inp.cap || {}).filter(([, v]) => typeof v === "number")
      .sort((x, y) => x[0] - y[0]).map(([id, v]) => `${id}-${v}`).join(".");
    if (cap) q.cap = cap;
    return q;
  }
  function fromQuery(get, dflt, limits) {
    const inp = { ...dflt, cap: {} };
    const num = (name, lo, hi) => {
      const v = Number(get(name));
      return get(name) !== null && Number.isFinite(v) && v >= lo && v <= hi ? v : undefined;
    };
    const L = limits;
    const set = (k, v) => { if (v !== undefined) inp[k] = v; };
    set("rate", num("rate", L.rate[0], L.rate[1]));
    set("stay", num("stay", L.stay[0], L.stay[1]));
    set("outage", num("outage", L.outage[0], L.outage[1]));
    set("trip", num("trip", L.trip[0], L.trip[1]));
    set("support", num("support", L.support[0], L.support[1]));
    for (const part of String(get("cap") || "").split(".")) {
      const m = /^(\d+)-(\d+)$/.exec(part);
      if (m) inp.cap[Number(m[1])] = Number(m[2]);
    }
    return inp;
  }

  const api = { roundHE, defaults, compute, allocate, toQuery, fromQuery };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.WhatIf = api;
}(typeof self !== "undefined" ? self : this));
