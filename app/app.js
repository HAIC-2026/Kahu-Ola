/* Hawaiʻi ESF-6 Planning – offline app.
   Kahu Ola Invariant I: the user chooses the hazard. This app makes NO calls to NWS or any
   upstream API; the only requests are the local, pre-cached data bundle (data/bundle.json)
   and, when online, the small same-origin data/version.json to spot newer planning data.
   No login, no analytics, no tracking, no location access. */
"use strict";

const BUNDLE_URL = "data/bundle.json";
const VERSION_URL = "data/version.json";
const SVG_NS = "http://www.w3.org/2000/svg";
const RAMP = ["--ramp-1", "--ramp-2", "--ramp-3", "--ramp-4", "--ramp-5"];
const MARKERS = {
  "ok": ["circle", "Usable site"],
  "check": ["triangle", "Check flood zone"],
  "check (tract-level)": ["triangle", "Check flood zone"],
  "undetermined": ["diamond", "Flood risk not mapped (FEMA zone D)"],
  "exclude": ["square", "Not for this hazard"],
};
/* care facilities (CMS): filled black shapes, distinct from the white site markers */
const FACILITY = {
  "dialysis": ["hexagon", "Dialysis facility"],
  "nursing_home": ["house", "Nursing home"],
  "hospital": ["cross", "Hospital"],
  "childcare": ["star", "Childcare centre"],
};
const LAYERS = { outside: true, care: true, sirens: false, safe: true, fire: false, flooded: true };   // map layer checkboxes (kept across views)
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
/* append only real nodes or text: skips null, undefined and false (never shows "null") */
function append(parent, ...items) {
  parent.append(...items.flat(Infinity).filter((x) => x !== null && x !== undefined && x !== false));
  return parent;
}
function svg(tag, attrs) {
  const e = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs || {})) e.setAttribute(k, v);
  return e;
}
const fmt = (v) => (v === null || v === undefined || v === "" ? "–" :
  typeof v === "number" ? Math.round(v).toLocaleString("en-US") : String(v));
/* percent with a decimal only when needed: 0.112 -> "11.2%", 0.11 -> "11%" */
const pct = (v) => {
  const p = Math.round(v * 1000) / 10;
  return Number.isInteger(p) ? `${p}%` : `${p.toFixed(1)}%`;
};
const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
/* keep a date, "140 – 349 – 781" or "Census area 314.05" on one line on phones:
   dates become <time datetime class="nowrap">, the rest <span class="nowrap">; the text is unchanged */
const KEEP = /(\d{4}-\d{2}-\d{2})|(\d[\d,.]*(?: ?– ?\d[\d,.]*)+|Census area \d+(?:\.\d+)?)/g;
const keep = (text) => String(text).split(KEEP).map((part, i) => (part === undefined || part === "" ? null
  : i % 3 === 1 ? el("time", { datetime: part, class: "nowrap" }, part)
  : i % 3 === 2 ? el("span", { class: "nowrap" }, part) : part)).filter((x) => x !== null);

function table(caption, headers, rows, numCols = []) {
  const head = el("tr", null, headers.map((h, i) =>
    el("th", { scope: "col", class: numCols.includes(i) ? "num" : null }, h)));
  const body = rows.map((r) => el("tr", null, r.map((c, i) =>
    el("td", { class: numCols.includes(i) ? "num" : null }, typeof c === "string" ? keep(c) : c))));
  const name = Array.isArray(caption) ? caption[0] : caption;
  return el("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": name },
    el("table", null, el("caption", null, caption), el("thead", null, head), el("tbody", null, body)));
}

/* ---------- offline banner ---------- */
function updateBanner() {
  const b = document.getElementById("offline");
  const asOf = DATA ? DATA.meta.data_as_of : "last download";
  b.replaceChildren(...keep(`Offline – data as of ${asOf}`));
  b.hidden = navigator.onLine;
}

/* ---------- data version and update notice ---------- */
function showVersion() {
  const text = `Data version ${DATA.meta.version} · Data as of ${DATA.meta.data_as_of}`;
  document.getElementById("dataver").replaceChildren(...keep(text));
  document.getElementById("version").replaceChildren(...keep(text));
}

/* When online, compare the server's version.json (never from a cache) with the bundle
   this page is showing; offer a reload when newer planning data is published. */
async function checkForUpdate() {
  if (!DATA || !navigator.onLine) return;
  try {
    const res = await fetch(VERSION_URL, { cache: "no-store" });
    if (!res.ok) return;
    const latest = await res.json();
    if (latest.version && latest.version !== DATA.meta.version) showUpdate(latest);
  } catch (err) { /* offline or blocked: keep showing the cached data */ }
}

function showUpdate(latest) {
  const b = document.getElementById("update");
  const btn = el("button", { type: "button", class: "button" }, "Reload");
  btn.addEventListener("click", reloadWithNewData);
  b.replaceChildren(...keep(`New planning data available (data as of ${latest.data_as_of}) – `), btn);
  b.hidden = false;
}

/* Fetch the new service worker (its cache name is a hash of every file), wait for it to
   take over, then reload so the page reads the new bundle from the new cache. */
async function reloadWithNewData() {
  try {
    const reg = "serviceWorker" in navigator ? await navigator.serviceWorker.getRegistration() : null;
    if (reg) {
      await reg.update();
      const w = reg.installing || reg.waiting;
      if (w && w.state !== "activated") {
        await new Promise((done) => {
          w.addEventListener("statechange", () => { if (w.state === "activated") done(); });
          setTimeout(done, 15000);
        });
      }
    }
  } catch (err) { /* reload anyway */ }
  location.reload();
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

function facilityShape(shape, x, y, r = 5) {
  const st = { fill: "#000000", stroke: "#ffffff", "stroke-width": "1.5" };
  const g = svg("g");
  if (shape === "hexagon") {
    const pts = Array.from({ length: 6 }, (_, i) => {
      const a = Math.PI / 3 * i;
      return `${(x + r * 1.15 * Math.cos(a)).toFixed(1)},${(y + r * 1.15 * Math.sin(a)).toFixed(1)}`;
    });
    g.append(svg("polygon", { points: pts.join(" "), ...st }));
  } else if (shape === "house") {
    g.append(svg("polygon", { points: `${x},${y - r * 1.3} ${x + r * 1.1},${y - r * 0.2} ${x + r * 1.1},${y + r} ${x - r * 1.1},${y + r} ${x - r * 1.1},${y - r * 0.2}`, ...st }));
  } else if (shape === "star") {
    const pts = Array.from({ length: 10 }, (_, i) => {
      const a = -Math.PI / 2 + Math.PI / 5 * i, k = i % 2 ? r * 0.6 : r * 1.4;
      return `${(x + k * Math.cos(a)).toFixed(1)},${(y + k * Math.sin(a)).toFixed(1)}`;
    });
    g.append(svg("polygon", { points: pts.join(" "), ...st }));
  } else {
    const a = r * 0.45, b = r * 1.2;
    g.append(svg("polygon", { points: `${x - a},${y - b} ${x + a},${y - b} ${x + a},${y - a} ${x + b},${y - a} ${x + b},${y + a} ${x + a},${y + a} ${x + a},${y + b} ${x - a},${y + b} ${x - a},${y + a} ${x - b},${y + a} ${x - b},${y - a} ${x - a},${y - a}`, ...st }));
  }
  return g;
}

/* the zone a care facility is in for this hazard ("" = outside it, null = no screen) */
const ZONE_HAZARDS = ["tsunami", "inland_flood", "coastal_flood"];
const facilityZone = (f, hazard) => (ZONE_HAZARDS.includes(hazard) ? (f.z[hazard] || "") : null);
const hasAccess = () => Boolean(DATA.access && DATA.access.source);
const hasState = () => Boolean(DATA.state && DATA.state.sirens);

/* ---------- map: Census areas, sites, tsunami zone; click or Enter opens an area ---------- */
const MAP = {};                       // state of the map on screen (one at a time)
const REDUCED = () => window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function renderMap(county, sc, sites, title, hazard) {
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
  const names = needNames(bounds.length);
  const level = (f) => (f in sc.tracts && afn[f] > 0 ? names[cls(afn[f])] : "Outside the risk area");
  const ringPath = (r) => {
    const pts = [];
    for (let i = 0; i < r.length; i += 2) pts.push(proj(r[i], r[i + 1]).join(","));
    return "M" + pts.join(" L") + " Z";
  };

  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-labelledby": "map-title", tabindex: "-1" });
  const t = svg("title", { id: "map-title" }); t.textContent = title; root.append(t);
  const defs = svg("defs");
  const hatch = svg("pattern", { id: "tsunami-hatch", width: 8, height: 8, patternUnits: "userSpaceOnUse", patternTransform: "rotate(45)" });
  hatch.append(svg("line", { x1: 0, y1: 0, x2: 0, y2: 8, stroke: "#000000", "stroke-width": "1.5" }));
  const hatch2 = svg("pattern", { id: "outside-hatch", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(90)" });
  hatch2.append(svg("line", { x1: 0, y1: 0, x2: 0, y2: 6, stroke: "#000000", "stroke-width": "1.2" }));
  defs.append(hatch, hatch2); root.append(defs);
  root.append(svg("rect", { width: W, height: H, fill: "#ffffff" }));
  const paths = {};
  for (const tr of tracts) {
    const d = tr.g.map(ringPath).join(" ");
    const risk = tr.f in sc.tracts;
    const fill = risk && afn[tr.f] > 0 ? css(RAMP[cls(afn[tr.f])]) : "#ffffff";
    const path = svg("path", risk
      ? { d, fill, stroke: "#000000", "stroke-width": "1.4", "vector-effect": "non-scaling-stroke", class: "area" }
      : { d, fill, stroke: "#9a9a9a", "stroke-width": "0.5", "stroke-dasharray": "2,2", "vector-effect": "non-scaling-stroke", class: "area" });
    const tip = svg("title"); tip.textContent = `${tr.l || tr.f} – ${level(tr.f)}${isLahaina(tr.l) ? ` – ${DATA.meta.lahaina_note}` : ""}`; path.append(tip);
    path.addEventListener("click", () => openArea(tr.f, null));
    paths[tr.f] = path;
    root.append(path);
  }
  // State tsunami evacuation zone (simplified outline, built in; shown for tsunami only)
  const zone = hazard === "tsunami" ? (DATA.tsunami_zone[county] || []) : [];
  if (zone.length) {
    root.append(svg("path", { d: zone.map(ringPath).join(" "), fill: "url(#tsunami-hatch)", "fill-opacity": "0.45",
      stroke: "#000000", "stroke-width": "1.2", "stroke-dasharray": "5,3", "vector-effect": "non-scaling-stroke",
      "pointer-events": "none", class: "tsunami-zone" }));
  }
  // State Hub layers (build time, simplified): Tsunami Safe Zones (tsunami view), State Fire
  // Risk Areas (wildfire view, a comparison layer), highways that may flood with 3.2 ft of sea
  // level rise (coastal flooding view). Patterns and line styles, not colour, tell them apart.
  const HUBD = DATA.hub || {};
  const linePath = (r) => {
    const pts = [];
    for (let i = 0; i < r.length; i += 2) pts.push(proj(r[i], r[i + 1]).join(","));
    return "M" + pts.join(" L");
  };
  const dots = svg("pattern", { id: "safe-dots", width: 7, height: 7, patternUnits: "userSpaceOnUse" });
  dots.append(svg("circle", { cx: 3.5, cy: 3.5, r: 1.3, fill: "#000000" }));
  const fireHi = svg("pattern", { id: "fire-high", width: 6, height: 6, patternUnits: "userSpaceOnUse", patternTransform: "rotate(-45)" });
  fireHi.append(svg("line", { x1: 0, y1: 0, x2: 0, y2: 6, stroke: "#000000", "stroke-width": "1.6" }));
  const fireMed = svg("pattern", { id: "fire-med", width: 14, height: 14, patternUnits: "userSpaceOnUse", patternTransform: "rotate(-45)" });
  fireMed.append(svg("line", { x1: 0, y1: 0, x2: 0, y2: 14, stroke: "#000000", "stroke-width": "1.2" }));
  defs.append(dots, fireHi, fireMed);
  const safe = hazard === "tsunami" ? ((HUBD.safe_zones || {})[county] || []) : [];
  const safeLayer = svg("g", { class: "layer-safe" });
  if (safe.length) {
    safeLayer.append(svg("path", { d: safe.map(ringPath).join(" "), fill: "url(#safe-dots)", "fill-opacity": "0.4", "fill-rule": "evenodd",
      stroke: "#000000", "stroke-width": "1", "vector-effect": "non-scaling-stroke", "pointer-events": "none" }));
    root.append(safeLayer);
  }
  const fh = hazard === "wildfire" ? ((HUBD.fire_high || {})[county] || []) : [];
  const fm = hazard === "wildfire" ? ((HUBD.fire_medium || {})[county] || []) : [];
  const fireLayer = svg("g", { class: "layer-fire" });
  if (fm.length) fireLayer.append(svg("path", { d: fm.map(ringPath).join(" "), fill: "url(#fire-med)", "fill-rule": "evenodd",
    stroke: "#000000", "stroke-width": "0.8", "stroke-dasharray": "1,2", "vector-effect": "non-scaling-stroke", "pointer-events": "none" }));
  if (fh.length) fireLayer.append(svg("path", { d: fh.map(ringPath).join(" "), fill: "url(#fire-high)", "fill-rule": "evenodd",
    stroke: "#000000", "stroke-width": "1.2", "vector-effect": "non-scaling-stroke", "pointer-events": "none" }));
  if (fh.length || fm.length) root.append(fireLayer);
  const fl = hazard === "coastal_flood" ? ((HUBD.flooded || {})[county] || []) : [];
  const floodLayer = svg("g", { class: "layer-flooded" });
  if (fl.length) {
    const d = fl.map(linePath).join(" ");
    floodLayer.append(svg("path", { d, fill: "none", stroke: "#ffffff", "stroke-width": "7", "stroke-linecap": "round", "vector-effect": "non-scaling-stroke", "pointer-events": "none" }));
    floodLayer.append(svg("path", { d, fill: "none", stroke: "#000000", "stroke-width": "4", "stroke-linecap": "round", "vector-effect": "non-scaling-stroke", "pointer-events": "none" }));
    root.append(floodLayer);
  }
  // Census areas with no known site within a 15-minute drive (ArcGIS drive-time matrix)
  const access = hasAccess();
  const outside = access ? tracts.filter((tr) => tr.o && tr.o[hazard]) : [];
  const hzLow = (Object.fromEntries(DATA.hazards)[hazard] || hazard).toLowerCase();
  const counts = access ? (DATA.access.outside_counts[`${county}|${hazard}`] || [0, 0, 0]) : [0, 0, 0];
  const outsideLayer = svg("path", { d: outside.map((tr) => tr.g.map(ringPath).join(" ")).join(" "),
    fill: "url(#outside-hatch)", "fill-opacity": "0.7", stroke: "none", "pointer-events": "none", class: "layer-outside" });
  if (outside.length) root.append(outsideLayer);
  const marks = [];
  // care facilities: black shapes; ⚠ when inside the selected hazard's zone
  const careLayer = svg("g", { class: "layer-care" });
  const facilities = access ? DATA.facilities.filter((f) => f.c === county) : [];
  for (const f of facilities) {
    const [x, y] = proj(f.x, f.y);
    const g = svg("g", { class: "facility", transform: `translate(${x} ${y}) scale(1)` });
    g.dataset.x = x; g.dataset.y = y;
    g.append(facilityShape((FACILITY[f.t] || FACILITY.hospital)[0], 0, 0));
    const zone = facilityZone(f, hazard);
    if (zone) {
      const w = svg("text", { x: 6, y: -4, "font-size": "13", "font-weight": "bold", stroke: "#ffffff", "stroke-width": "3", "paint-order": "stroke", class: "zone-flag",
        role: "img", "aria-label": `In hazard zone: ${zone}` });
      w.textContent = "⚠"; g.append(w);
    }
    const tip = svg("title");
    tip.textContent = `${f.n} – ${DATA.access.types[f.t]}${zone ? ` – inside: ${zone}` : zone === "" ? " – outside this hazard's zone" : ""}`;
    g.append(tip);
    marks.push(g); careLayer.append(g);
  }
  if (facilities.length) root.append(careLayer);
  // permanent outdoor sirens and the official rated audible radius (dashed circles)
  const sirenLayer = svg("g", { class: "layer-sirens" });
  const sirens = hasState() ? (DATA.state.sirens[county] || []) : [];
  for (const [lon, lat] of sirens) {
    const [x, y] = proj(lon, lat);
    const r = Math.abs(proj(lon, lat + DATA.state.radius_m / 111320)[1] - y);
    sirenLayer.append(svg("circle", { cx: x, cy: y, r: r.toFixed(1), fill: "#000000", "fill-opacity": "0.06",
      stroke: "#000000", "stroke-width": "0.8", "stroke-dasharray": "3,2", "vector-effect": "non-scaling-stroke", "pointer-events": "none" }));
  }
  for (const [lon, lat] of sirens) {
    const [x, y] = proj(lon, lat);
    const g = svg("g", { class: "siren", transform: `translate(${x} ${y}) scale(1)` });
    g.dataset.x = x; g.dataset.y = y;
    g.append(svg("circle", { cx: 0, cy: 0, r: 2.5, fill: "#000000", stroke: "#ffffff", "stroke-width": "1" }));
    marks.push(g); sirenLayer.append(g);
  }
  if (sirens.length) root.append(sirenLayer);
  for (const s of sites) {
    if (s.lon === null) continue;
    const [x, y] = proj(s.lon, s.lat);
    const g = svg("g", { class: "site", transform: `translate(${x} ${y}) scale(1)` });
    g.dataset.x = x; g.dataset.y = y; g.dataset.site = s.id;
    g.append(markerShape((MARKERS[s.st] || MARKERS.ok)[0], 0, 0));
    const lab = svg("text", { x: 10, y: 4, "font-size": "13", "font-weight": "bold",
      stroke: "#ffffff", "stroke-width": "3", "paint-order": "stroke" });
    lab.textContent = s.n; g.append(lab);
    marks.push(g); root.append(g);
  }
  Object.assign(MAP, { root, W, H, proj, paths, marks, tracts, county, sc, sites, hazard, level,
    hatches: [[hatch, 8, 1.5], [hatch2, 6, 1.2], [dots, 7, 1.3], [fireHi, 6, 1.6], [fireMed, 14, 1.2]], view: [0, 0, W, H] });

  const legend = el("ul", { class: "legend", "aria-label": "Map legend" });
  let lo = 0;
  bounds.forEach((b, i) => {
    const sw = svg("svg", { width: 28, height: 16, "aria-hidden": "true" });
    sw.append(svg("rect", { width: 28, height: 16, fill: css(RAMP[i]), stroke: "#000" }));
    legend.append(el("li", null, sw, names[i], " ", el("small", null, keep(`(${fmt(lo)}–${fmt(b)} people)`))));
    lo = b;
  });
  const swatch = (attrs, text) => {
    const sw = svg("svg", { width: 28, height: 16, "aria-hidden": "true" });
    sw.append(svg("rect", { width: 28, height: 16, ...attrs }));
    return el("li", null, sw, text);
  };
  legend.append(swatch({ fill: "#fff", stroke: "#000", "stroke-width": "2" }, "Solid outline: Census area in the risk area"));
  legend.append(swatch({ fill: "#fff", stroke: "#9a9a9a", "stroke-dasharray": "2,2" }, "Dashed outline: outside the risk area"));
  if (zone.length) {
    const sw = svg("svg", { width: 28, height: 16, "aria-hidden": "true" });
    const p2 = svg("defs"); const pat = hatch.cloneNode(true); pat.setAttribute("id", "tsunami-hatch-key"); p2.append(pat); sw.append(p2);
    sw.append(svg("rect", { width: 28, height: 16, fill: "url(#tsunami-hatch-key)", stroke: "#000", "stroke-dasharray": "5,3" }));
    legend.append(el("li", null, sw, "Hatched, dashed edge: State tsunami evacuation zone (simplified outline)"));
  }
  if (outside.length) {
    const sw = svg("svg", { width: 28, height: 16, "aria-hidden": "true" });
    const p3 = svg("defs"); const pat = hatch2.cloneNode(true); pat.setAttribute("id", "outside-hatch-key"); p3.append(pat); sw.append(p3);
    sw.append(svg("rect", { width: 28, height: 16, fill: "url(#outside-hatch-key)", stroke: "#000" }));
    legend.append(el("li", null, sw, `Horizontal lines: ${DATA.access.no_activated.toLowerCase()} – sites usable for ${hzLow}`));
  }
  for (const [shape, label] of Object.values(FACILITY)) {
    if (!facilities.length) break;
    const sw = svg("svg", { width: 28, height: 22, "aria-hidden": "true" });
    sw.append(facilityShape(shape, 14, 11, 6));
    legend.append(el("li", null, sw, `${label} (care facility)`));
  }
  if (sirens.length) {
    const sw = svg("svg", { width: 28, height: 22, "aria-hidden": "true" });
    sw.append(svg("circle", { cx: 14, cy: 11, r: 9, fill: "#000", "fill-opacity": "0.06", stroke: "#000", "stroke-dasharray": "3,2" }));
    sw.append(svg("circle", { cx: 14, cy: 11, r: 2.5, fill: "#000" }));
    legend.append(el("li", null, sw, `Outdoor siren (dot) and its rated audible radius, ${fmt(DATA.state.radius_ft)} feet (dashed circle; real range varies)`));
  }
  const patternKey = (pat, id, attrs, text) => {
    const sw = svg("svg", { width: 28, height: 16, "aria-hidden": "true" });
    const dd = svg("defs"); const c = pat.cloneNode(true); c.setAttribute("id", id); dd.append(c); sw.append(dd);
    sw.append(svg("rect", { width: 28, height: 16, fill: `url(#${id})`, stroke: "#000", ...attrs }));
    legend.append(el("li", null, sw, text));
  };
  if (safe.length) patternKey(dots, "safe-dots-key", {}, "Dots, solid edge: Tsunami Safe Zone – evacuate to these areas (State; simplified outline)");
  if (fh.length) patternKey(fireHi, "fire-high-key", {}, "Close diagonal lines: State Fire Risk Area rated High (comparison layer)");
  if (fm.length) patternKey(fireMed, "fire-med-key", { "stroke-dasharray": "1,2" }, "Wide diagonal lines, dotted edge: State Fire Risk Area rated Medium (comparison layer)");
  if (fl.length) {
    const sw = svg("svg", { width: 28, height: 16, "aria-hidden": "true" });
    sw.append(svg("path", { d: "M2,8 L26,8", stroke: "#ffffff", "stroke-width": "7", "stroke-linecap": "round" }));
    sw.append(svg("path", { d: "M2,8 L26,8", stroke: "#000000", "stroke-width": "4", "stroke-linecap": "round" }));
    legend.append(el("li", null, sw, "Thick black line with a white edge: highway that may flood with 3.2 ft of sea level rise"));
  }
  if (facilities.some((f) => facilityZone(f, hazard))) legend.append(el("li", null, el("span", { class: "legend-glyph", "aria-hidden": "true" }, "⚠"), "Care facility inside this hazard's zone (small ⚠ beside the facility; each area's panel lists them in words)"));
  const seen = new Set();
  for (const [shape, label] of Object.values(MARKERS)) {
    if (seen.has(label)) continue; seen.add(label);
    const sw = svg("svg", { width: 28, height: 22, "aria-hidden": "true" });
    sw.append(markerShape(shape, 14, 11, 6));
    legend.append(el("li", null, sw, label));
  }
  const key = el("ol", { class: "sitekey", "aria-label": "Site key" },
    sites.map((x) => el("li", null, el("b", null, String(x.n)),
      ` = ${x.name} (${DATA.meta.site_key_status[x.st] || x.st})`)));

  // the same areas as a list: buttons that open the area (keyboard Enter or Space)
  const risk = tracts.filter((tr) => tr.f in sc.tracts).sort((a, b) => (afn[b.f] || 0) - (afn[a.f] || 0));
  const areas = el("details", { class: "areas" },
    el("summary", null, `Census areas on this map in the risk area (${risk.length}) – open one for details`),
    el("ul", null, risk.map((tr) => {
      const b = el("button", { type: "button", class: "linklike" }, keep(`${tr.l || tr.f}: ${fmt(afn[tr.f])} people with needs (${level(tr.f)})`));
      b.addEventListener("click", () => openArea(tr.f, b));
      return el("li", null, b, lahainaNote(tr.l, true));
    })));
  const official = el("a", { class: "button", href: DATA.official_map.url, target: "_blank", rel: "noopener noreferrer" },
    `${DATA.official_map.label} (${DATA.official_map.source}, opens in a new tab)`);
  const panel = el("section", { id: "area-panel", class: "area-panel", role: "region", "aria-labelledby": "area-title", hidden: "" });
  const layerBox = (key, label, node, count) => {
    const id = `layer-${key}`;
    const box = el("input", { type: "checkbox", id, name: id });
    box.checked = LAYERS[key];
    const show = () => { if (box.checked) node.removeAttribute("display"); else node.setAttribute("display", "none"); };
    box.addEventListener("change", () => { LAYERS[key] = box.checked; show(); });
    show();
    return el("label", { for: id, class: "check" }, box, ` ${label}${count === null ? "" : ` (${fmt(count)})`}`);
  };
  const hubBoxes = [
    safe.length ? layerBox("safe", "Tsunami Safe Zones – evacuate to these areas (dots)", safeLayer, null) : null,
    safe.length && county === "Maui" ? el("p", { class: "layer-note", id: "maui-2013" }, HUBD.maui_2013) : null,
    fh.length || fm.length ? layerBox("fire", "State Fire Risk Areas, High and Medium (comparison layer; the plan uses the FEMA National Risk Index)", fireLayer, null) : null,
    fl.length ? layerBox("flooded", `Highways that may flood with 3.2 ft of sea level rise (thick line, ${fmt(HUBD.flooded_km[county])} km)`, floodLayer, null) : null,
  ];
  const hubSources = [safe.length ? HUBD.sources.safe_zones : null, fh.length || fm.length ? HUBD.sources.fire : null, fl.length ? HUBD.sources.flooded : null]
    .filter(Boolean).map((t) => el("p", { class: "src" }, `Source: ${t}`));
  const layers = access ? el("fieldset", { class: "layers" }, el("legend", null, "Map layers"), ...hubBoxes,
    layerBox("outside", `${DATA.access.no_activated} – sites usable for ${hzLow}`, outsideLayer, outside.length),
    el("p", { class: "layer-note", id: "scenario-note" }, `With DOE candidate schools usable for ${hzLow}: ${fmt(counts[1])} of ${fmt(counts[2])} areas (2026 activated sites only: ${fmt(counts[0])}). ${DATA.access.not_no_shelter}`),
    layerBox("care", "Care facilities", careLayer, facilities.length),
    sirens.length ? layerBox("sirens", `Outdoor sirens and rated audible radius (${fmt(DATA.state.radius_ft)} ft)`, sirenLayer, sirens.length) : null) : null;
  return [el("p", null, official), layers,
    el("div", { class: "mapwrap" }, el("div", { class: "map" }, root),
      el("div", null, el("h3", null, "Site key"), key)),
    el("p", { class: "hint" }, "Select a Census area on the map, or open one from the list below the legend."),
    el("p", { class: "note", id: "site-focus", role: "status", hidden: "" }),
    panel, legend, areas,
    access ? el("p", { class: "src" }, `${DATA.access.source} ${DATA.access.attribution} ${DATA.access.outside_method}`) : null,
    ...hubSources];
}

/* ---------- zoom: animate the SVG viewBox; markers keep their size ---------- */
function setView(v) {
  MAP.view = v;
  MAP.root.setAttribute("viewBox", v.map((x) => x.toFixed(1)).join(" "));
  const k = v[2] / MAP.W;
  for (const g of MAP.marks) g.setAttribute("transform", `translate(${g.dataset.x} ${g.dataset.y}) scale(${k.toFixed(3)})`);
  // keep the hatches the same on screen at any zoom
  for (const [pat, size, width] of MAP.hatches) {
    const s = (size * k).toFixed(2), mark = pat.firstChild;
    pat.setAttribute("width", s); pat.setAttribute("height", s);
    if (mark.tagName === "circle") {                     // dots: centre and radius
      mark.setAttribute("cx", (size * k / 2).toFixed(2)); mark.setAttribute("cy", (size * k / 2).toFixed(2));
      mark.setAttribute("r", (width * k).toFixed(2));
    } else {
      mark.setAttribute("y2", s);
      mark.setAttribute("stroke-width", (width * k).toFixed(2));
    }
  }
}

function zoomTo(target) {
  const from = MAP.view.slice();
  if (REDUCED()) { setView(target); return; }
  const t0 = performance.now(), ms = 350;
  const step = (now) => {
    const a = Math.min(1, (now - t0) / ms), e = a * (2 - a);
    setView(from.map((x, i) => x + (target[i] - x) * e));
    if (a < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function areaBox(tr) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const r of tr.g) for (let i = 0; i < r.length; i += 2) {
    if (r[i] < MAIN_ISLANDS_WEST) continue;
    const [x, y] = MAP.proj(r[i], r[i + 1]);
    x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
  }
  const pad = 0.25, w = Math.max(x1 - x0, 40), h = Math.max(y1 - y0, 30);
  let bw = w * (1 + 2 * pad), bh = h * (1 + 2 * pad);
  if (bw / bh > MAP.W / MAP.H) bh = bw * MAP.H / MAP.W; else bw = bh * MAP.W / MAP.H;
  return [(x0 + x1) / 2 - bw / 2, (y0 + y1) / 2 - bh / 2, bw, bh];
}

/* straight-line distance (great circle), km */
function haversineKm(lon1, lat1, lon2, lat2) {
  const R = 6371.0088, rad = Math.PI / 180;
  const dp = (lat2 - lat1) * rad, dl = (lon2 - lon1) * rad;
  const h = Math.sin(dp / 2) ** 2 + Math.cos(lat1 * rad) * Math.cos(lat2 * rad) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

/* usable sites on the SAME island only (never another island), nearest first:
   by drive time when the ArcGIS matrix has this area, else straight-line distance */
function nearestSites(tr, sites, k = 3) {
  const point = tr.p;
  const usable = sites.filter((s) => s.st === "ok" && s.lon !== null && tr.i && s.island === tr.i);
  if (tr.a && tr.a.length) {
    const byId = new Map(usable.map((s) => [s.id, s]));
    return tr.a.filter((r) => byId.has(r[0]) && r[1] !== null)
      .map(([id, drive, km, walk]) => ({ s: byId.get(id), drive, km, walk }))
      .sort((a, b) => a.drive - b.drive || a.s.name.localeCompare(b.s.name)).slice(0, k);
  }
  return usable
    .map((s) => ({ s, km: haversineKm(point[0], point[1], s.lon, s.lat) }))
    .sort((a, b) => a.km - b.km || a.s.name.localeCompare(b.s.name)).slice(0, k);
}

/* populated Census areas with no permanent outdoor siren ("How to reach residents") */
function zeroSirens(county) {
  if (!hasState()) return [];
  const label = Object.fromEntries(DATA.tracts.map((t) => [t.f, t.l || t.f]));
  const share = Object.fromEntries(DATA.tracts.map((t) => [t.f, t.sc || 0]));
  const low = DATA.state.low[county] || [];
  return [el("p", { id: "outside-sirens" }, `${DATA.state.outside_text}: `, el("strong", null, fmt(DATA.state.outside[county] || 0)), "."),
    low.length ? el("details", { class: "areas", id: "zero-sirens" },
      el("summary", null, `${DATA.state.low_text} (${low.length}): ${DATA.state.no_sirens}`),
      el("ul", null, low.map((f) => el("li", null, keep(`${label[f] || f} – ${Math.round(share[f] * 100)}% within rated range`), lahainaNote(label[f], true))))) : null,
    source("sirens")];
}

/* care facilities inside this Census area, and whether each is in the hazard's zone */
function careInArea(f, hazard) {
  if (!hasAccess()) return null;
  const here = DATA.facilities.filter((x) => x.f === f);
  const hz = Object.fromEntries(DATA.hazards)[hazard].toLowerCase();
  if (!here.length) return [el("h4", null, "Care facilities in this area"), el("p", null, "None listed (CMS dialysis facilities, nursing homes, hospitals).")];
  return [el("h4", null, "Care facilities in this area"),
    table("Care facilities in this area", ["Name", "Type", `In the ${hz} zone?`],
      here.map((x) => {
        const z = facilityZone(x, hazard);
        return [x.n, DATA.access.types[x.t], z ? `⚠ Yes – ${z}` : z === "" ? (x.d && hazard !== "tsunami" ? "No – FEMA zone D (flood risk not mapped)" : "No") : DATA.access.no_screen];
      }))];
}

/* care facilities in this hazard's zone, one county (the same table as the PDFs) */
function careTable(county, hazard, cLabel, hLabel) {
  if (!hasAccess()) return [];
  const all = DATA.facilities.filter((x) => x.c === county);
  const rows = all.filter((x) => facilityZone(x, hazard));
  const out = [el("h3", { id: "care-facilities" }, "Care facilities in hazard zones")];
  if (!ZONE_HAZARDS.includes(hazard)) out.push(el("p", null, `${DATA.access.no_screen} Care facilities in this county: ${fmt(all.length)}.`));
  else if (rows.length) out.push(table(`Care facilities in hazard zones – ${cLabel}, ${hLabel} (${rows.length} of ${all.length})`,
    ["Name", "Type", "Zone"], rows.map((x) => [x.n, DATA.access.types[x.t], x.z[hazard]])));
  else out.push(el("p", null, `None of the ${fmt(all.length)} care facilities in this county is inside the ${hLabel.toLowerCase()} zone.`));
  const zoneD = all.filter((x) => x.d);
  if (hazard !== "tsunami" && ZONE_HAZARDS.includes(hazard) && zoneD.length) {
    out.push(el("p", null, `${DATA.access.zone_d.replace("{n}", zoneD.length)} ${zoneD.map((x) => x.n).join(", ")}.`));
  }
  out.push(source("facilities"));
  if (hasState()) out.push(source("childcare"));
  return out;
}

/* ---------- detail panel for one Census area ---------- */
let OPENER = null;

function openArea(f, opener) {
  const tr = MAP.tracts.find((t) => t.f === f);
  const panel = document.getElementById("area-panel");
  if (!tr || !panel) return;
  OPENER = opener || MAP.paths[f] || null;
  for (const p of Object.values(MAP.paths)) p.classList.remove("selected");
  MAP.paths[f].classList.add("selected");
  zoomTo(areaBox(tr));

  const { sc, hazard, county } = MAP, C = DATA.meta.cols;
  const v = sc.tracts[f], inRisk = Boolean(v);
  const pop = tr.n[0], share = inRisk && pop ? v[0] / pop : 0;
  const [main, sub] = (tr.l || f).split(" · ");
  const hz = Object.fromEntries(DATA.hazards)[hazard];
  const counts = DATA.area_fields.map((k, i) => [C[k], fmt(inRisk ? tr.n[i + 1] * share : tr.n[i + 1])]);
  const near = nearestSites(tr, MAP.sites);
  const lead = new Set(), support = new Set();
  for (const n of sc.needs) { n[3].split(", ").forEach((x) => x && lead.add(x)); n[4].split(", ").forEach((x) => x && support.add(x)); }
  const L = DATA.languages[county];
  const msgLink = (label, language) => {
    const a = el("a", { href: "#messages" }, label);
    a.addEventListener("click", () => Object.assign(MSG, { county, hazard, language: language || "", phase: "", onlyCounty: false }));
    return a;
  };
  const langs = L.rows.slice(0, 3);
  const msgLangs = new Set(DATA.messages.map((m) => m.language_label));
  const back = el("button", { type: "button", class: "button" }, "Back to county");
  back.addEventListener("click", closeArea);
  const print = el("button", { type: "button", class: "button" }, "Print this area");
  print.addEventListener("click", () => { document.body.classList.add("print-area"); window.print(); });

  panel.replaceChildren();
  append(panel,
    el("h3", { id: "area-title", tabindex: "-1" }, main, " ", el("small", null, keep(sub || ""))),
    isLahaina(main) ? el("p", { class: "note lahaina-note", id: "lahaina-note" }, DATA.meta.lahaina_note) : null,
    el("p", null, el("strong", null, inRisk ? `Inside the ${hz.toLowerCase()} risk area` : `Outside the ${hz.toLowerCase()} risk area`),
      ` · Need level: ${MAP.level(f)}`),
    el("dl", { class: "area-facts" },
      el("dt", null, inRisk ? C.at_risk : "People living in the area"), el("dd", null, fmt(inRisk ? v[0] : pop)),
      inRisk ? [el("dt", null, "May need a public shelter (likely)"), el("dd", null, fmt(v[1]))] : null),
    table(inRisk ? "Access and functional needs (people in the risk area)" : "Access and functional needs (people living in the area)",
      ["Need", "People"], counts, [1]),
    el("h4", null, `Nearest sites usable for ${hz.toLowerCase()} on ${tr.i || "this island"}`),
    tr.i === "Niʻihau"
      ? el("p", { class: "note", id: "nearest-none" }, DATA.meta.niihau_note)
      : near.length && near[0].drive !== undefined
        ? table(`Same island only; travel times by road from the area's center (Esri ArcGIS routing)`, ["#", "Site", "Travel time", "Road distance"],
          near.map(({ s, drive, km, walk }) => [s.n, s.name,
            `${Math.round(drive)} min drive · ${walk === null ? DATA.access.no_walk : `${Math.round(walk)} min walk`} (${DATA.access.times_note})`,
            `${km.toFixed(1)} km`]), [0, 3])
        : near.length
          ? table(`Same island only; straight-line distance from the area's center`, ["#", "Site", "Distance"],
            near.map(({ s, km }) => [s.n, s.name, `${km.toFixed(1)} km straight-line, same island`]), [0, 2])
          : el("p", { class: "note", id: "nearest-none" }, DATA.meta.no_island_site),
    tr.o && tr.o[hazard] && tr.i !== "Niʻihau" ? el("p", { class: "note", id: "outside-drive" },
      `${DATA.access.no_activated}, for ${hz.toLowerCase()}. With DOE candidate schools: ${tr.o[hazard] === 1 ? `a candidate school usable for ${hz.toLowerCase()} is within ${DATA.access.limit} minutes` : `still none within ${DATA.access.limit} minutes`}. ${DATA.access.not_no_shelter}`) : null,
    near.length && near[0].drive !== undefined ? el("p", { class: "src" }, `${DATA.access.source} ${DATA.access.attribution}`) : null,
    hasState() ? el("p", { id: "area-sirens" },
      el("strong", null, `Nearest outdoor siren: ${tr.sd === null || tr.sd === undefined ? "none on this island" : `${fmt(tr.sd)} ft`} (rated range ${fmt(DATA.state.radius_ft)} ft)`), el("br"),
      el("strong", null, `Share ${DATA.state.share_word} within rated siren range: ${Math.round((tr.sc || 0) * 100)}%`),
      (tr.sc || 0) < 0.5 ? ` – ${DATA.state.no_sirens}.` : "") : null,
    careInArea(f, hazard),
    el("p", null, el("strong", null, "Proposed partners: "), `lead – ${[...lead].join(", ") || "—"}; support – ${[...support].join(", ") || "—"}. `, DATA.meta.role_status),
    el("p", null, el("strong", null, `Top languages (${L.area}): `), langs.map((r) => `${r[0]} ${fmt(r[1])}`).join("; ") || "—"),
    el("p", null, el("strong", null, "Messages: "), msgLink(`all ${hz.toLowerCase()} messages`),
      langs.filter((r) => msgLangs.has(r[0])).flatMap((r) => [", ", msgLink(r[0], DATA.messages.find((m) => m.language_label === r[0]).language)])),
    el("p", { class: "panel-actions" }, back, " ", print));
  panel.hidden = false;
  const q = new URLSearchParams(location.search);
  q.set("county", county); q.set("hazard", hazard); q.set("area", f);
  history.replaceState(null, "", `?${q.toString()}${location.hash}`);
  document.getElementById("area-title").focus();
}

/* deep link ?site=<id>: zoom to the site's marker and outline it (stress test "show on map") */
function openSite(id) {
  const g = (MAP.marks || []).find((m) => m.dataset.site === String(id));
  const s = DATA.sites.find((x) => x.id === id);
  if (!g || !s) return false;
  const x = +g.dataset.x, y = +g.dataset.y, bw = MAP.W / 4, bh = MAP.H / 4;
  g.classList.add("selected-site");
  zoomTo([x - bw / 2, y - bh / 2, bw, bh]);
  const note = document.getElementById("site-focus");
  note.textContent = `Showing site ${g.querySelector("text") ? g.querySelector("text").textContent : ""}: ${s.name} (${s.address}).`;
  note.hidden = false;
  return true;
}

function closeArea() {
  const panel = document.getElementById("area-panel");
  if (panel) { panel.hidden = true; panel.replaceChildren(); }
  for (const p of Object.values(MAP.paths || {})) p.classList.remove("selected");
  if (MAP.root) zoomTo([0, 0, MAP.W, MAP.H]);
  const q = new URLSearchParams(location.search); q.delete("area");
  history.replaceState(null, "", `?${q.toString()}${location.hash}`);
  const back = OPENER && document.contains(OPENER) ? OPENER : MAP.root;
  if (back && back.focus) back.focus();
  // a map area cannot take focus: return to the map itself (tabindex -1, not in the Tab order)
  if (document.activeElement !== back && MAP.root && document.contains(MAP.root)) MAP.root.focus();
  OPENER = null;
}

/* Esc inside the open panel works like "Back to county" (focus returns to the opener) */
document.addEventListener("keydown", (e) => {
  const panel = document.getElementById("area-panel");
  if (e.key === "Escape" && panel && !panel.hidden && panel.contains(document.activeElement)) closeArea();
});

window.addEventListener("afterprint", () => document.body.classList.remove("print-area"));

function needNames(k) {
  if (k <= 1) return ["People with needs"];
  if (k === DATA.meta.need_names.length) return DATA.meta.need_names;
  return ["Lowest need", ...Array(k - 2).fill("Middle"), "Highest need"];
}

/* community name first, Census area ID as a smaller second line */
function community(main, sub) {
  return [el("span", null, main), el("br"), el("small", null, keep(sub || "")), ...(lahainaNote(main) || [])];
}
/* Lahaina-area Census areas (community label names Lahaina): 2020 population predates the
   August 2023 fire. Only Census-area labels are passed here, never site names. */
const isLahaina = (label) => /\bLahaina\b/.test(label || "");
function lahainaNote(label, inline) {
  if (!isLahaina(label)) return null;
  const note = el("small", { class: "lahaina-note" }, DATA.meta.lahaina_note);
  return inline ? [" ", note] : [el("br"), note];
}
/* "{SOURCES}" becomes a "see Sources" link (the PDFs say "section 8") */
const linkSources = (text) => text.split("{SOURCES}").flatMap((part, i) => (i
  ? [el("a", { href: DATA.provenance.sources_url, rel: "noopener noreferrer" }, "see Sources"), part]
  : [part]));
const source = (key) => el("p", { class: "src" }, linkSources(DATA.meta.sources[key]));

/* ---------- help panel ("?") ---------- */
function helpPanel(sc, hazard) {
  const s = sc.summary, C = DATA.meta.cols, ex = sc.largest[0];
  const area = DATA.meta.footprint_text[s.footprint_rule] || s.footprint_rule;
  const body = [];
  if (ex) {
    body.push(el("h3", null, "Example row"),
      table("One row from the “Largest single community” table", [C.area, C.at_risk, C.shelter],
        [[community(ex.label_main, ex.label_sub), fmt(ex.at_risk_pop), `${fmt(ex.low)} – ${fmt(ex.central)} – ${fmt(ex.high)}`]], [1, 2]),
      el("p", null, `Read it as: about ${fmt(ex.at_risk_pop)} people live in the risk area of ${ex.label_main}.${isLahaina(ex.label_main) ? ` ${DATA.meta.lahaina_note}` : ""} If this hazard hits, between ${fmt(ex.low)} and ${fmt(ex.high)} of them may need a public shelter; ${fmt(ex.central)} is the likely number.`));
  }
  body.push(
    el("h3", null, "Census area"),
    el("p", null, keep("A neighborhood-sized area the U.S. Census uses, usually 1,200–8,000 people. The number (for example “Census area 308”) is its Census ID. Each area is named after the Census place where most of its people live; “near” means no one in the area lives inside a named place, and “rural near” means most people live outside named places.")),
    el("h3", null, "Low – likely – high"),
    el("p", null, `The share of people in the risk area who may go to a public shelter: low ${pct(s.rate_low)}, likely ${pct(s.rate_central)}, high ${pct(s.rate_high)}. Where the rates come from: ${DATA.meta.rate_note[hazard]}`),
    el("h3", null, "Who has access and functional needs (CMIST)"),
    el("ul", null, DATA.meta.cmist.map(([k, v]) => el("li", null, el("strong", null, `${k}: `), v))),
    el("h3", null, "County total vs. one community"),
    el("p", null, `The county total counts ${area} as hit at the same time, so it is an upper bound. Use the “Largest single community” table to plan for an event that hits one community.`),
    el("h3", null, "Map"),
    el("p", null, "Darker blue means more people with needs, from “Lowest need” to “Highest need”. A solid outline marks a Census area in the risk area; a dashed outline is outside it. Symbols: ○ usable site, △ check flood zone, ◇ flood risk not mapped, ☒ not for this hazard. Numbers on the map match the site key."),
    el("h3", null, "Why population numbers can differ"),
    el("p", null, "People in the risk area come from ACS 2018–2022 estimates (through the CDC Social Vulnerability Index 2022). Community names use 2020 Census counts. County totals in the plan use Census estimates for 2025. Each table names its source underneath."),
    el("p", { class: "note" }, el("strong", null, "Every number is a planning estimate. In an event, follow county announcements.")));
  return el("details", { class: "help", id: "help" },
    el("summary", null, el("span", { class: "help-icon", "aria-hidden": "true" }, "?"), " How to read this page"),
    ...body);
}

/* ---------- navigation: Plan · Messages ---------- */
const VIEWS = { plan: "Plan", stress: "Stress tests", whatif: "What-if", messages: "Messages" };
function currentView() {
  const v = location.hash.replace("#", "");
  return v in VIEWS ? v : "plan";
}

function render() {
  const view = currentView();
  for (const id of Object.keys(VIEWS)) {
    const a = document.getElementById(`nav-${id}`);
    if (id === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
  document.getElementById("controls").hidden = view === "messages";
  if (view === "messages") renderMessages();
  else if (view === "stress") renderStress();
  else if (view === "whatif") renderWhatIf();
  else renderPlan();
  showVersion();
  SHOWN = view;
}

/* The user switched views (menu tab, a Messages link, browser Back): start at the top of the
   new view with focus on its heading. Not on first load or a deep link, so focus is never taken
   from someone just arriving. Instant jump, never a smooth scroll (prefers-reduced-motion). */
let SHOWN = null;
function onHashChange() {
  const before = SHOWN;
  render();
  if (SHOWN === before) return;
  const h = document.querySelector("#app h2");
  window.scrollTo(0, 0);
  if (!h) return;
  h.setAttribute("tabindex", "-1");
  h.focus({ preventScroll: true });
}

const provLabel = (text, link) => {
  const [before, after] = link ? text.split("see Sources") : [text];
  return el("p", { class: "prov" }, before,
    link ? [el("a", { href: link, rel: "noopener noreferrer" }, "see Sources"), after] : null);
};

/* ---------- Messages: every stored message row, filters only narrow ---------- */
const MSG = { county: null, onlyCounty: false, hazard: "", phase: "", language: "", open: new Set(["English"]) };

function msgSelect(label, key, pairs) {
  const id = `msg-${key}`;
  const s = el("select", { id, name: key }, pairs.map(([v, t]) => el("option", { value: v }, t)));
  s.value = MSG[key] ?? "";
  s.addEventListener("change", () => { MSG[key] = s.value; renderMessages(); });
  return [el("label", { for: id }, label), s];
}

/* name = the visible word + which message, e.g. "Copy Vietnamese – Wildfire, before"
   (starts with the visible word so voice control can still say "click Copy") */
function copyButton(text, which) {
  if (!text) return el("button", { type: "button", class: "button", disabled: "", "aria-label": `No text yet: ${which}` }, "No text yet");
  const b = el("button", { type: "button", class: "button", "aria-label": `Copy ${which}` }, "Copy");
  const say = (word) => { b.textContent = word; b.setAttribute("aria-label", `${word} ${which}`); };
  b.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(text); say("Copied"); }
    catch (err) { say("Select the text to copy"); }
  });
  return b;
}

function badge(status) {
  const kind = status === "Reviewed" ? "badge reviewed" : status === "Needs a translator" ? "badge human" : "badge draft";
  return el("span", { class: kind }, status);
}

function renderMessages() {
  const app = document.getElementById("app");
  if (MSG.county === null) MSG.county = document.getElementById("county").value;
  const all = DATA.messages;
  const reviewed = all.filter((m) => m.status === "Reviewed").length;
  const countyLangs = new Set(["English", ...(DATA.message_languages[MSG.county] || [])]);
  const cLabel = Object.fromEntries(DATA.counties)[MSG.county];
  const uniq = (k, lab) => [...new Map(all.map((m) => [m[k], m[lab || k]])).entries()];
  const shown = all.filter((m) =>
    (!MSG.onlyCounty || countyLangs.has(m.language)) &&
    (!MSG.hazard || m.hazard === MSG.hazard) &&
    (!MSG.phase || m.phase === MSG.phase) &&
    (!MSG.language || m.language === MSG.language));

  const only = el("input", { type: "checkbox", id: "msg-only" });
  only.checked = MSG.onlyCounty;
  only.addEventListener("change", () => { MSG.onlyCounty = only.checked; renderMessages(); });
  const hz = Object.fromEntries(DATA.hazards);
  const filters = el("form", { class: "controls msg-filters", "aria-label": "Filter messages" },
    ...msgSelect("County", "county", DATA.counties),
    el("label", { for: "msg-only", class: "check" }, only, ` Only ${cLabel}'s message languages`),
    ...msgSelect("Hazard", "hazard", [["", "All hazards"], ...DATA.hazards]),
    ...msgSelect("Phase", "phase", [["", "All phases"], ...uniq("phase").map(([v]) => [v, v])]),
    ...msgSelect("Language", "language", [["", "All languages"], ...uniq("language", "language_label")]));
  filters.addEventListener("submit", (e) => e.preventDefault());

  const counts = table("Messages by language",
    ["Language", "Messages", "Drafts", "Waiting for a translator", "Reviewed", "Review assigned to"],
    DATA.message_counts.map((c) => [c.label,
      fmt(c.rows), fmt(c.drafts), fmt(c.placeholders), fmt(c.reviewed), c.assignee || "—"]), [1, 2, 3, 4]);

  const cards = shown.map((m) => el("article", { class: "msg" },
    el("header", null,
      el("strong", null, `${m.language_label} · ${hz[m.hazard] || m.hazard} · ${m.phase}`),
      " ", el("small", null, `Trigger: ${m.trigger_label}`),
      countyLangs.has(m.language) ? el("span", { class: "tag" }, `In ${cLabel}'s list`) : null),
    m.text ? el("p", { class: "msg-text", lang: m.lang || null }, m.text)
      : el("p", { class: "msg-text empty" }, `No text yet: needs a translator (translate from the English message ${hz[m.hazard] || m.hazard} · ${m.phase}).`),
    el("dl", { class: "msg-meta" },
      el("dt", null, "Status"), el("dd", null, badge(m.status)),
      el("dt", null, "Review assigned to"), el("dd", null, m.review_assignee || "—"),
      el("dt", null, "Reviewed by"), el("dd", null, m.reviewed_by || "—"),
      el("dt", null, "Review date"), el("dd", null, keep(m.review_date || "—")),
      el("dt", null, "Approved"), el("dd", null, m.approved || "—"),
      m.notes ? [el("dt", null, "Notes"), el("dd", null, m.notes)] : null),
    copyButton(m.text, `${m.language_label} – ${hz[m.hazard] || m.hazard}, ${m.phase.toLowerCase()}`)));

  app.replaceChildren();
  append(app,
    el("h2", { id: "messages" }, "Messages"),
    el("p", { class: "note" }, el("strong", null, `Reviewed: ${fmt(reviewed)} of ${fmt(all.length)}. `),
      "These are drafts for county review. Do not send any message until a native speaker and the county have reviewed it."),
    el("p", null, "The message library is statewide: every county uses the same texts. Filters only narrow the list; nothing is left out by default."),
    counts,
    filters,
    el("p", { role: "status" }, `Showing ${fmt(shown.length)} of ${fmt(all.length)} messages.`),
    msgGroups(shown, cards, countyLangs, cLabel));
}

/* one open/close section per language (native <details>), in library order. English starts
   open; a language picked in the filter opens; sections the user opens stay open on re-render. */
function msgGroups(shown, cards, countyLangs, cLabel) {
  const groups = new Map();
  shown.forEach((m, i) => {
    if (!groups.has(m.language)) groups.set(m.language, { label: m.language_label, cards: [], texts: 0 });
    const g = groups.get(m.language);
    g.cards.push(cards[i]);
    if (m.text) g.texts += 1;
  });
  return [...groups].map(([lang, g]) => {
    const d = el("details", { class: "msg-group", open: MSG.open.has(lang) || MSG.language === lang ? "" : null },
      el("summary", null, el("h3", null, g.label),
        el("small", null, `${fmt(g.cards.length)} ${g.cards.length === 1 ? "message" : "messages"}${g.texts < g.cards.length ? `, ${fmt(g.cards.length - g.texts)} waiting for a translator` : ""}`),
        countyLangs.has(lang) ? el("span", { class: "tag" }, `In ${cLabel}'s list`) : null),
      el("div", { class: "msg-list" }, g.cards));
    d.addEventListener("toggle", () => { if (d.open) MSG.open.add(lang); else MSG.open.delete(lang); });
    return d;
  });
}

/* ---------- plan view ---------- */
function renderPlan() {
  const county = document.getElementById("county").value;
  const hazard = document.getElementById("hazard").value;
  const sc = DATA.scenarios[`${county}|${hazard}`];
  const cLabel = Object.fromEntries(DATA.counties)[county];
  const hLabel = Object.fromEntries(DATA.hazards)[hazard];
  const s = sc.summary, C = DATA.meta.cols;
  const app = document.getElementById("app");
  app.replaceChildren();

  // sites for this county/hazard, numbered like the playbook
  const sites = DATA.sites.filter((x) => x.county === county).map((x) => ({
    ...x, st: x.status[hazard] ? x.status[hazard][0] : "unlocated",
    why: x.status[hazard] ? x.status[hazard][1] : "Address not located; not on the map",
  })).sort((a, b) => STATUS_ORDER.indexOf(a.st) - STATUS_ORDER.indexOf(b.st) || a.name.localeCompare(b.name));
  sites.forEach((x, i) => { x.n = i + 1; });

  const kpis = [
    [C.at_risk, fmt(s.at_risk_pop)],
    ["May need a public shelter (likely)", fmt(s.shelter_demand_central)],
    ["May need a public shelter (low – high)", `${fmt(s.shelter_demand_low)} – ${fmt(s.shelter_demand_high)}`],
    [`${C.lep} (C)`, fmt(s.C_lep_at_risk)],
    [`${C.power} (M)`, fmt(s.M_power_dependent_at_risk)],
    [`${C.disability} (I)`, fmt(s.I_disability_at_risk)],
    [`${C.age65} (I)`, fmt(s.I_age65_at_risk)],
    [`${C.no_car} (T)`, fmt(s.T_no_vehicle_persons_at_risk)],
    ["Known 2026 shelter sites usable for this hazard", fmt(s.known_sites_usable)],
  ];
  kpis.splice(8, 0, ...DATA.meta.detail_keys.map(([k, field, letter]) => [`${C[k]} (${letter})`, fmt(s[field])]));
  if (hazard === "hurricane") kpis.push([C.highrise, fmt(s.highrise_units_at_risk)]);
  if (hazard === "tsunami") kpis.push(["People in the extreme tsunami zone (worst case)", fmt(s.at_risk_pop_extreme_zone)]);
  const lines = DATA.county_lines.filter((r) => r.county === county);
  const area = DATA.meta.footprint_text[s.footprint_rule] || s.footprint_rule;
  const largestTitle = "Largest single community (the Census areas with the most people who may need a shelter)";

  const L = DATA.languages[county];
  append(app,
    el("h2", { id: "summary" }, `${cLabel} – ${hLabel}`),
    helpPanel(sc, hazard),
    provLabel(DATA.provenance.numbers, DATA.provenance.sources_url),
    el("p", null, el("a", { class: "button", href: sc.playbook }, `⬇ Printable playbook (PDF): ${cLabel} – ${hLabel}`)),
    el("ul", { class: "kpis" }, kpis.map(([k, v]) => el("li", { class: /–/.test(v) ? "kpi-range" : null }, k, el("b", null, keep(v))))),
    county === "Maui" ? el("p", { class: "note lahaina-note", id: "lahaina-summary" }, DATA.meta.lahaina_summary) : null,
    source("summary"),
    DATA.stress ? el("p", { class: "plan-links" }, el("a", { class: "button", href: "#stress" }, `Stress tests – what could break in ${cLabel}`), " ",
      el("a", { class: "button", href: "#whatif" }, "What-if: change the planning numbers")) : null,
    el("p", null, `Share of people in the risk area who may need a public shelter: low ${pct(s.rate_low)}, likely ${pct(s.rate_central)}, high ${pct(s.rate_high)}. One person can be counted in more than one need. Open “How to read this page” for an explanation.`),

    el("h2", null, "Scope: county total vs. one community"),
    el("p", { class: "note" }, el("strong", null, "The county total is an upper bound. "),
      `It counts ${area} as hit at the same time. Real events usually hit fewer communities.`),
    table(hazard === "hurricane"
      ? [largestTitle, el("br"), el("span", { class: "caption-note" }, DATA.meta.hurricane_scope_note)]
      : largestTitle,
      [C.area, C.at_risk, C.shelter, C.lep, C.power, C.disability, C.age65, C.no_car],
      sc.largest.map((c) => [community(c.label_main || c.tract_label, c.label_sub), fmt(c.at_risk_pop),
        `${fmt(c.low)} – ${fmt(c.central)} – ${fmt(c.high)}`,
        fmt(c.C_lep_at_risk), fmt(c.M_power_dependent_at_risk), fmt(c.I_disability_at_risk), fmt(c.I_age65_at_risk),
        fmt(c.T_no_vehicle_persons_at_risk)]), [1, 2, 3, 4, 5, 6, 7]),
    source("people"),
    table("More needs in the largest communities", [C.area, ...DATA.meta.detail_keys.map(([k]) => C[k])],
      sc.largest.map((c) => [community(c.label_main || c.tract_label, c.label_sub),
        ...DATA.meta.detail_keys.map(([, field]) => fmt(c[field]))]), [1, 2, 3, 4]),
    source("detail"),

    el("h2", null, "Map: people with needs and known sites"),
    ...renderMap(county, sc, sites, `${cLabel} ${hLabel}: people with needs by Census area and known shelter sites`, hazard),
    el("p", null, "Color = people in the risk area who speak English less than well, use power-dependent medical equipment, have a disability, or live without a car (a person can be counted more than once). No street map: Census area outlines only. Select an area to see its details."),
    source("people"),

    el("h2", null, "Known sites (opened in 2026 events)"),
    provLabel(DATA.provenance.shelters),
    table("Sites with status for this hazard", ["#", "Status for this hazard", "Site", "Address", "Why", "Times opened in 2026", ...(hasAccess() ? ["Location check"] : [])],
      sites.map((x) => [x.n, el("span", { class: "status" }, DATA.status_labels[x.st] || "Not located",
        x.dam ? [el("br"), `⚠ ${DATA.state.check_dam}`] : null), x.name, x.address, x.why, x.times_opened_2026, ...(hasAccess() ? [x.loc || "–"] : [])]), [0, 5]),
    source("sites"),
    hasAccess() ? source("access") : null,
    ...careTable(county, hazard, cLabel, hLabel),
    el("p", null, `Candidate public schools usable for this hazard: ${fmt(s.candidate_schools_usable)}. Not every site opens in every event; follow current county announcements.`),

    el("h2", null, "Needs and proposed partners"),
    el("p", null, DATA.meta.role_status, " The pledged column stays blank until a partner confirms it."),
    table("Needs (likely estimate)", ["Need", "How many", "Unit", "Proposed lead", "Proposed support", "Pledged by partner", "Still needed"],
      sc.needs.map((n) => [n[0], fmt(n[1]), n[2], n[3], n[4], n[5] === "" ? "—" : fmt(n[5]), n[6]]), [1]),
    source("needs"),
    el("p", null, el("strong", null, DATA.meta.service_animals)),
    lines.length ? table("Also plan for (county counts, not included in the totals above)", ["Group", "People", "Detail", "Date"],
      lines.map((r) => [r.label, fmt(r.value), r.detail, r.period]), [1]) : null,
    lines.length ? source("county_lines") : null,
    lines.some((r) => r.line === "dam_zones") && hasState() ? el("p", { id: "dam-note" }, DATA.state.dam_note) : null,
    lines.some((r) => r.line === "dam_zones") ? source("dams") : null,
    county === "Maui" ? el("p", null, DATA.meta.kalawao_note) : null,
    el("div", { class: "note" }, el("strong", null, "Who else to plan for"),
      el("ul", null, DATA.meta.who_else.map(([k, v]) => el("li", null, el("strong", null, `${k}: `), linkSources(v))))),

    el("h2", null, "Decision points"),
    el("p", { class: "note" }, DATA.meta.decision_status),
    table("Before, during and after", ["When", "Trigger", "Action", "Owner (proposed)", "Support"],
      DATA.decision_points[hazard].map((d) => [el("strong", null, d[0].toUpperCase()), `${d[1]} (${d[2]})`, d[3], d[4], d[5].replaceAll("; ", ", ")])),
    source("decisions"),

    el("h2", null, "Priority outreach and languages"),
    table("Top 10 Census areas by number of people with needs",
      ["#", C.area, C.at_risk, C.power, C.disability, C.lep, C.no_car, C.needs_total],
      sc.priority_tracts.map((t) => [t.rank, community(t.label_main || t.tract_label, t.label_sub), fmt(t.at_risk_pop), fmt(t.power_dependent), fmt(t.disability),
        fmt(t.limited_english), fmt(t.no_vehicle), fmt(t.afn_need_sum)]), [0, 2, 3, 4, 5, 6, 7]),
    source("people"),
    el("h3", null, "How to reach residents"),
    table("Channels", ["Channel", "Owner (proposed)", "Support (proposed)"], DATA.reach.channels),
    source("reach"),
    ...zeroSirens(county),
    el("p", null, el("strong", null, "Accessible formats for every message:")),
    el("ul", null, DATA.reach.formats.map(([k, v]) => el("li", null, el("strong", null, `${k}: `), v))),
    L.note ? el("p", null, L.note) : null,
    table(`Languages: people age 5 and older who speak English less than “very well” (${L.area})`, ["Language", "People", "Margin of error (90%)"],
      L.rows.map((r) => [r[0], fmt(r[1]), `±${fmt(r[2])}`]), [1, 2]),
    source("languages"),
    el("p", { id: "messages-line" }, DATA.meta.messages_line),
    L.all && L.all.length ? el("details", { class: "all-languages", id: "all-languages" },
      el("summary", null, `All languages (${L.all.length}) – ${L.area}`),
      table(`All languages in the survey for ${L.area}: people age 5 and older who speak English less than “very well”`,
        ["Language", "People", "Margin of error (90%)", "Reliability"],
        L.all.map(([name, people, moe, low]) => [name, people === null ? DATA.meta.too_few : fmt(people),
          moe === null ? "" : `±${fmt(moe)}`, low ? DATA.meta.low_reliability : ""]), [1, 2]),
      el("p", null, `Low reliability: margin of error large compared with the estimate (coefficient of variation above ${Math.round(DATA.meta.cv_limit * 100)}%), or ${DATA.meta.too_few} (fewer than 100 people or 10 survey responses).`)) : null,
    ...resultsSection(),
  );
  showVersion();
}

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
  const S = DATA.stress;
  app.replaceChildren();
  if (!S) { append(app, el("h2", { id: "stress" }, "Stress tests"), el("p", null, "Stress tests are not in this data version.")); return; }
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

/* ---------- results: every number read from data files at build time ---------- */
function resultsSection() {
  const r = DATA.results, b = r.backtest[0];
  const items = [
    el("li", null, el("strong", null, "Coverage: "),
      `${fmt(r.with_cmist)} of ${fmt(r.tracts)} Census areas have needs data (FEMA risk data joined for ${fmt(r.with_nri)} of ${fmt(r.tracts)}). `,
      el("small", null, `Source: ${r.sources.coverage}`)),
    b ? el("li", null, el("strong", null, keep(`Backtest – ${b.event} (${b.date}): `)),
      `observed ${fmt(+b.observed)} people in shelters; model ${fmt(+b.model_low)} / ${fmt(+b.model_central)} / ${fmt(+b.model_high)} (low / likely / high). `,
      b.calibration_event === "True" ? "This is a calibration event, not validation: the high rate was set from it. " : "",
      el("small", null, `Source: ${r.sources.backtest}`)) : null,
  ];
  return [el("h2", { id: "results" }, "Results"), el("ul", { class: "results" }, items)];
}

function fillSelect(id, pairs) {
  const s = document.getElementById(id);
  s.replaceChildren(...pairs.map(([v, label]) => el("option", { value: v }, label)));
}

async function init() {
  window.addEventListener("online", updateBanner);
  window.addEventListener("online", checkForUpdate);
  window.addEventListener("offline", updateBanner);
  updateBanner();
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(() => { /* app still works online */ });
  }
  // show "Loading…" only if the data takes more than 2 s (avoids a layout jump)
  const fb = document.getElementById("fallback");
  const slow = setTimeout(() => { if (!DATA) fb.hidden = false; }, 2000);
  try {
    const res = await fetch(BUNDLE_URL);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    DATA = await res.json();
  } catch (err) {
    clearTimeout(slow);
    fb.querySelector("h2").textContent = "Planning data could not be loaded";
    fb.querySelector("p").textContent = "The printable playbooks at the bottom of the page still work.";
    fb.setAttribute("role", "alert");
    fb.hidden = false;
    return;
  }
  clearTimeout(slow);
  fb.hidden = true;
  fillSelect("county", DATA.counties);
  fillSelect("hazard", DATA.hazards);
  // optional deep link: ?county=Maui&hazard=hurricane (same-page, no request)
  const q = new URLSearchParams(location.search);
  for (const id of ["county", "hazard"]) {
    const v = q.get(id), s = document.getElementById(id);
    if (v && [...s.options].some((o) => o.value === v)) s.value = v;
  }
  for (const id of ["county", "hazard"]) document.getElementById(id).disabled = false;
  document.getElementById("controls").addEventListener("change", () => {
    MSG.county = null;
    const qs = new URLSearchParams(location.search);          // a new view: drop the old area
    qs.set("county", document.getElementById("county").value);
    qs.set("hazard", document.getElementById("hazard").value);
    for (const k of ["area", "site", "rate", "stay", "outage", "trip", "support", "cap"]) qs.delete(k);   // a new view starts from the plan
    history.replaceState(null, "", `?${qs.toString()}${location.hash}`);
    render();
  });
  document.getElementById("controls").addEventListener("submit", (e) => e.preventDefault());
  window.addEventListener("hashchange", onHashChange);
  updateBanner();
  render();
  // deep link: ?county=&hazard=&area=<Census area code> opens the area panel
  const area = q.get("area");
  if (area && currentView() === "plan" && MAP.paths && MAP.paths[area]) openArea(area, null);
  const site = Number(q.get("site"));
  if (site && !area && currentView() === "plan") openSite(site);
  checkForUpdate();
}

init();
