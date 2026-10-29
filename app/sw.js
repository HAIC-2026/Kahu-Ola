/* Hawaiʻi ESF-6 Planning – service worker.
   Pre-caches the app shell, the data bundle and all 20 PDF playbooks so the app works
   in airplane mode after the first load. Same-origin requests only: requests to any
   other origin are never handled or made here. */
"use strict";

// BEGIN GENERATED
const VERSION = "59ba75503b35";
const PRECACHE = [
  "./",
  "index.html",
  "app.js",
  "styles.css",
  "manifest.webmanifest",
  "icon.svg",
  "icon-180.png",
  "icon-192.png",
  "icon-512.png",
  "data/bundle.json",
  "data/version.json",
  "playbooks/hawaii_coastal_flood.pdf",
  "playbooks/hawaii_hurricane.pdf",
  "playbooks/hawaii_inland_flood.pdf",
  "playbooks/hawaii_tsunami.pdf",
  "playbooks/hawaii_wildfire.pdf",
  "playbooks/honolulu_coastal_flood.pdf",
  "playbooks/honolulu_hurricane.pdf",
  "playbooks/honolulu_inland_flood.pdf",
  "playbooks/honolulu_tsunami.pdf",
  "playbooks/honolulu_wildfire.pdf",
  "playbooks/kauai_coastal_flood.pdf",
  "playbooks/kauai_hurricane.pdf",
  "playbooks/kauai_inland_flood.pdf",
  "playbooks/kauai_tsunami.pdf",
  "playbooks/kauai_wildfire.pdf",
  "playbooks/maui_coastal_flood.pdf",
  "playbooks/maui_hurricane.pdf",
  "playbooks/maui_inland_flood.pdf",
  "playbooks/maui_tsunami.pdf",
  "playbooks/maui_wildfire.pdf"
];
// END GENERATED

const CACHE = `esf6-${VERSION}`;

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith("esf6-") && k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.endsWith("/data/version.json")) {
    // network first: the page compares it with the cached bundle to spot new data
    event.respondWith(fetch(req).catch(() => caches.match(req, { ignoreSearch: true })));
    return;
  }
  event.respondWith(
    caches.match(req, { ignoreSearch: true }).then((hit) => hit || fetch(req).catch(() =>
      req.mode === "navigate" ? caches.match("index.html")
        : new Response("Offline and not cached", { status: 503, statusText: "Offline" }))));
});
