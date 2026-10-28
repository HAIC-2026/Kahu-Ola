/* Hawaiʻi ESF-6 Planning – offline app.
   Kahu Ola Invariant I: the user chooses the hazard. This app makes NO calls to NWS or any
   upstream API; the only request is the local, pre-cached data bundle (data/bundle.json).
   No login, no analytics, no tracking, no location access. */
"use strict";

const BUNDLE_URL = "data/bundle.json";
const SVG_NS = "http://www.w3.org/2000/svg";
const RAMP = ["--ramp-1", "--ramp-2", "--ramp-3", "--ramp-4", "--ramp-5"];
const MARKERS = {
  "ok": ["circle", "Usable"],
  "check": ["triangle", "Check: flood (SFHA)"],
  "check (tract-level)": ["triangle", "Check: flood (tract-level)"],
  "undetermined": ["diamond", "Flood risk undetermined (zone D)"],
  "exclude": ["square", "Excluded: tsunami zone"],
};
const STATUS_ORDER = ["ok", "check", "check (tract-level)", "undetermined", "exclude", "unlocated"];
const MAIN_ISLANDS_WEST = -160.6;

let DATA = null;

/* ---------- small DOM helpers (textContent only: no HTML injection) ---------- */
function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined) continue;
    if (k === "class") e.className = v; else e.setAttribute(k, v);
  }
  for (const k of kids.flat()) {
    if (k === null || k === undefined) continue;
    e.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
  return e;
}
function svg(tag, attrs) {
  const e = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
  return e;
}
const fmt = (v) => (v === null || v === undefined || v === "" ? "–" :
  typeof v === "number" ? Math.round(v).toLocaleString("en-US") : String(v));
const pct = (v, d = 0) => `${(v * 100).toFixed(d)}%`;
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function table(caption, headers, rows, numCols = []) {
  const head = el("tr", null, headers.map((h, i) =>
    el("th", { scope: "col", class: numCols.includes(i) ? "num" : null }, h)));
  const body = rows.map((r) => el("tr", null, r.map((c, i) =>
    el("td", { class: numCols.includes(i) ? "num" : null }, c))));
  return el("div", { class: "table-wrap" },
    el("table", null, el("caption", null, caption), el("thead", null, head), el("tbody", null, body)));
}

/* ---------- offline banner ---------- */
function updateBanner() {
  const b = document.getElementById("offline");
  const asOf = DATA ? DATA.meta.data_as_of : "last download";
  b.textContent = `Offline – data as of ${asOf}`;
  b.hidden = navigator.onLine;
}

/* ---------- map ---------- */
function projection(bbox, w, h, pad = 8) {
  const [minx, miny, maxx, maxy] = bbox;
  const k = Math.cos(((miny + maxy) / 2) * Math.PI / 180);
  const bw = Math.max((maxx - minx) * k, 1e-6), bh = Math.max(maxy - miny, 1e-6);
  const s = Math.min((w - 2 * pad) / bw, (h - 2 * pad) / bh);
  const ox = pad + ((w - 2 * pad) - bw * s) / 2, oy = pad + ((h - 2 * pad) - bh * s) / 2;
  return (x, y) => [+(ox + (x - minx) * k * s).toFixed(1), +(oy + (maxy - y) * s).toFixed(1)];
}

function quantiles(values, n = 5) {
  const v = values.filter((x) => x > 0).sort((a, b) => a - b);
  if (!v.length) return [];
  return Array.from({ length: n }, (_, i) => v[Math.min(v.length - 1, Math.ceil(v.length * (i + 1) / n) - 1)]);
}

function markerShape(shape, x, y, r = 7) {
  const st = { fill: "#ffffff", stroke: "#000000", "stroke-width": "2" };
  const g = svg("g");
  if (shape === "circle") g.append(svg("circle", { cx: x, cy: y, r, ...st }));
  else if (shape === "triangle") g.append(svg("polygon", { points: `${x},${y - r * 1.2} ${x + r * 1.1},${y + r * 0.8} ${x - r * 1.1},${y + r * 0.8}`, ...st }));
  else if (shape === "diamond") g.append(svg("polygon", { points: `${x},${y - r * 1.2} ${x + r * 1.2},${y} ${x},${y + r * 1.2} ${x - r * 1.2},${y}`, ...st }));
  else {
    g.append(svg("rect", { x: x - r, y: y - r, width: 2 * r, height: 2 * r, ...st }));
    g.append(svg("path", { d: `M${x - r},${y - r} L${x + r},${y + r} M${x + r},${y - r} L${x - r},${y + r}`, stroke: "#000000", "stroke-width": "1.5" }));
  }
  return g;
}

function renderMap(county, sc, sites, title) {
  const W = 720, H = 520;
  const tracts = DATA.tracts.filter((t) => t.c === county);
  let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
  for (const t of tracts) for (const r of t.g) for (let i = 0; i < r.length; i += 2) {
    if (r[i] < MAIN_ISLANDS_WEST) continue;
    minx = Math.min(minx, r[i]); maxx = Math.max(maxx, r[i]);
    miny = Math.min(miny, r[i + 1]); maxy = Math.max(maxy, r[i + 1]);
  }
  const proj = projection([minx, miny, maxx, maxy], W, H);
  const afn = Object.fromEntries(Object.entries(sc.tracts).map(([f, v]) => [f, v[2]]));
  const bounds = quantiles(Object.values(afn));
  const cls = (v) => bounds.findIndex((b) => v <= b);

  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-labelledby": "map-title" });
  const t = svg("title", { id: "map-title" }); t.textContent = title; root.append(t);
  root.append(svg("rect", { width: W, height: H, fill: "#ffffff" }));
  for (const tr of tracts) {
    const d = tr.g.map((r) => {
      const pts = [];
      for (let i = 0; i < r.length; i += 2) pts.push(proj(r[i], r[i + 1]).join(","));
      return "M" + pts.join(" L") + " Z";
    }).join(" ");
    const risk = tr.f in sc.tracts;
    const fill = risk && afn[tr.f] > 0 ? css(RAMP[cls(afn[tr.f])]) : "#ffffff";
    const path = svg("path", risk
      ? { d, fill, stroke: "#000000", "stroke-width": "1.4" }
      : { d, fill, stroke: "#9a9a9a", "stroke-width": "0.5", "stroke-dasharray": "2,2" });
    const tip = svg("title"); tip.textContent = tr.l || tr.f; path.append(tip);   // hover tooltip
    root.append(path);
  }
  for (const s of sites) {
    if (s.lon === null) continue;
    const [x, y] = proj(s.lon, s.lat);
    root.append(markerShape((MARKERS[s.st] || MARKERS.ok)[0], x, y));
    const lab = svg("text", { x: x + 10, y: y + 4, "font-size": "13", "font-weight": "bold",
      stroke: "#ffffff", "stroke-width": "3", "paint-order": "stroke" });
    lab.textContent = s.n; root.append(lab);
  }

  const legend = el("ul", { class: "legend", "aria-label": "Map legend" });
  let lo = 0;
  bounds.forEach((b, i) => {
    const sw = svg("svg", { width: 28, height: 16, "aria-hidden": "true" });
    sw.append(svg("rect", { width: 28, height: 16, fill: css(RAMP[i]), stroke: "#000" }));
    legend.append(el("li", null, sw, `AFN need ${fmt(lo)}–${fmt(b)} people (class ${i + 1} of ${bounds.length})`));
    lo = b;
  });
  const outline = (dashed, text) => {
    const sw = svg("svg", { width: 28, height: 16, "aria-hidden": "true" });
    sw.append(svg("rect", dashed ? { width: 28, height: 16, fill: "#fff", stroke: "#9a9a9a", "stroke-dasharray": "2,2" }
      : { width: 28, height: 16, fill: "#fff", stroke: "#000", "stroke-width": "2" }));
    return el("li", null, sw, text);
  };
  legend.append(outline(false, "Solid outline: tract in hazard footprint (at risk)"));
  legend.append(outline(true, "Dashed outline: not in footprint"));
  const seen = new Set();
  for (const [shape, label] of Object.values(MARKERS)) {
    if (seen.has(label)) continue; seen.add(label);
    const sw = svg("svg", { width: 28, height: 22, "aria-hidden": "true" });
    sw.append(markerShape(shape, 14, 11, 6));
    legend.append(el("li", null, sw, label));
  }
  return [el("div", { class: "map" }, root), legend];
}

/* ---------- views ---------- */
function render() {
  const county = document.getElementById("county").value;
  const hazard = document.getElementById("hazard").value;
  const sc = DATA.scenarios[`${county}|${hazard}`];
  const cLabel = Object.fromEntries(DATA.counties)[county];
  const hLabel = Object.fromEntries(DATA.hazards)[hazard];
  const s = sc.summary;
  const app = document.getElementById("app");
  app.replaceChildren();

  // sites for this county/hazard, numbered like the playbook
  const sites = DATA.sites.filter((x) => x.county === county).map((x) => ({
    ...x, st: x.status[hazard] ? x.status[hazard][0] : "unlocated",
    why: x.status[hazard] ? x.status[hazard][1] : "not located – not on map",
  })).sort((a, b) => STATUS_ORDER.indexOf(a.st) - STATUS_ORDER.indexOf(b.st) || a.name.localeCompare(b.name));
  sites.forEach((x, i) => { x.n = i + 1; });

  const kpis = [
    ["People at risk", fmt(s.at_risk_pop)],
    ["Shelter demand (central)", fmt(s.shelter_demand_central)],
    ["Shelter demand low – high", `${fmt(s.shelter_demand_low)} – ${fmt(s.shelter_demand_high)}`],
    ["Limited English (C)", fmt(s.C_lep_at_risk)],
    ["Power-dependent (M)", fmt(s.M_power_dependent_at_risk)],
    ["Disability (I)", fmt(s.I_disability_at_risk)],
    ["Age 65+ (I)", fmt(s.I_age65_at_risk)],
    ["People without a vehicle (T)", fmt(s.T_no_vehicle_persons_at_risk)],
    ["Known 2026 sites usable", fmt(s.known_sites_usable)],
  ];
  if (hazard === "tsunami") kpis.push(["At risk, extreme tsunami zone (worst case)", fmt(s.at_risk_pop_extreme_zone)]);

  const L = DATA.languages[county];
  app.append(
    el("h2", { id: "summary" }, `${cLabel} – ${hLabel}`),
    el("p", null, el("strong", null, `Data as of ${DATA.meta.data_as_of}. `), DATA.meta.disclaimer),
    el("p", null, el("a", { class: "button", href: sc.playbook }, `⬇ Printable playbook (PDF): ${cLabel} – ${hLabel}`)),
    el("ul", { class: "kpis" }, kpis.map(([k, v]) => el("li", null, k, el("b", null, v)))),
    el("p", null, `Shelter-seeking rates: low ${pct(s.rate_low)}, central ${pct(s.rate_central)}, high ${pct(s.rate_high, 1)}. One person can appear in more than one CMIST count.`),

    el("h2", null, "Scope: county total vs. one community"),
    el("p", { class: "note" }, el("strong", null, "County total = upper bound. "),
      `It assumes every at-risk tract is hit at once (${s.footprint_rule}). Real events usually hit fewer communities.`),
    table(hazard === "hurricane"
      ? ["Largest single community (highest-demand census tracts)", el("br"),
         el("span", { class: "caption-note" }, DATA.meta.hurricane_scope_note)]
      : "Largest single community (highest-demand census tracts)",
      ["Tract", "At risk", "Shelter low / central / high", "Limited English", "Power-dep.", "Disability", "65+", "No vehicle"],
      sc.largest.map((c) => [c.tract_label || c.tract_fips, fmt(c.at_risk_pop), `${fmt(c.low)} / ${fmt(c.central)} / ${fmt(c.high)}`,
        fmt(c.C_lep_at_risk), fmt(c.M_power_dependent_at_risk), fmt(c.I_disability_at_risk), fmt(c.I_age65_at_risk),
        fmt(c.T_no_vehicle_persons_at_risk)]), [1, 2, 3, 4, 5, 6, 7]),

    el("h2", null, "Map: AFN need and known sites"),
    ...renderMap(county, sc, sites, `${cLabel} ${hLabel}: AFN need by census tract and known shelter sites`),
    el("p", null, "AFN need = power-dependent + disability + limited English + no-vehicle people at risk. Marker numbers match the sites table. Tract outlines only, no basemap."),

    el("h2", null, "Known sites (opened in 2026 events)"),
    table("Sites with status for this hazard", ["#", "Status", "Site", "Address", "Reason", "Times opened 2026"],
      sites.map((x) => [x.n, el("span", { class: "status" }, DATA.status_labels[x.st] || "Not located"), x.name, x.address, x.why, x.times_opened_2026]), [0, 5]),
    el("p", null, `Candidate public schools usable for this hazard: ${fmt(s.candidate_schools_usable)}. Not every site opens in every event; follow current county announcements.`),

    el("h2", null, "Needs and proposed partners"),
    el("p", null, DATA.meta.role_status, " Pledged capacity stays blank until a partner confirms it."),
    table("Needs (central estimate)", ["Need", "Quantity", "Unit", "Proposed lead", "Proposed support", "Pledged", "Gap"],
      sc.needs.map((n) => [n[0], fmt(n[1]), n[2], n[3], n[4].replaceAll("; ", ", "), n[5] === "" ? "—" : fmt(n[5]), n[6]]), [1]),

    el("h2", null, "Decision points"),
    el("p", { class: "note" }, DATA.meta.decision_status),
    table("Before, during and after", ["When", "Trigger", "Action", "Owner (proposed)", "Support"],
      DATA.decision_points[hazard].map((d) => [el("strong", null, d[0].toUpperCase()), `${d[1]} (${d[2]})`, d[3], d[4], d[5].replaceAll("; ", ", ")])),

    el("h2", null, "Priority outreach and languages"),
    table("Top 10 census tracts by AFN need (tract-level counts only)",
      ["#", "Tract", "At risk", "Power-dep.", "Disability", "Limited English", "No vehicle", "AFN need"],
      sc.priority_tracts.map((t) => [t.rank, t.tract_label || t.tract_fips, fmt(t.at_risk_pop), fmt(t.power_dependent), fmt(t.disability),
        fmt(t.limited_english), fmt(t.no_vehicle), fmt(t.afn_need_sum)]), [0, 2, 3, 4, 5, 6, 7]),
    L.note ? el("p", null, L.note) : null,
    table(`People who speak English less than "very well" (${L.area}; ACS PUMS 2019-2023)`, ["Language", "People 5+", "90% MOE"],
      L.rows.map((r) => [r[0], fmt(r[1]), `±${fmt(r[2])}`]), [1, 2]),
    el("p", null, DATA.meta.privacy),
  );
  document.getElementById("version").textContent = `Data version ${DATA.meta.version} · data as of ${DATA.meta.data_as_of}`;
}

function fillSelect(id, pairs) {
  const s = document.getElementById(id);
  s.replaceChildren(...pairs.map(([v, label]) => el("option", { value: v }, label)));
}

async function init() {
  window.addEventListener("online", updateBanner);
  window.addEventListener("offline", updateBanner);
  updateBanner();
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(() => { /* app still works online */ });
  }
  try {
    const res = await fetch(BUNDLE_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    DATA = await res.json();
  } catch (err) {
    const fb = document.getElementById("fallback");
    fb.querySelector("h2").textContent = "Planning data could not be loaded";
    fb.querySelector("p").textContent = "The printable playbooks below work on their own.";
    fb.prepend(el("p", { class: "note warn", role: "alert" },
      "The interactive view is unavailable right now. The printable playbooks below still work."));
    return;
  }
  fillSelect("county", DATA.counties);
  fillSelect("hazard", DATA.hazards);
  document.getElementById("controls").hidden = false;
  document.getElementById("controls").addEventListener("change", render);
  document.getElementById("controls").addEventListener("submit", (e) => e.preventDefault());
  document.getElementById("fallback").hidden = true;
  document.getElementById("app").hidden = false;
  updateBanner();
  render();
}

init();
