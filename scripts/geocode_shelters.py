#!/usr/bin/env python3
"""
Geocode shelter addresses with the U.S. Census Bureau Geocoder.

Why Census: free, no API key, and results are public domain, so the State of
Hawaiʻi can reuse them without third-party permission (HAIC rules, Section 5).

Results are cached in data/sources/geocodes.csv (committed), so each address is
looked up once and the build stays reproducible offline.

Usage:  python3 scripts/geocode_shelters.py           # look up new addresses only
        python3 scripts/geocode_shelters.py --retry   # also retry earlier no-matches
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_shelters import load_activations  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "sources" / "geocodes.csv"
ENDPOINT = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
FIELDS = ["address", "query", "status", "lon", "lat", "matched_address", "method"]


def plain(text: str) -> str:
    s = unicodedata.normalize("NFKD", text or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.replace("ʻ", "").replace("‘", "").replace("’", "")


def to_query(address: str) -> str:
    q = plain(address).strip().rstrip(",")
    return q if q.upper().endswith((" HI", ", HI")) or " HI " in q.upper() else f"{q}, HI"


def census_lookup(query: str, fetch=None) -> dict:
    url = ENDPOINT + "?" + urllib.parse.urlencode(
        {"address": query, "benchmark": "Public_AR_Current", "format": "json"})
    if fetch is None:
        # The Census server sometimes answers a burst of requests with an HTML
        # error page (JSONDecodeError). Retry with backoff before giving up.
        last = None
        for attempt in range(4):
            try:
                req = urllib.request.Request(
                    url, headers={"User-Agent": "HAIC2026-KahuOla-ESF6"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    data = json.loads(r.read().decode("utf-8"))
                break
            except (json.JSONDecodeError, OSError) as e:
                last = e
                time.sleep(3 * (attempt + 1))
        else:
            raise last
    else:
        data = fetch(url)
    matches = (data.get("result") or {}).get("addressMatches") or []
    if not matches:
        return {"status": "no_match"}
    m = matches[0]
    c = m.get("coordinates") or {}
    lon, lat = c.get("x"), c.get("y")
    # Sanity check: must fall inside the Hawaiian Islands
    if lon is None or lat is None or not (-160.6 <= lon <= -154.7 and 18.8 <= lat <= 22.4):
        return {"status": "outside_hawaii"}
    return {"status": "match", "lon": round(lon, 6), "lat": round(lat, 6),
            "matched_address": m.get("matchedAddress", "")}


def load_cache(path: Path = CACHE) -> dict:
    if not path.exists():
        return {}
    with open(path, newline="", encoding="utf-8") as fh:
        return {r["address"]: r for r in csv.DictReader(fh)}


def save_cache(cache: dict, path: Path = CACHE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for addr in sorted(cache):
            w.writerow({k: cache[addr].get(k, "") for k in FIELDS})


def run(rows: list, cache: dict, retry: bool = False, fetch=None, pause: float = 1.5):
    done = 0
    for addr in sorted({r["address"].strip() for r in rows if r.get("address", "").strip()}):
        old = cache.get(addr)
        if old and (old.get("status") == "match" or not retry):
            continue
        q = to_query(addr)
        try:
            res = census_lookup(q, fetch)
        except Exception as e:  # network error: keep going, report
            res = {"status": f"error: {type(e).__name__}"}
        cache[addr] = {"address": addr, "query": q, "method": "census_onelineaddress",
                       "lon": "", "lat": "", "matched_address": "", **res}
        done += 1
        print(f"[{cache[addr]['status']}] {addr}")
        if fetch is None:
            time.sleep(pause)
    return done


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Geocode shelter addresses (Census)")
    ap.add_argument("--retry", action="store_true", help="retry earlier non-matches")
    args = ap.parse_args(argv)
    cache = load_cache()
    n = run(load_activations(), cache, retry=args.retry)
    save_cache(cache)
    matched = sum(1 for r in cache.values() if r.get("status") == "match")
    print(f"\nLooked up {n} new address(es). Cache: {matched}/{len(cache)} matched "
          f"-> {CACHE.relative_to(ROOT)}")
    misses = [a for a, r in cache.items() if r.get("status") != "match"]
    if misses:
        print("No match (check spelling, or add coordinates by hand with method=manual):")
        for a in misses:
            print("  -", a)
    print("\nNext: python3 scripts/build_shelters.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
