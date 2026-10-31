/* Hawaiʻi ESF-6 Planning – Stress tests and What-if views. Loaded by app.js (same origin,
   pre-cached) only when one of these views opens; uses app.js helpers (el, table, fmt, DATA).
   Every number comes from the data file (data/stress.json); nothing is stored. */
"use strict";

/* ---------- shared: hazard names, CSV download ---------- */
function hzName(h) {
  const L = { ...Object.fromEntries(DATA.hazards), dam: "Dam failure", power: "Power loss", all: "All hazards" };
  return String(h).split("+").map((x) => L[x] || x).join(" + ");
}
const capFirst = (t) => (t ? t[0].toUpperCase() + t.slice(1) : t);

/* builds the file in the page (no request): a spreadsheet-safe CSV with a byte-order mark */
function downloadCsv(name, rows) {
  const esc = (v) => {
    const t = v === null || v === undefined ? "" : String(v);
    return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
  };
  const text = "﻿" + rows.map((r) => r.map(esc).join(",")).join("\n") + "\n";
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = el("a", { href: url, download: name, hidden: "" });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/* ---------- Stress tests: what could break (computed at build time, not a forecast) ---------- */
const STRESS = { hazardOnly: false };
/* rows: [id, test, scenario, county ("Statewide|A|B" for several counties), hazard, people
   (null = needs county data), rank, county rank, more, sources, assumptions, areas, sites, evidence] */
const inCounty = (r, county) => r[3] === county || (r[3].startsWith("Statewide|") && r[3].split("|").includes(county));
function stressHead(r) {
  const S = DATA.stress, m = S.measures[r[1]] || "";
  return r[5] === null ? `${capFirst(m)}: ${S.needs_data}` : `${fmt(r[5])} ${m}`;
}
function findingLinks(r, county, hazard) {
  const h = DATA.hazards.some(([k]) => k === r[4]) ? r[4] : hazard;
  const label = Object.fromEntries(DATA.tracts.map((t) => [t.f, t.l || t.f]));
  const out = [];
  for (const f of r[11]) {
    if (!label[f]) continue;
    out.push(el("a", { href: `?county=${encodeURIComponent(county)}&hazard=${h}&area=${f}#plan` }, label[f]));
  }
  for (const id of r[12]) {
    const s = DATA.sites.find((x) => x.id === id);
    if (s && s.county === county && s.lon !== null) out.push(el("a", { href: `?county=${encodeURIComponent(county)}&hazard=${h}&site=${id}#plan` }, s.name));
  }
  return out.flatMap((a, i) => (i ? [", ", a] : [a]));
}
function findingCard(r, county, hazard) {
  const S = DATA.stress;
  const links = findingLinks(r, county, hazard);
  return el("li", { class: "finding" },
    el("h3", null, r[2]),
    el("p", { class: "finding-meta" }, `Test ${r[1]}: ${S.tests[r[1]]} · ${hzName(r[4])} · rank ${fmt(r[7])} in the county, ${fmt(r[6])} statewide`),
    el("p", { class: "finding-head" }, el("strong", null, stressHead(r)), r[8] ? ` (${r[8]})` : ""),
    el("p", null, el("span", { class: "tag" }, S.label)),
    el("details", { class: "finding-detail" }, el("summary", null, "Evidence, sources and assumptions"),
      r[13] ? table(`Evidence – ${r[2]}`, ["What", "Number"], r[13]) : null,
      el("h4", null, "Sources"), el("ul", null, r[9].map((i) => el("li", null, S.sources[i]))),
      el("h4", null, "Assumptions"),
      r[10].length ? el("ul", null, r[10].map((i) => el("li", null, S.assumptions[i])))
        : el("p", null, "Only the plan's own factors and rates.")),
    links.length ? el("p", { class: "finding-links" }, "Show on the map: ", links) : null);
}
function stressCsv(rows, county) {
  const S = DATA.stress;
  downloadCsv(`stress-tests-${county.toLowerCase()}.csv`, [
    ["Rank in county", "Rank statewide", "Test", "Test name", "Scenario", "Hazard", "Number", "What is counted", "More", "Sources", "Assumptions", "Label"],
    ...rows.map((r) => [r[7], r[6], r[1], S.tests[r[1]], r[2], hzName(r[4]), r[5] === null ? S.needs_data : r[5],
      S.measures[r[1]] || "", r[8], r[9].map((i) => S.sources[i]).join("; "), r[10].map((i) => S.assumptions[i]).join("; "), S.label])]);
}

function renderStress() {
  const app = document.getElementById("app");
  const county = document.getElementById("county").value, hazard = document.getElementById("hazard").value;
  const cLabel = Object.fromEntries(DATA.counties)[county], hLabel = Object.fromEntries(DATA.hazards)[hazard];
  if (!lazyReady("stress", "Stress tests – what could break")) return;
  const S = DATA.stress;
  app.replaceChildren();
  const byId = new Map(S.rows.map((r) => [r[0], r]));
  const topIds = S.top[county][STRESS.hazardOnly ? hazard : "all"] || [];
  const all = S.rows.filter((r) => inCounty(r, county) && (!STRESS.hazardOnly || r[4].split("+").some((x) => x === hazard || x === "all")))
    .sort((a, b) => a[6] - b[6]);
  const only = el("input", { type: "checkbox", id: "stress-hazard" });
  only.checked = STRESS.hazardOnly;
  only.addEventListener("change", () => { STRESS.hazardOnly = only.checked; renderStress(); });
  const csv = el("button", { type: "button", class: "button" }, `Download the full list (CSV, ${fmt(all.length)} rows)`);
  csv.addEventListener("click", () => stressCsv(all, county));
  append(app,
    el("h2", { id: "stress" }, `Stress tests – what could break: ${cLabel}`),
    el("p", { class: "note" }, el("strong", null, `${S.label}. `),
      "Each test changes one thing in the plan – a site closes, two hazards strike together, a road is cut, more people come – and counts who is affected, from the plan's own data. ",
      S.method),
    el("p", null, `${fmt(S.tested[county])} tests ran for ${cLabel}; ${fmt(all.length)} affect someone or need county data. ${S.not_no_shelter}`),
    el("p", { id: "definition-15" }, el("strong", null, "Definition: "), S.definition_15),
    el("p", null, el("a", { class: "button", href: DATA.meta.annex[county] }, `⬇ ${cLabel} stress-test annex (PDF): every result with its numbers`)),
    el("label", { for: "stress-hazard", class: "check" }, only, ` Only tests for ${hLabel.toLowerCase()} (and all-hazard tests)`),
    el("h3", { id: "stress-top" }, `Top ${topIds.length} by people affected`),
    el("p", { class: "hint" }, `Ranked by people affected; at most ${S.per_test} from one test, so different risks show. Counts of facilities or households follow the people counts.`),
    el("ol", { class: "findings" }, topIds.map((id) => byId.get(id)).filter(Boolean).map((r) => findingCard(r, county, hazard))),
    el("details", { class: "areas", id: "stress-all" },
      el("summary", null, `Full list for ${cLabel} (${fmt(all.length)})`),
      table(`Every stress test result for ${cLabel}${STRESS.hazardOnly ? ` – ${hLabel}` : ""}, ranked by people affected`,
        ["Rank", "Test", "Scenario", "Hazard", "Result"],
        all.map((r) => [fmt(r[7]), r[1], r[2], hzName(r[4]), [stressHead(r), r[8] ? ` (${r[8]})` : ""]]), [0])),
    el("p", null, csv),
    el("h2", { id: "questions" }, "Questions for counties"),
    el("p", null, "These questions need county knowledge. The plan has no data for them, so it shows no numbers."),
    el("ol", { class: "questions" }, S.questions.map(([t, q]) => el("li", null, el("strong", null, `${t}: `), q))));
  showVersion();
}

/* ---------- What-if: the planner changes the inputs; the plan's formulas do the rest ---------- */
const WI = { key: null, inp: null };
const wiDefaults = (key) => window.WhatIf.defaults(DATA.whatif, key);
function wiUrl() {
  const q = new URLSearchParams();
  q.set("county", document.getElementById("county").value);
  q.set("hazard", document.getElementById("hazard").value);
  for (const [k, v] of Object.entries(window.WhatIf.toQuery(WI.inp, wiDefaults(WI.key)))) q.set(k, v);
  history.replaceState(null, "", `?${q.toString()}#whatif`);
}

/* slider and number field kept in step; both 44 px tall, labelled, with the plan value */
function wiField(id, label, unit, min, max, step, value, plan, onSet) {
  const range = el("input", { type: "range", id: `${id}-range`, min, max, step, value, "aria-describedby": `${id}-plan` });
  const box = el("input", { type: "number", id, name: id, min, max, step, value, inputmode: "decimal", "aria-describedby": `${id}-plan` });
  const set = (v, from) => {
    let n = Number(v);
    if (!Number.isFinite(n)) return;
    n = Math.min(max, Math.max(min, n));
    if (from !== range) range.value = n;
    if (from !== box) box.value = n;
    onSet(n);
  };
  range.addEventListener("input", () => set(range.value, range));
  box.addEventListener("change", () => set(box.value, box));
  return el("div", { class: "wi-field" },
    el("label", { for: id }, `${label} (${unit})`),
    el("div", { class: "wi-inputs" }, range, box),
    el("label", { for: `${id}-range`, class: "visually-hidden" }, `${label} slider`),
    el("small", { id: `${id}-plan` }, plan));
}

function wiResults(county, hazard) {
  const W = DATA.whatif, key = `${county}|${hazard}`, a = W.scenarios[key], inp = WI.inp;
  const r = window.WhatIf.compute(W, key, inp);
  const sc = DATA.scenarios[key];
  const sites = DATA.sites.filter((x) => x.county === county);
  const areas = DATA.tracts.filter((t) => t.c === county && t.f in sc.tracts)
    .map((t) => ({ f: t.f, island: t.i || "", people: sc.tracts[t.f][1], a: t.a || [], t }));
  const al = window.WhatIf.allocate(areas, sites.map((x) => ({ id: x.id, island: x.island,
    usable: x.lon !== null && (x.status[hazard] || [""])[0] === "ok" })), inp, a.rate);
  const H = W.how, name = Object.fromEntries(sites.map((x) => [x.id, x.name]));
  const how = (k) => el("details", { class: "how" }, el("summary", null, "How this is calculated"), el("p", null, H[k]));
  const stayW = `${fmt(inp.stay)} ${inp.stay === 1 ? "day" : "days"}`;
  const rows = [
    ["People who may need a public shelter", fmt(r.people_in_shelter), "people", how("people_in_shelter")],
    ["Cots", fmt(r.cots), "cots", how("cots")],
    ["Floor space", fmt(r.floor_sqft), `sq ft (${r.floor_basis === "72h" ? "stays up to 3 days" : "longer stays"})`, how("floor_sqft")],
    ["Water", `${fmt(r.water_per_day)} a day · ${fmt(r.water_total)} for ${stayW}`, "gallons", how("water")],
    ["Meals", `${fmt(r.meals_per_day)} a day · ${fmt(r.meals_total)} for ${stayW}`, "meals", how("meals")],
    ["Toilets", fmt(r.toilets), "toilets", how("toilets")],
    ["Power outlets", inp.outage > 0 ? `${fmt(r.outlets_per_day)} a day · ${fmt(r.charge_point_days)} charge-point days over ${fmt(inp.outage)} days` : fmt(r.outlets_per_day), "outlets", how("outlets")],
    ["People in shelter needing support", fmt(r.support_people), "people", how("support")],
    ["Vehicle trips for residents without a car", `${fmt(r.trips)} (${fmt(r.transport_people)} people ÷ ${fmt(inp.trip)} per trip)`, "trips", how("trips")],
    ["Households with a dog · with a cat", `${fmt(r.dog_households)} · ${fmt(r.cat_households)}`, "households", how("pets")],
    ["Shelter staff per shift (all roles)", fmt(r.staff_total), "staff", how("staff")],
  ];
  const known = al.sites.filter((x) => x.cap !== null);
  const capLine = known.length
    ? el("p", { id: "wi-shortfall" }, el("strong", null, `Sites over capacity: ${fmt(al.over_sites)} of ${fmt(known.length)} with a capacity entered; shortfall ${fmt(al.shortfall)} people.`))
    : el("p", { id: "wi-shortfall" }, "Capacity unknown: enter a capacity for a site to see whether it is over capacity.");
  const trips = (t) => {
    const share = t.t.n[0] ? sc.tracts[t.f][0] / t.t.n[0] : 0;
    return t.t.n[5] * share;
  };
  return [
    el("p", { class: "note" }, el("strong", null, `${W.label}. `), `${Object.fromEntries(DATA.counties)[county]} – ${Object.fromEntries(DATA.hazards)[hazard]}. Planning factors and data are the plan's; only the inputs above change.`),
    el("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": "What-if results" },
      el("table", null, el("caption", null, "What-if results (county total, upper bound: every risk area hit at once)"),
        el("thead", null, el("tr", null, ["Output", "Number", "Unit", "How"].map((h, i) => el("th", { scope: "col", class: i === 1 ? "num" : null }, h)))),
        el("tbody", null, rows.map(([k, v, u, d]) => el("tr", null, el("th", { scope: "row" }, k), el("td", { class: "num" }, v), el("td", null, u), el("td", null, d)))))),
    table("Shelter staff per role, per shift", ["Role", "Staff"], Object.entries(r.staff).map(([k, v]) => [W.staff_labels[k] || k, fmt(v)]), [1]),
    table("People with limited English in shelter, by language (each may need an interpreter)", ["Language", "People"], r.interpreters.map(([l, n]) => [l, fmt(n)]), [1]),
    how("interpreters"),
    el("h3", { id: "wi-sites" }, "People by nearest usable site (same island, by drive time)"),
    table("Allocation to the nearest usable 2026 site", ["Site", "People in shelter", "Capacity entered", "Over capacity"],
      al.sites.map((x) => [name[x.id], fmt(x.load), x.cap === null ? "unknown" : fmt(x.cap), x.over === null ? "–" : fmt(x.over)]), [1, 2, 3]),
    capLine, how("allocation"),
    al.unassigned > 0 ? el("p", { class: "note", id: "wi-unassigned" }, `${fmt(al.unassigned)} people live in Census areas with no known usable 2026 site on their island for this hazard. ${DATA.meta.no_island_site}`) : null,
    el("details", { class: "areas", id: "wi-areas" }, el("summary", null, `By Census area (${fmt(al.areas.length)})`),
      table("People in shelter by Census area and their nearest usable site", ["Census area", "People in shelter", "Nearest usable site", "Drive", "People without a car", "Vehicle trips"],
        al.areas.map((x, i) => {
          const nc = trips(areas[i]);
          return [areas[i].t.l || x.f, fmt(x.people), x.site === null ? "none on this island" : name[x.site],
            x.drive === null ? "–" : `${Math.round(x.drive)} min`, fmt(nc), fmt(Math.ceil(nc / inp.trip))];
        }), [1, 3, 4, 5]),
      el("p", { class: "hint" }, "Per-area numbers are rounded; the county totals above use the plan's exact sums.")),
  ];
}

function renderWhatIf() {
  const app = document.getElementById("app");
  const county = document.getElementById("county").value, hazard = document.getElementById("hazard").value;
  if (!lazyReady("whatif", "What-if: change the planning numbers")) return;
  const W = DATA.whatif;
  app.replaceChildren();
  if (!W || !window.WhatIf) { append(app, el("h2", { id: "whatif" }, "What-if"), el("p", null, "The what-if panel is not in this data version.")); return; }
  const key = `${county}|${hazard}`, a = W.scenarios[key], d = wiDefaults(key), L = W.limits;
  if (WI.key !== key) {
    const q = new URLSearchParams(location.search);
    const same = q.get("county") === county && q.get("hazard") === hazard;
    WI.inp = same ? window.WhatIf.fromQuery((k) => q.get(k), d, L) : d;
    WI.key = key;
  }
  const inp = WI.inp;
  const out = el("div", { id: "wi-out" });
  const live = el("p", { class: "visually-hidden", role: "status", "aria-live": "polite", id: "wi-live" });
  const update = () => {
    out.replaceChildren(...wiResults(county, hazard).filter(Boolean));
    const r = window.WhatIf.compute(W, key, WI.inp);
    live.textContent = `Updated: ${fmt(r.people_in_shelter)} people may need a public shelter.`;
    wiUrl();
  };
  const pct1 = (v) => Math.round(v * 1000) / 10;
  const planShare = pct1(a.demand ? a.disability_in_shelter / a.demand : 0);
  const sites = DATA.sites.filter((x) => x.county === county && x.lon !== null && (x.status[hazard] || [""])[0] === "ok");
  const capNote = el("p", { id: "wi-cap-note", role: "status" });
  const capBoxes = sites.map((x) => {
    const id = `cap-${x.id}`;
    const box = el("input", { type: "number", id, name: id, min: 0, step: 1, inputmode: "numeric", placeholder: "unknown",
      value: inp.cap[x.id] === undefined ? null : inp.cap[x.id] });
    box.addEventListener("change", () => {
      const v = box.value === "" ? NaN : Math.round(Number(box.value));
      if (Number.isFinite(v) && v >= 0) inp.cap[x.id] = v; else { delete inp.cap[x.id]; box.value = ""; }
      update();
    });
    return el("div", { class: "wi-cap" }, el("label", { for: id }, x.name), box);
  });
  const load = el("button", { type: "button", class: "button" }, "Load 2009 reference capacity (may be outdated)");
  load.addEventListener("click", () => {
    let n = 0;
    for (const x of sites) {
      const ref = (DATA.hub.pdc_sites || {})[String(x.id)];
      if (!ref) continue;
      inp.cap[x.id] = ref[0]; n += 1;
      document.getElementById(`cap-${x.id}`).value = ref[0];
    }
    capNote.textContent = `Loaded the 2009 reference capacity for ${fmt(n)} of ${fmt(sites.length)} usable sites. ${DATA.hub.pdc_note} Sites without a 2009 match stay unknown.`;
    update();
  });
  const reset = el("button", { type: "button", class: "button" }, "Reset to plan defaults");
  reset.addEventListener("click", () => { WI.inp = wiDefaults(key); WI.key = null; history.replaceState(null, "", `?county=${county}&hazard=${hazard}#whatif`); WI.key = key; renderWhatIf(); document.getElementById("whatif").focus(); });
  const csv = el("button", { type: "button", class: "button" }, "Download results (CSV)");
  csv.addEventListener("click", () => {
    const r = window.WhatIf.compute(W, key, WI.inp), sc = DATA.scenarios[key];
    const rows = [["What-if, not a forecast", `${county} – ${hazard}`], ["Input", "Value"],
      ["Shelter-seeking rate (%)", pct1(WI.inp.rate)], ["Stay (days)", WI.inp.stay], ["Power outage (days)", WI.inp.outage],
      ["People per vehicle trip", WI.inp.trip], ["Share needing support (%)", WI.inp.support === null ? `plan (${planShare})` : pct1(WI.inp.support)],
      [], ["Output", "Number"], ["People who may need a public shelter", r.people_in_shelter], ["Cots", r.cots], ["Floor space (sq ft)", r.floor_sqft],
      ["Water per day (gal)", r.water_per_day], ["Water for the stay (gal)", r.water_total], ["Meals per day", r.meals_per_day], ["Meals for the stay", r.meals_total],
      ["Toilets", r.toilets], ["Power outlets per day", r.outlets_per_day], ["Charge-point days", r.charge_point_days], ["People needing support", r.support_people],
      ["Vehicle trips", r.trips], ["Households with a dog", r.dog_households], ["Households with a cat", r.cat_households], ["Staff per shift", r.staff_total],
      ...Object.entries(r.staff).map(([k, v]) => [`Staff – ${W.staff_labels[k] || k}`, v]),
      ...r.interpreters.map(([l, n]) => [`People with limited English – ${l}`, n]), [], ["Census area", "People in shelter", "Nearest usable site", "Drive (min)"]];
    const sites2 = DATA.sites.filter((x) => x.county === county);
    const al = window.WhatIf.allocate(DATA.tracts.filter((t) => t.c === county && t.f in sc.tracts).map((t) => ({ f: t.f, island: t.i || "", people: sc.tracts[t.f][1], a: t.a || [] })),
      sites2.map((x) => ({ id: x.id, island: x.island, usable: x.lon !== null && (x.status[hazard] || [""])[0] === "ok" })), WI.inp, a.rate);
    const nm = Object.fromEntries(sites2.map((x) => [x.id, x.name])), lab = Object.fromEntries(DATA.tracts.map((t) => [t.f, t.l || t.f]));
    for (const x of al.areas) rows.push([lab[x.f], Math.round(x.people * 10) / 10, x.site === null ? "none on this island" : nm[x.site], x.drive === null ? "" : Math.round(x.drive)]);
    downloadCsv(`what-if-${county.toLowerCase()}-${hazard}.csv`, rows);
  });
  const print = el("button", { type: "button", class: "button" }, "Print");
  print.addEventListener("click", () => window.print());
  const onSet = (k, scale) => (v) => { WI.inp[k] = scale ? v / 100 : v; update(); };
  append(app,
    el("h2", { id: "whatif", tabindex: "-1" }, "What-if: change the planning numbers"),
    el("p", { class: "note" }, el("strong", null, `${W.label}. `), "Change an input to see what the plan would need. Defaults are the plan's own values. Nothing is stored: the inputs are kept only in this page's address, so you can bookmark or share it."),
    el("form", { class: "wi-form", "aria-label": "What-if inputs" },
      el("fieldset", null, el("legend", null, "Inputs"),
        wiField("wi-rate", "Shelter-seeking rate", "% of people in the risk area", L.rate[0] * 100, L.rate[1] * 100, 0.5, pct1(inp.rate),
          `Plan: ${pct1(a.rate)}% (likely rate for this hazard).`, onSet("rate", true)),
        wiField("wi-stay", "Length of stay", "days", L.stay[0], L.stay[1], 1, inp.stay, `Plan: ${d.stay} days (${W.assumptions.stay}).`, onSet("stay")),
        wiField("wi-outage", "Power outage", "days", L.outage[0], L.outage[1], 1, inp.outage, `Plan: ${d.outage} days (${W.assumptions.outage}).`, onSet("outage")),
        wiField("wi-trip", "People per vehicle trip", "people", L.trip[0], L.trip[1], 1, inp.trip, `Default: ${W.assumptions.people_per_trip}.`, onSet("trip")),
        wiField("wi-support", "Share needing support in shelter", "% of people in shelter", L.support[0] * 100, L.support[1] * 100, 0.5,
          inp.support === null ? Math.min(planShare, L.support[1] * 100) : pct1(inp.support),
          `Plan: ${planShare}% (people in shelter with a disability).`, onSet("support", true))),
      el("fieldset", null, el("legend", null, "Site capacity (people) – blank means unknown"),
        sites.length ? capBoxes : el("p", null, "No usable 2026 site for this hazard in this county."),
        sites.length ? el("p", null, load) : null, capNote,
        el("p", { class: "hint" }, `${DATA.hub.pdc_note} ${fmt(DATA.hub.pdc_schools)} DOE schools also have a 2009 reference capacity; they are not 2026 sites, so they are not used here.`)),
      el("p", { class: "panel-actions" }, reset, " ", csv, " ", print)),
    live, out);
  app.querySelector(".wi-form").addEventListener("submit", (e) => e.preventDefault());
  update();
  showVersion();
}

