# Team verification of the fact check (C2)

The reviewer's files `C1_skeptic.md` and `C2_factcheck.md` are saved unedited. This file records how
the team checked each C2 row marked NOT SUPPORTED or NEEDS A LIVE SOURCE against the repository
(2026-11-01). Row numbers are C2's.

## NOT SUPPORTED (9)

| Row | Finding | Repository evidence | Action in PLAN.md |
|---|---|---|---|
| 1 | "Data as of 2026-10-28" while later inputs are used | `needs_by_scenario.json` built 2026-10-28; ACS 1-year fetched 2026-10-29; Hub layers and stress routing 2026-10-30 | Header now names the later dates |
| 74 | 5 vs 4 sites under review | `docs/site_review.md` lists 5 sites; Lahaina Civic Center Gym is resolved | §5.7: 5 listed, 4 still need review |
| 121 | 427 populated areas vs 436 − 4 | `afn_tracts.geojson`: 9 areas have population 0 in CDC SVI 2022 (ACS); 4 have no 2020 Census population | §5.7 states the basis (427 correct) |
| 148 | Maui SLR: 92 min to which sites | `stress_tests.json`: +92.0 min to any known site, +3.8 min to a 2026 site | §5.10 sentence corrected |
| 155 | Credits add to 12.3855 | `arcgis_credits.json`: earlier steps total 10.103 (rounded 10.10); total 12.3885 correct | §5.10 states 10.103 |
| 157 | Floor and toilet factors unsourced | `config/planning_factors.json`: Florida DEM Sheltering Guidance Aid (2010) | Source added in §5.11 |
| 160 | Pet shares unsourced | `config/planning_factors.json`: AVMA 2022 Sourcebook, 2020 data | Source added in §5.11 |
| 165 | 650 line pieces vs 779 | `flooded_paths.json` and `hub_layers_summary.json`: 779 pieces | **Error fixed: 779** |
| 181 | Census API key claim | Only a code comment (`scripts/build_demographics.py`); no dated source | Removed with the §9 rewrite |

## NEEDS A LIVE SOURCE (46)

**Clarified or updated in PLAN.md (4):**
- **61:** the risk-area suppression counts reproduce from `needs_by_tract.csv`. They cover people in the risk area, likely shelter demand and people-with-needs totals; the definition is now stated.
- **99:** Maui 1-year 160,642 ±19 vs Vintage 2025 160,592 (`race_ethnicity_by_county.csv`); the sentence is now explicit.
- **172:** the test count is updated.
- **180:** the playbook page range is updated.

**Confirmed by a source URL, date or file in the repository (25):**
- **2:** git remotes.
- **11:** standard-library imports in `scripts/`.
- **13:** 20 PDFs, `playbooks/index.html` and the `sw.js` precache.
- **14:** `LICENSE` (MIT).
- **15:** `.github/workflows/tests.yml`.
- **18:** no AI or HTTP client library in `scripts/`.
- **32, 176, 177:** product URLs in `config/decision_points.json`.
- **33:** GNIS download URL in `place_display_names.csv`.
- **42, 144, 188:** City and County of Honolulu release URL and dates in `county_lines.csv`.
- **62, 63, 161:** the tests and `tests/golden/`.
- **69:** event dates from 2026-04-09 to 2026-09-26 and 32 source URLs in `county_shelter_activations.csv`.
- **93:** SCEMD 2026 Annex G URL in `config/planning_factors.json`.
- **94, 163:** Maui Now article URL (2023-08-12) and count date 2023-08-11 in `past_events.csv`.
- **115:** Esri credit-rate URLs in `arcgis_credits.json`.
- **117:** `scripts/fetch_arcgis.py` and the credit-log note.
- **126:** `scripts/raw_inputs.py`, and the token-scan tests in `tests/test_arcgis.py`.
- **158:** Florida DEM 2010 URL in `config/planning_factors.json`.
- **179:** the bundle is 813 KB.

**Still open (17):**
- **Labelled team assumptions** (by design, to be replaced with county figures): 95, 142, 145, 159, 170, 184.
- **Need a live check:** 3 (demo site), 190 and 191 (Office of Language Access, We Are Oceania), 125 (Esri terms version), 100 and 102 (Census program rules), 78 (FEMA zone definitions are not cited), 81 (C16001 grouping, supported only by a code comment).
- **Team record only:** 72 (a manual check of pages that return HTTP 403).
- **Third-party copy of 2009 data:** 55 and 166.
