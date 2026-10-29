#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – three public State layers, downloaded at BUILD TIME ONLY.

Free public ArcGIS services (no token, no credits). For each layer the geoportal / ArcGIS
Online item is looked up first and its underlying feature service is queried; only the
fields listed below are requested (no phone numbers, owners, parcel numbers or live siren
status). Raw downloads go to data/raw/state_layers/ (gitignored); build_state_layers.py
turns them into the committed summary the app and the PDFs read.

  childcare  Ready Keiki Locator, "All Pre-K Sites" (Office of the Lieutenant Governor,
             hosted by Hawaiʻi Statewide GIS): licensed group child care (PATCH), public
             pre-K (EOEL) and charter pre-K sites
  sirens     HI-EMA public siren layer (all-hazard outdoor warning sirens): locations only
  dams       State of Hawaiʻi dam evacuation zones (hosted by Hawaiʻi Statewide GIS)

Usage:  python3 scripts/fetch_state_layers.py
"""
from __future__ import annotations

import json
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import fetch_json  # noqa: E402
from hawaii_time import now_hst  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "state_layers"
ITEM_URL = "https://www.arcgis.com/sharing/rest/content/items/{}?f=json"
LAYERS = {
    "childcare": {
        "item": "5486617da05241cc93e5a33c1f1b5133",
        "web_map": "221ce0935c884aebb730664ff46c688a",      # "Ready Keiki" (the locator map)
        "layer": 0,
        "fields": ["name", "site_type", "street_address", "city", "notes"],
        "title": "Ready Keiki Locator – All Pre-K Sites (Office of the Lieutenant Governor, "
                 "hosted by Hawaiʻi Statewide GIS)",
    },
    "sirens": {
        "item": "912539122be443b9a4a9781644e6a4f0",
        "web_map": "51e8c8de58f94662959d8d61e543a9f6",      # HI-EMA public siren map
        "layer": 0,
        "fields": ["Siren_Iden", "Location", "Permanent_Mobile"],   # no live status
        "title": "Hawaiʻi Emergency Management Agency – all-hazard outdoor warning sirens "
                 "(public siren layer; locations only)",
    },
    "dams": {
        "item": "fd89058573f4409cacb6f5c58bbb5165",
        "web_map": "0c30e60f2c764f58b64b3f9ef83201fd",      # State of Hawaii Dam Evacuation Zones
        "layer": 0,
        "fields": ["nid_id", "dam_name", "island", "county", "hazard"],   # no owner / TMK
        "title": "State of Hawaiʻi dam evacuation zones (hosted by Hawaiʻi Statewide GIS)",
    },
}
SIREN_RADIUS = {          # official audible radius (manufacturer rating, published by HI-EMA)
    "feet": 3400,
    "metres": 1036,
    "source": "Hawaiʻi Emergency Management Agency, All-Hazards Statewide Outdoor Warning "
              "Siren System: \"The sirens output is 121 decibels and propagate with a "
              "manufacture radius of 3,400 feet. This range may vary due to environmental "
              "and surrounding physical conditions.\"",
    "url": "https://dod.hawaii.gov/hiema/all-hazard-statewide-outdoor-warning-siren-system/",
}


def item_info(item_id: str) -> dict:
    d = fetch_json(ITEM_URL.format(item_id))
    return {"item_id": item_id, "item_title": d.get("title", ""), "owner": d.get("owner", ""),
            "org_id": d.get("orgId", ""), "service_url": d.get("url", ""),
            "item_modified": datetime.fromtimestamp(d.get("modified", 0) / 1000,
                                                    timezone.utc).strftime("%Y-%m-%d"),
            "item_page": f"https://www.arcgis.com/home/item.html?id={item_id}"}


def download(url: str, fields: list) -> list:
    out, offset = [], 0
    while True:
        q = urllib.parse.urlencode({"where": "1=1", "outFields": ",".join(fields),
                                    "outSR": "4326", "f": "geojson",
                                    "resultOffset": offset, "resultRecordCount": 1000})
        page = fetch_json(f"{url}/query?{q}")
        if "error" in page:
            raise RuntimeError(f"{url}: {page['error']}")
        feats = page.get("features", [])
        out += feats
        if len(feats) < 1000:
            return out
        offset += len(feats)


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    meta = {}
    for key, src in LAYERS.items():
        info = item_info(src["item"])
        url = f"{info['service_url'].rstrip('/')}/{src['layer']}"
        feats = download(url, src["fields"])
        for f in feats:                       # keep only the requested fields
            f["properties"] = {k: f["properties"].get(k) for k in src["fields"]}
        meta[key] = {**info, "layer_url": url, "title": src["title"],
                     "web_map": f"https://www.arcgis.com/home/item.html?id={src['web_map']}",
                     "fields": src["fields"], "features": len(feats), "fetched_at": now_hst()}
        (RAW / f"{key}.geojson").write_text(json.dumps(
            {"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")
        print(f"{key}: {len(feats)} features from {url}")
    meta["siren_radius"] = SIREN_RADIUS
    (RAW / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
