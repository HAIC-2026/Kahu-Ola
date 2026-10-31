// Test helper: open app views in headless Chrome (DevTools protocol, no packages) and report
// what each view shows: JS errors, requests to any other origin, bad words in the visible
// text, horizontal scroll, page background; optionally run a script after load, and check
// the same views again with the network cut (offline, from the service worker cache).
// Usage: node tests/views_check.mjs <chrome> <json: {urls, width, scheme, offline, after}>
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [chromePath, raw] = process.argv.slice(2);
const opt = JSON.parse(raw);
const profile = mkdtempSync(join(tmpdir(), "kahuola-views-"));
const chrome = spawn(chromePath, ["--headless=new", "--disable-gpu", "--no-first-run",
  `--user-data-dir=${profile}`, "--remote-debugging-port=0", "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const wsUrl = await new Promise((resolve, reject) => {
  let buf = "";
  chrome.stderr.on("data", (d) => { buf += d; const m = buf.match(/DevTools listening on (ws:\/\/\S+)/); if (m) resolve(m[1]); });
  setTimeout(() => reject(new Error("Chrome did not start")), 20000);
});
const port = new URL(wsUrl).port;
const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0; const pending = new Map(); let events = [];
ws.addEventListener("message", (e) => {
  const m = JSON.parse(e.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m.result || m.error); pending.delete(m.id); }
  else if (m.method) events.push(m);
});
const send = (method, params = {}) => new Promise((r) => { id += 1; pending.set(id, r); ws.send(JSON.stringify({ id, method, params })); });
const evaluate = async (expr) => (await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true })).result.value;
await send("Runtime.enable"); await send("Network.enable"); await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", { width: opt.width || 390, height: 900, deviceScaleFactor: 1, mobile: (opt.width || 390) < 500 });
await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-color-scheme", value: opt.scheme || "light" }] });

const INFO = `(() => {
  const t = document.body.innerText;
  return { title: document.title, h2: [...document.querySelectorAll('main h2')].map((x) => x.textContent),
    bad: t.match(/\\b(null|undefined|NaN)\\b|\\[object/g) || [],
    overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
    bg: getComputedStyle(document.body).backgroundColor, color: getComputedStyle(document.body).color,
    disclaimer: document.querySelector('.disclaimer') ? document.querySelector('.disclaimer').innerText : '',
    text: t.slice(0, 200000) };
})()`;

async function visit(url) {
  events = [];
  await send("Page.navigate", { url });
  await sleep(opt.wait || 3000);
  let after = null;
  if (opt.after) { after = await evaluate(opt.after); await sleep(600); }
  const info = await evaluate(INFO);
  const errors = events.filter((e) => e.method === "Runtime.exceptionThrown" ||
    (e.method === "Runtime.consoleAPICalled" && e.params.type === "error")).map((e) => JSON.stringify(e.params).slice(0, 300));
  const origin = new URL(url).origin;
  const outside = events.filter((e) => e.method === "Network.requestWillBeSent").map((e) => e.params.request.url)
    .filter((u) => !u.startsWith(origin) && !u.startsWith("data:") && !u.startsWith("blob:"));
  return { url, ...info, after, errors, outside };
}

const out = { online: [], offline: [] };
for (const url of opt.urls) out.online.push(await visit(url));
if (opt.offline) {
  await sleep(1500);                                   // let the service worker finish caching
  await send("Network.emulateNetworkConditions", { offline: true, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  for (const url of opt.urls) out.offline.push(await visit(url));
}
console.log(JSON.stringify(out));
ws.close(); chrome.kill(); await sleep(300);
try { rmSync(profile, { recursive: true, force: true }); } catch { /* temp profile */ }
process.exit(0);
