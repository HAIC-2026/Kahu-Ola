// Test helper: drive headless Chrome with real key presses (DevTools protocol, no packages).
// Usage: node tests/keyboard_layers.mjs <chrome> <url>
// Tabs to each map layer checkbox, presses Space, and prints what changed as JSON.
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [chromePath, url] = process.argv.slice(2);
const profile = mkdtempSync(join(tmpdir(), "kahuola-keys-"));
const chrome = spawn(chromePath, ["--headless=new", "--disable-gpu", "--no-first-run",
  `--user-data-dir=${profile}`, "--remote-debugging-port=0", "about:blank"], { stdio: ["ignore", "ignore", "pipe"] });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const wsUrl = await new Promise((resolve, reject) => {
  let buf = "";
  chrome.stderr.on("data", (d) => {
    buf += d;
    const m = buf.match(/DevTools listening on (ws:\/\/\S+)/);
    if (m) resolve(m[1]);
  });
  setTimeout(() => reject(new Error("Chrome did not start")), 20000);
});
const port = new URL(wsUrl).port;
const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r));
let id = 0;
const pending = new Map();
ws.addEventListener("message", (e) => {
  const msg = JSON.parse(e.data);
  if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg.result); pending.delete(msg.id); }
});
const send = (method, params = {}) => new Promise((r) => { id += 1; pending.set(id, r); ws.send(JSON.stringify({ id, method, params })); });
const evaluate = async (expr) => (await send("Runtime.evaluate", { expression: expr, returnByValue: true })).result.value;
const key = async (k, code, keyCode) => {
  await send("Input.dispatchKeyEvent", { type: "keyDown", key: k, code, windowsVirtualKeyCode: keyCode });
  await send("Input.dispatchKeyEvent", { type: "keyUp", key: k, code, windowsVirtualKeyCode: keyCode });
};

const out = {};
try {
  await send("Page.navigate", { url });
  for (let i = 0; i < 50 && !(await evaluate("Boolean(document.getElementById('layer-care'))")); i++) await sleep(200);
  for (const name of ["outside", "care"]) {
    const target = `layer-${name}`;
    let tabs = 0;
    while (tabs < 200 && (await evaluate("document.activeElement && document.activeElement.id")) !== target) {
      await key("Tab", "Tab", 9); tabs += 1;
    }
    const layer = name === "outside" ? ".layer-outside" : ".layer-care";
    const before = await evaluate(`[document.getElementById('${target}').checked, document.querySelector('${layer}').getAttribute('display')]`);
    await key(" ", "Space", 32);
    await sleep(100);
    const after = await evaluate(`[document.getElementById('${target}').checked, document.querySelector('${layer}').getAttribute('display')]`);
    out[name] = { reached: tabs < 200, before, after,
      label: await evaluate(`document.querySelector('label[for=${target}]').textContent`) };
  }
} finally {
  console.log(JSON.stringify(out));
  ws.close();
  chrome.kill();
  await sleep(300);
  rmSync(profile, { recursive: true, force: true });
}
