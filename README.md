# Hawaiʻi ESF-6 AFN Planning Framework (HAIC 2026)

> **Planning aid. Supports, does not replace, county emergency plans. Not an official shelter list.**

An AI-developed planning framework for Hawaiʻi DHS ESF-6 (mass care). It maps where people with access and functional needs (CMIST) live relative to hurricane, wildfire, tsunami, inland flood and coastal flood hazards. It estimates shelter needs for each county × hazard and matches those needs to proposed partner roles, decision points and multilingual communication. It uses public, aggregate data only, and it works offline.

The full plan is in **[PLAN.md](PLAN.md)**.

## Access

- **Demo:** https://shelters.kahuola.org (placeholder: not deployed yet)
- **No login.** No accounts, no tracking, no location access.
- **Offline:** after one visit the web app works in airplane mode, and it pre-caches all 20 printable playbooks.
- **Paper:** `playbooks/<county>_<hazard>.pdf`, 20 printable US-Letter playbooks; the index is `playbooks/index.html`.

## Run the pipeline

Requirements: Python 3.10+ (standard library only). PDF output also needs a local Chrome or Chromium, or WeasyPrint.

```sh
# 1. Refresh public data (network). Optional: processed data is committed.
python3 scripts/fetch_data.py               # SVI, NRI, tsunami zones, emPOWER, schools
python3 scripts/fetch_flood_zones.py        # FEMA flood zone per site (cached)
python3 scripts/fetch_languages.py          # ACS C16001 (secondary)
#    ACS PUMS: download the files listed in scripts/build_languages_pums.py into data/raw/pums/

# 2. Rebuild everything from local data (offline, about 1 minute)
python3 scripts/fetch_data.py --offline
python3 scripts/build_map.py
python3 scripts/build_shelters.py
python3 scripts/model_needs.py
python3 scripts/build_languages_pums.py
python3 scripts/match.py
python3 scripts/build_playbooks.py          # add --html-only to skip PDFs
python3 scripts/build_app_data.py           # app bundle and service worker; copies PDFs into app/
```

To preview the app: `cd app && python3 -m http.server 8000`.

## Test

```sh
python3 -m unittest discover tests
```

## Repository map

| Path | Contents |
|---|---|
| `PLAN.md` | The submission: the AI-developed plan |
| `config/` | Planning factors with sources (`planning_factors.json`), partner roster template, decision points, communication |
| `data/sources/` | Hand-curated and cached source tables with URLs: shelter activations, geocodes, flood zones, languages, message drafts |
| `data/processed/` | Pipeline outputs: tract layer, shelters, needs by scenario and tract, match plan, backtest |
| `data/raw/` | Downloads, including Census microdata (gitignored, never committed) |
| `scripts/` | MAP, MODEL, MATCH and deliverable builders |
| `playbooks/` | 20 printable playbooks (HTML and PDF) |
| `app/` | Offline web app (PWA); deploy output directory |
| `docs/` | Deploy note and security answer |
| `tests/` | Offline unit tests |

## Disclaimer

This is a planning aid built from public, aggregate data. It supports, and does not replace, county and State emergency plans or alerting systems. Sites listed are places a county opened in past events; not every site opens in every event. Roles, decision points and messages are proposals to be confirmed with each partner and county. Message translations are AI drafts that need native-speaker review before use. In an emergency, follow official county announcements and call 911 if you are in danger.

## License

MIT. See [LICENSE](LICENSE).
