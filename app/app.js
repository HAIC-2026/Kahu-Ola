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
  "check": ["triangle", "Check flood risk"],
  "check (tract-level)": ["triangle", "Check flood risk"],
  "undetermined": ["diamond", "Flood risk not mapped (FEMA zone D)"],
  "exclude": ["square", "Not for this hazard"],
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
  const names = needNames(bounds.length);
  let lo = 0;
  bounds.forEach((b, i) => {
    const sw = svg("svg", { width: 28, height: 16, "aria-hidden": "true" });
    sw.append(svg("rect", { width: 28, height: 16, fill: css(RAMP[i]), stroke: "#000" }));
    legend.append(el("li", null, sw, names[i], " ", el("small", null, `(${fmt(lo)}–${fmt(b)} people)`)));
    lo = b;
  });
  const outline = (dashed, text) => {
    const sw = svg("svg", { width: 28, height: 16, "aria-hidden": "true" });
    sw.append(svg("rect", dashed ? { width: 28, height: 16, fill: "#fff", stroke: "#9a9a9a", "stroke-dasharray": "2,2" }
      : { width: 28, height: 16, fill: "#fff", stroke: "#000", "stroke-width": "2" }));
    return el("li", null, sw, text);
  };
  legend.append(outline(false, "Solid outline: Census area in the risk area"));
  legend.append(outline(true, "Dashed outline: outside the risk area"));
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
  return [el("div", { class: "mapwrap" }, el("div", { class: "map" }, root),
    el("div", null, el("h3", null, "Site key"), key)), legend];
}

function needNames(k) {
  if (k <= 1) return ["People with needs"];
  if (k === DATA.meta.need_names.length) return DATA.meta.need_names;
  return ["Lowest need", ...Array(k - 2).fill("Middle"), "Highest need"];
}

/* community name first, Census area ID as a smaller second line */
function community(main, sub) {
  return [el("span", null, main), el("br"), el("small", null, sub || "")];
}
const source = (key) => el("p", { class: "src" }, DATA.meta.sources[key]);

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
    el("p", null, `The share of people in the risk area who may go to a public shelter: low ${pct(s.rate_low)}, likely ${pct(s.rate_central)}, high ${pct(s.rate_high, 1)}. Where the rates come from: ${DATA.meta.rate_note[hazard]}`),
    el("h3", null, "Who has access and functional needs (CMIST)"),
    el("ul", null, DATA.meta.cmist.map(([k, v]) => el("li", null, el("strong", null, `${k}: `), v))),
    el("h3", null, "County total vs. one community"),
    el("p", null, `The county total counts ${area} as hit at the same time, so it is an upper bound. Use the “Largest single community” table to plan for an event that hits one community.`),
    el("h3", null, "Map"),
    el("p", null, "Darker blue means more people with needs, from “Lowest need” to “Highest need”. A solid outline marks a Census area in the risk area; a dashed outline is outside it. Symbols: ○ usable site, △ check flood risk, ◇ flood risk not mapped, ☒ not for this hazard. Numbers on the map match the site key."),
    el("h3", null, "Why population numbers can differ"),
    el("p", null, "People in the risk area come from ACS 2018–2022 estimates (through the CDC Social Vulnerability Index 2022). Community names use 2020 Census counts. County totals in the plan use Census estimates for 2025. Each table names its source underneath."),
    el("p", { class: "note" }, el("strong", null, "Every number is a planning estimate. In an event, follow county announcements.")));
  return el("details", { class: "help", id: "help" },
    el("summary", null, el("span", { class: "help-icon", "aria-hidden": "true" }, "?"), " How to read this page"),
    ...body);
}

/* ---------- navigation: Plan · Messages · How AI built this ---------- */
const VIEWS = { plan: "Plan", messages: "Messages", ai: "How AI built this" };
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
  else if (view === "ai") renderAI();
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
  const kind = status.startsWith("NEEDS HUMAN") ? "badge human" : status.startsWith("DRAFT") ? "badge draft" : "badge";
  return el("span", { class: kind }, status || "(no status)");
}

function renderMessages() {
  const app = document.getElementById("app");
  if (MSG.county === null) MSG.county = document.getElementById("county").value;
  const all = DATA.messages, ai = DATA.ai;
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

  const counts = table("Messages by language (counted when the site was built)",
    ["Language", "Messages", "AI drafts", "Need a human translator", "Approved", "Review assigned to"],
    ai.message_counts.map((c) => [c.label,
      fmt(c.rows), fmt(c.drafts), fmt(c.placeholders), fmt(c.approved), c.assignee || "—"]), [1, 2, 3, 4]);

  const cards = shown.map((m) => el("article", { class: "msg" },
    el("header", null,
      el("strong", null, `${m.language_label} · ${hz[m.hazard] || m.hazard} · ${m.phase}`),
      " ", el("small", null, `${m.message_id} · trigger: ${m.trigger.replaceAll("_", " ")} · ${m.timing}`),
      countyLangs.has(m.language) ? el("span", { class: "tag" }, `In ${cLabel}'s list`) : null),
    m.text ? el("p", { class: "msg-text", lang: m.lang || null }, m.text)
      : el("p", { class: "msg-text empty" }, "No text: this language needs a human translator."),
    el("dl", { class: "msg-meta" },
      el("dt", null, "Status"), el("dd", null, badge(m.status)),
      el("dt", null, "Drafted by"), el("dd", null, m.translated_by || "—"),
      el("dt", null, "Review assigned to"), el("dd", null, m.review_assignee || "—"),
      el("dt", null, "Reviewed by"), el("dd", null, m.reviewed_by || "—"),
      el("dt", null, "Review date"), el("dd", null, m.review_date || "—"),
      el("dt", null, "Approved"), el("dd", null, m.approved || "—"),
      m.notes ? [el("dt", null, "Notes"), el("dd", null, m.notes)] : null),
    copyButton(m.text)));

  app.replaceChildren(
    el("h2", { id: "messages" }, "Messages: every AI draft, unedited"),
    el("p", { class: "note" }, el("strong", null, `Approved: ${fmt(ai.messages_approved)} of ${fmt(ai.messages_total)}. `),
      "These are drafts for county review. Do not send any message until a native speaker and the county have approved it."),
    el("p", null, "The message library is statewide: every county uses the same texts. Filters only narrow the list; nothing is left out by default."),
    counts,
    el("p", { class: "src" }, ai.counted_note),
    filters,
    el("p", { role: "status" }, `Showing ${fmt(shown.length)} of ${fmt(all.length)} messages.`),
    ...cards);
}

/* ---------- How AI built this plan ---------- */
function evidenceLinks(items) {
  return items.flatMap(([name, url], i) => [i ? el("br") : null,
    el("a", { href: url, rel: url.startsWith("#") ? null : "noopener noreferrer" }, name)]);
}

function renderAI() {
  const ai = DATA.ai;
  document.getElementById("app").replaceChildren(
    el("h2", { id: "ai" }, "How AI built this plan"),
    el("p", null, "Everything AI contributed is listed here, with what people checked and where to see the evidence. No AI runs in this app: it works offline and makes no calls to AI services."),
    el("ul", { class: "kpis" },
      el("li", null, "Commits in the repository", el("b", null, fmt(ai.commits))),
      el("li", null, "Commits co-authored by Claude", el("b", null, fmt(ai.coauthored))),
      el("li", null, "Automated tests", el("b", null, fmt(ai.tests))),
      el("li", null, "Message drafts approved", el("b", null, `${fmt(ai.messages_approved)} of ${fmt(ai.messages_total)}`))),
    table("What AI did and what people checked", ["Task", "What AI did", "What people checked", "Evidence"],
      ai.tasks.map((x) => [el("strong", null, x.task), x.ai, x.people, evidenceLinks(x.evidence)])),
    el("h3", null, "What AI does NOT do"),
    el("ul", { class: "notdone" }, ai.not_done.map(([k, v]) => el("li", null, el("strong", null, `${k}. `), v))),
    el("p", { class: "src" }, ai.counted_note));
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
  if (hazard === "tsunami") kpis.push(["People in the extreme tsunami zone (worst case)", fmt(s.at_risk_pop_extreme_zone)]);
  const area = DATA.meta.footprint_text[s.footprint_rule] || s.footprint_rule;
  const largestTitle = "Largest single community (the Census areas with the most people who may need a shelter)";

  const L = DATA.languages[county];
  app.append(
    el("h2", { id: "summary" }, `${cLabel} – ${hLabel}`),
    el("p", null, el("strong", null, `Data as of ${DATA.meta.data_as_of}. `), DATA.meta.disclaimer),
    helpPanel(sc, hazard),
    provLabel(DATA.provenance.numbers, DATA.provenance.sources_url),
    el("p", null, el("a", { class: "button", href: sc.playbook }, `⬇ Printable playbook (PDF): ${cLabel} – ${hLabel}`)),
    el("ul", { class: "kpis" }, kpis.map(([k, v]) => el("li", null, k, el("b", null, v)))),
    source("summary"),
    el("p", null, `Share of people in the risk area who may need a public shelter: low ${pct(s.rate_low)}, likely ${pct(s.rate_central)}, high ${pct(s.rate_high, 1)}. One person can be counted in more than one need. Open “How to read this page” for an explanation.`),

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

    el("h2", null, "Map: people with needs and known sites"),
    ...renderMap(county, sc, sites, `${cLabel} ${hLabel}: people with needs by Census area and known shelter sites`),
    el("p", null, "Color = people in the risk area who speak English less than well, use power-dependent medical equipment, have a disability, or live without a car (a person can be counted more than once). No street map: Census area outlines only. Hover over an area to see its name."),
    source("people"),

    el("h2", null, "Known sites (opened in 2026 events)"),
    provLabel(DATA.provenance.shelters),
    table("Sites with status for this hazard", ["#", "Status for this hazard", "Site", "Address", "Why", "Times opened in 2026"],
      sites.map((x) => [x.n, el("span", { class: "status" }, DATA.status_labels[x.st] || "Not located"), x.name, x.address, x.why, x.times_opened_2026]), [0, 5]),
    source("sites"),
    el("p", null, `Candidate public schools usable for this hazard: ${fmt(s.candidate_schools_usable)}. Not every site opens in every event; follow current county announcements.`),

    el("h2", null, "Needs and proposed partners"),
    el("p", null, DATA.meta.role_status, " The pledged column stays blank until a partner confirms it."),
    table("Needs (likely estimate)", ["Need", "How many", "Unit", "Proposed lead", "Proposed support", "Pledged by partner", "Still needed"],
      sc.needs.map((n) => [n[0], fmt(n[1]), n[2], n[3], n[4], n[5] === "" ? "—" : fmt(n[5]), n[6]]), [1]),
    source("needs"),

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
    L.note ? el("p", null, L.note) : null,
    table(`Languages: people age 5 and older who speak English less than “very well” (${L.area})`, ["Language", "People", "Margin of error (90%)"],
      L.rows.map((r) => [r[0], fmt(r[1]), `±${fmt(r[2])}`]), [1, 2]),
    source("languages"),
    el("p", null, DATA.meta.privacy),
  );
  showVersion();
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
  document.getElementById("controls").addEventListener("change", () => { MSG.county = null; render(); });
  window.addEventListener("hashchange", render);
  document.getElementById("menu").hidden = false;
  document.getElementById("controls").addEventListener("submit", (e) => e.preventDefault());
  document.getElementById("fallback").hidden = true;
  document.getElementById("app").hidden = false;
  updateBanner();
  render();
  checkForUpdate();
}

init();
