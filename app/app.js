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
};
const LAYERS = { outside: true, care: true };     // map layer checkboxes (kept across views)
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

function table(caption, headers, rows, numCols = []) {
  const head = el("tr", null, headers.map((h, i) =>
    el("th", { scope: "col", class: numCols.includes(i) ? "num" : null }, h)));
  const body = rows.map((r) => el("tr", null, r.map((c, i) =>
    el("td", { class: numCols.includes(i) ? "num" : null }, c))));
  const name = Array.isArray(caption) ? caption[0] : caption;
  return el("div", { class: "table-wrap", tabindex: "0", role: "region", "aria-label": name },
    el("table", null, el("caption", null, caption), el("thead", null, head), el("tbody", null, body)));
}

/* ---------- offline banner ---------- */
function updateBanner() {
  const b = document.getElementById("offline");
  const asOf = DATA ? DATA.meta.data_as_of : "last download";
  b.textContent = `Offline – data as of ${asOf}`;
  b.hidden = navigator.onLine;
}

/* ---------- data version and update notice ---------- */
function showVersion() {
  const text = `Data version ${DATA.meta.version} · Data as of ${DATA.meta.data_as_of}`;
  document.getElementById("dataver").textContent = text;
  document.getElementById("version").textContent = text;
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
  b.replaceChildren(`New planning data available (data as of ${latest.data_as_of}) – `, btn);
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

  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, role: "img", "aria-labelledby": "map-title" });
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
    const tip = svg("title"); tip.textContent = `${tr.l || tr.f} – ${level(tr.f)}`; path.append(tip);
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
      const w = svg("text", { x: 6, y: -4, "font-size": "13", "font-weight": "bold", stroke: "#ffffff", "stroke-width": "3", "paint-order": "stroke", class: "zone-flag" });
      w.textContent = "⚠"; g.append(w);
    }
    const tip = svg("title");
    tip.textContent = `${f.n} – ${DATA.access.types[f.t]}${zone ? ` – inside: ${zone}` : zone === "" ? " – outside this hazard's zone" : ""}`;
    g.append(tip);
    marks.push(g); careLayer.append(g);
  }
  if (facilities.length) root.append(careLayer);
  for (const s of sites) {
    if (s.lon === null) continue;
    const [x, y] = proj(s.lon, s.lat);
    const g = svg("g", { class: "site", transform: `translate(${x} ${y}) scale(1)` });
    g.dataset.x = x; g.dataset.y = y;
    g.append(markerShape((MARKERS[s.st] || MARKERS.ok)[0], 0, 0));
    const lab = svg("text", { x: 10, y: 4, "font-size": "13", "font-weight": "bold",
      stroke: "#ffffff", "stroke-width": "3", "paint-order": "stroke" });
    lab.textContent = s.n; g.append(lab);
    marks.push(g); root.append(g);
  }
  Object.assign(MAP, { root, W, H, proj, paths, marks, tracts, county, sc, sites, hazard, level,
    hatches: [[hatch, 8, 1.5], [hatch2, 6, 1.2]], view: [0, 0, W, H] });

  const legend = el("ul", { class: "legend", "aria-label": "Map legend" });
  let lo = 0;
  bounds.forEach((b, i) => {
    const sw = svg("svg", { width: 28, height: 16, "aria-hidden": "true" });
    sw.append(svg("rect", { width: 28, height: 16, fill: css(RAMP[i]), stroke: "#000" }));
    legend.append(el("li", null, sw, names[i], " ", el("small", null, `(${fmt(lo)}–${fmt(b)} people)`)));
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
  if (facilities.some((f) => facilityZone(f, hazard))) legend.append(el("li", null, el("span", { class: "legend-glyph", "aria-hidden": "true" }, "⚠"), "Care facility inside this hazard's zone"));
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
      const b = el("button", { type: "button", class: "linklike" }, `${tr.l || tr.f}: ${fmt(afn[tr.f])} people with needs (${level(tr.f)})`);
      b.addEventListener("click", () => openArea(tr.f, b));
      return el("li", null, b);
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
    return el("label", { for: id, class: "check" }, box, ` ${label} (${fmt(count)})`);
  };
  const layers = access ? el("fieldset", { class: "layers" }, el("legend", null, "Map layers"),
    layerBox("outside", `${DATA.access.no_activated} – sites usable for ${hzLow}`, outsideLayer, outside.length),
    el("p", { class: "layer-note", id: "scenario-note" }, `With DOE candidate schools usable for ${hzLow}: ${fmt(counts[1])} of ${fmt(counts[2])} areas (2026 activated sites only: ${fmt(counts[0])}). ${DATA.access.not_no_shelter}`),
    layerBox("care", "Care facilities", careLayer, facilities.length)) : null;
  return [el("p", null, official), layers,
    el("div", { class: "mapwrap" }, el("div", { class: "map" }, root),
      el("div", null, el("h3", null, "Site key"), key)),
    el("p", { class: "hint" }, "Select a Census area on the map, or open one from the list below the legend."),
    panel, legend, areas,
    access ? el("p", { class: "src" }, `${DATA.access.source} ${DATA.access.attribution} ${DATA.access.outside_method}`) : null];
}

/* ---------- zoom: animate the SVG viewBox; markers keep their size ---------- */
function setView(v) {
  MAP.view = v;
  MAP.root.setAttribute("viewBox", v.map((x) => x.toFixed(1)).join(" "));
  const k = v[2] / MAP.W;
  for (const g of MAP.marks) g.setAttribute("transform", `translate(${g.dataset.x} ${g.dataset.y}) scale(${k.toFixed(3)})`);
  // keep the hatches the same on screen at any zoom
  for (const [pat, size, width] of MAP.hatches) {
    const s = (size * k).toFixed(2), line = pat.firstChild;
    pat.setAttribute("width", s); pat.setAttribute("height", s);
    line.setAttribute("y2", s);
    line.setAttribute("stroke-width", (width * k).toFixed(2));
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
    el("h3", { id: "area-title", tabindex: "-1" }, main, " ", el("small", null, sub || "")),
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
    careInArea(f, hazard),
    el("p", null, el("strong", null, "Proposed partners: "), `lead – ${[...lead].join(", ") || "—"}; support – ${[...support].join(", ") || "—"}. `, DATA.meta.role_status),
    el("p", null, el("strong", null, `Top languages (${L.area}): `), langs.map((r) => `${r[0]} ${fmt(r[1])}`).join("; ") || "—"),
    el("p", null, el("strong", null, "Messages: "), msgLink(`all ${hz.toLowerCase()} messages`),
      langs.filter((r) => msgLangs.has(r[0])).map((r) => [", ", msgLink(r[0], DATA.messages.find((m) => m.language_label === r[0]).language)])),
    el("p", { class: "panel-actions" }, back, " ", print));
  panel.hidden = false;
  const q = new URLSearchParams(location.search);
  q.set("county", county); q.set("hazard", hazard); q.set("area", f);
  history.replaceState(null, "", `?${q.toString()}${location.hash}`);
  document.getElementById("area-title").focus();
}

function closeArea() {
  const panel = document.getElementById("area-panel");
  if (panel) { panel.hidden = true; panel.replaceChildren(); }
  for (const p of Object.values(MAP.paths || {})) p.classList.remove("selected");
  if (MAP.root) zoomTo([0, 0, MAP.W, MAP.H]);
  const q = new URLSearchParams(location.search); q.delete("area");
  history.replaceState(null, "", `?${q.toString()}${location.hash}`);
  const back = OPENER && document.contains(OPENER) ? OPENER : document.getElementById("map-title");
  if (back && back.focus) back.focus();
  OPENER = null;
}

window.addEventListener("afterprint", () => document.body.classList.remove("print-area"));

function needNames(k) {
  if (k <= 1) return ["People with needs"];
  if (k === DATA.meta.need_names.length) return DATA.meta.need_names;
  return ["Lowest need", ...Array(k - 2).fill("Middle"), "Highest need"];
}

/* community name first, Census area ID as a smaller second line */
function community(main, sub) {
  return [el("span", null, main), el("br"), el("small", null, sub || "")];
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
      el("p", null, `Read it as: about ${fmt(ex.at_risk_pop)} people live in the risk area of ${ex.label_main}. If this hazard hits, between ${fmt(ex.low)} and ${fmt(ex.high)} of them may need a public shelter; ${fmt(ex.central)} is the likely number.`));
  }
  body.push(
    el("h3", null, "Census area"),
    el("p", null, "A neighborhood-sized area the U.S. Census uses, usually 1,200–8,000 people. The number (for example “Census area 308”) is its Census ID. Each area is named after the Census place where most of its people live; “near” means no one in the area lives inside a named place, and “rural near” means most people live outside named places."),
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
const VIEWS = { plan: "Plan", messages: "Messages" };
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
  document.getElementById("controls").hidden = view !== "plan";
  if (view === "messages") renderMessages();
  else renderPlan();
  showVersion();
}

const provLabel = (text, link) => {
  const [before, after] = link ? text.split("see Sources") : [text];
  return el("p", { class: "prov" }, before,
    link ? [el("a", { href: link, rel: "noopener noreferrer" }, "see Sources"), after] : null);
};

/* ---------- Messages: every stored message row, filters only narrow ---------- */
const MSG = { county: null, onlyCounty: false, hazard: "", phase: "", language: "" };

function msgSelect(label, key, pairs) {
  const id = `msg-${key}`;
  const s = el("select", { id, name: key }, pairs.map(([v, t]) => el("option", { value: v }, t)));
  s.value = MSG[key] ?? "";
  s.addEventListener("change", () => { MSG[key] = s.value; renderMessages(); });
  return [el("label", { for: id }, label), s];
}

function copyButton(text) {
  if (!text) return el("button", { type: "button", class: "button", disabled: "" }, "No text yet");
  const b = el("button", { type: "button", class: "button" }, "Copy");
  b.addEventListener("click", async () => {
    try { await navigator.clipboard.writeText(text); b.textContent = "Copied"; }
    catch (err) { b.textContent = "Select the text to copy"; }
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
      el("dt", null, "Review date"), el("dd", null, m.review_date || "—"),
      el("dt", null, "Approved"), el("dd", null, m.approved || "—"),
      m.notes ? [el("dt", null, "Notes"), el("dd", null, m.notes)] : null),
    copyButton(m.text)));

  app.replaceChildren();
  append(app,
    el("h2", { id: "messages" }, "Messages"),
    el("p", { class: "note" }, el("strong", null, `Reviewed: ${fmt(reviewed)} of ${fmt(all.length)}. `),
      "These are drafts for county review. Do not send any message until a native speaker and the county have reviewed it."),
    el("p", null, "The message library is statewide: every county uses the same texts. Filters only narrow the list; nothing is left out by default."),
    counts,
    filters,
    el("p", { role: "status" }, `Showing ${fmt(shown.length)} of ${fmt(all.length)} messages.`),
    ...cards);
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
    el("ul", { class: "kpis" }, kpis.map(([k, v]) => el("li", null, k, el("b", null, v)))),
    source("summary"),
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
      sites.map((x) => [x.n, el("span", { class: "status" }, DATA.status_labels[x.st] || "Not located"), x.name, x.address, x.why, x.times_opened_2026, ...(hasAccess() ? [x.loc || "–"] : [])]), [0, 5]),
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
    el("p", null, el("strong", null, "Accessible formats for every message:")),
    el("ul", null, DATA.reach.formats.map(([k, v]) => el("li", null, el("strong", null, `${k}: `), v))),
    L.note ? el("p", null, L.note) : null,
    table(`Languages: people age 5 and older who speak English less than “very well” (${L.area})`, ["Language", "People", "Margin of error (90%)"],
      L.rows.map((r) => [r[0], fmt(r[1]), `±${fmt(r[2])}`]), [1, 2]),
    source("languages"),
    ...resultsSection(),
  );
  showVersion();
}

/* ---------- results: every number read from data files at build time ---------- */
function resultsSection() {
  const r = DATA.results, b = r.backtest[0], t = r.rebuild, base = r.baseline;
  const items = [
    el("li", null, el("strong", null, "Coverage: "),
      `${fmt(r.with_cmist)} of ${fmt(r.tracts)} Census areas have needs data (FEMA risk data joined for ${fmt(r.with_nri)} of ${fmt(r.tracts)}). `,
      el("small", null, `Source: ${r.sources.coverage}`)),
    b ? el("li", null, el("strong", null, `Backtest – ${b.event} (${b.date}): `),
      `observed ${fmt(+b.observed)} people in shelters; model ${fmt(+b.model_low)} / ${fmt(+b.model_central)} / ${fmt(+b.model_high)} (low / likely / high). `,
      b.calibration_event === "True" ? "This is a calibration event, not validation: the high rate was set from it. " : "",
      el("small", null, `Source: ${r.sources.backtest}`)) : null,
    t ? el("li", null, el("strong", null, "Time: "),
      `a full rebuild from local data (${fmt(t.steps)} steps, ${fmt(t.scenarios)} scenarios, ${fmt(t.playbooks)} playbooks) took ${t.seconds} seconds on ${t.machine} (${t.measured_at.slice(0, 10)}). Team-assumed baseline without this tool: ${base.value} ${base.unit}. `,
      el("small", null, `Sources: ${r.sources.rebuild}; ${r.sources.baseline} (${base.source})`)) : null,
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
    qs.delete("area");
    history.replaceState(null, "", `?${qs.toString()}${location.hash}`);
    render();
  });
  document.getElementById("controls").addEventListener("submit", (e) => e.preventDefault());
  window.addEventListener("hashchange", render);
  updateBanner();
  render();
  // deep link: ?county=&hazard=&area=<Census area code> opens the area panel
  const area = q.get("area");
  if (area && currentView() === "plan" && MAP.paths && MAP.paths[area]) openArea(area, null);
  checkForUpdate();
}

init();
