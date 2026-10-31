#!/usr/bin/env python3
"""
HAIC 2026 – Team Kahu Ola – State Hub reference layers, downloaded at BUILD TIME ONLY.

Free public services (no token, no credits). Only the fields listed below are requested;
the PDC shelter layer is requested WITHOUT its phone and contact fields, so they never reach
data/raw/. Raw downloads go to data/raw/hub/ (gitignored); build_hub_layers.py turns them
into the committed summary the app, the stress tests and the PDFs read.

  safe_zones        Hawaiʻi Statewide GIS, Hazards MapServer layer 13 "Tsunami Safe Zones"
                    (Hawaiʻi, Oʻahu, Kauaʻi county data 2025; Maui County data 2013)
  fire_risk         Hawaiʻi Statewide GIS, Hazards MapServer layer 7 "Fire Risk Areas"
                    (DLNR-DOFAW 2007, boundaries confirmed 2017 and 2022)
  flooded_highways  Hawaiʻi Statewide GIS, Climate MapServer layer 71 "SLR Potential Flooded
                    Highways – 3.2 Ft. Scenario" (Hawaiʻi Sea Level Rise Viewer, PacIOOS)
  pdc_shelters      Pacific Disaster Center "Hawaii Emergency Shelters" (ground condition
                    2009-10-08; capacity from the American Red Cross Hawaiʻi State Chapter),
                    as republished on ArcGIS Online (the PDC download link no longer answers)
  roads             Hawaiʻi DOT HPMS road centrelines (Transportation MapServer layer 12) for
                    the five highways used in the road-closure stress tests

Usage:  python3 scripts/fetch_hub_layers.py
"""
from __future__ import annotations

import json
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import fetch_json  # noqa: E402
from hawaii_time import now_hst  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "hub"
HUB = "https://geodata.hawaii.gov/arcgis/rest/services"
PDC_ITEM = "50c24479afdc40359a4b51285f945968"
PDC_METADATA = ("https://ghin.pdc.org/ghin/catalog/search/resource/details.page?"
                "uuid=%7B51D8DB9C-1FBF-41E4-84FB-7634099EA8A2%7D")
PDC_FIELDS = ["BUSNAME", "ADDRESS", "PLACENAME", "ZIPCODE", "CAPACITY", "PETS", "SP_NEEDS",
              "TYPE"]                                   # never PHONE or CONTACT
PDC_DROPPED = ["PHONE", "CONTACT"]
CLOSURE_ROUTES = {"Maui": ["30", "360"], "Oahu": ["83"], "Kauai": ["560"], "Hawaii": ["11"]}
LAYERS = {
    "safe_zones": {
        "url": f"{HUB}/Hazards/MapServer/13", "fields": ["island", "zone_type", "zone_desc"],
        "title": "Tsunami Safe Zones (Hawaiʻi Statewide GIS, Hazards layer 13)",
        "page": "https://geoportal.hawaii.gov/",
        "metadata": "https://files.hawaii.gov/dbedt/op/gis/data/tsunevac.pdf",
        "dates": "Hawaiʻi Island March 2025 (corrected November 2025), Oʻahu April 2025, "
                 "Kauaʻi March 2025, Maui, Molokaʻi and Lānaʻi 2013",
    },
    "fire_risk": {
        "url": f"{HUB}/Hazards/MapServer/7", "fields": ["commu_name", "island", "risk_rating"],
        "title": "Fire Risk Areas (DLNR Division of Forestry and Wildlife, via Hawaiʻi "
                 "Statewide GIS, Hazards layer 7)",
        "page": "https://geoportal.hawaii.gov/",
        "metadata": "https://files.hawaii.gov/dbedt/op/gis/data/FireRisk.pdf",
        "dates": "2007; boundaries confirmed by DLNR-DOFAW 2017 and 2022",
    },
    "flooded_highways": {
        "url": f"{HUB}/Climate/MapServer/71", "fields": ["fename", "highway", "name"],
        "title": "Sea Level Rise – Potential Flooded Highways, 3.2 ft scenario (Hawaiʻi Sea "
                 "Level Rise Viewer, PacIOOS, via Hawaiʻi Statewide GIS, Climate layer 71)",
        "page": "https://pacioos.org/shoreline/slr-hawaii/",
        "metadata": "https://climateadaptation.hawaii.gov/wp-content/uploads/2017/12/"
                    "SLR-Report_Dec2017.pdf",
        "dates": "Hawaiʻi Sea Level Rise Vulnerability and Adaptation Report, 2017",
    },
}


def page_query(url: str, where: str, fields: list, offset: int, geometry: bool = True,
               max_offset: float | None = None) -> dict:
    q = {"where": where, "outFields": ",".join(fields), "outSR": "4326", "f": "geojson",
         "returnGeometry": "true" if geometry else "false",
         "resultOffset": offset, "resultRecordCount": 1000}
    if max_offset:
        q["maxAllowableOffset"] = max_offset
    return fetch_json(f"{url}/query?{urllib.parse.urlencode(q)}")


def download(url: str, fields: list, where: str = "1=1") -> list:
    out, offset = [], 0
    while True:
        page = page_query(url, where, fields, offset)
        if "error" in page:
            raise RuntimeError(f"{url}: {page['error']}")
        feats = page.get("features", [])
        out += feats
        if len(feats) < 1000 and not page.get("exceededTransferLimit"):
            return out
        offset += len(feats)


def layer_info(url: str) -> dict:
    d = fetch_json(f"{url}?f=json")
    return {"name": d.get("name", ""), "description": (d.get("description") or "")[:1500],
            "copyright": d.get("copyrightText", "")}


def save(name: str, feats: list) -> None:
    (RAW / f"{name}.geojson").write_text(json.dumps(
        {"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    RAW.mkdir(parents=True, exist_ok=True)
    meta = {}
    for key, src in LAYERS.items():
        feats = download(src["url"], src["fields"])
        for f in feats:
            f["properties"] = {k: f["properties"].get(k) for k in src["fields"]}
        save(key, feats)
        meta[key] = {**{k: v for k, v in src.items() if k != "fields"},
                     **layer_info(src["url"]), "fields": src["fields"],
                     "features": len(feats), "fetched_at": now_hst()}
        print(f"{key}: {len(feats)} features")

    item = fetch_json(f"https://www.arcgis.com/sharing/rest/content/items/{PDC_ITEM}?f=json")
    pdc_url = item["url"].rstrip("/") + "/36"
    feats = download(pdc_url, PDC_FIELDS)
    for f in feats:
        f["properties"] = {k: f["properties"].get(k) for k in PDC_FIELDS}
    save("pdc_shelters", feats)
    meta["pdc_shelters"] = {
        "title": "Pacific Disaster Center – Hawaii Emergency Shelters (capacity: American Red "
                 "Cross Hawaiʻi State Chapter)",
        "url": pdc_url, "item_page": f"https://www.arcgis.com/home/item.html?id={PDC_ITEM}",
        "item_owner": item.get("owner", ""), "metadata": PDC_METADATA,
        "dates": "ground condition 2009-10-08 (PDC metadata)",
        "fields": PDC_FIELDS, "fields_dropped": PDC_DROPPED, "features": len(feats),
        "fetched_at": now_hst()}
    print(f"pdc_shelters: {len(feats)} features ({sum(1 for f in feats if (f['properties']['CAPACITY'] or 0) > 0)} with a capacity)")

    roads = []
    for island, routes in CLOSURE_ROUTES.items():
        where = f"island='{island}' AND route_id IN ({','.join(repr(r) for r in routes)})"
        feats = download(f"{HUB}/Transportation/MapServer/12",
                         ["route_id", "route_name", "bmp", "emp", "island"], where)
        roads += feats
    save("roads", roads)
    meta["roads"] = {"title": "Hawaiʻi DOT Highway Performance Monitoring System road "
                              "centrelines (Hawaiʻi Statewide GIS, Transportation layer 12)",
                     "url": f"{HUB}/Transportation/MapServer/12", "routes": CLOSURE_ROUTES,
                     "features": len(roads), "fetched_at": now_hst()}
    print(f"roads: {len(roads)} HPMS segments")
    (RAW / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
