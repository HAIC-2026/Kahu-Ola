# C2 – Fact check of the Kahu-Ola plan (PLAN.md, README.md)

This check uses only the text of PLAN.md and README.md. No cited source, file, repository or web page was opened, so no figure was compared with its source. Where it says "arithmetic ✓" or "✗", that is a check of the text against itself.

**Status legend**
- **CHECKED**: the text names a specific source (a document, table, URL or repo file) together with a date or vintage, and nothing else in the text contradicts the figure. This rests on the citation only. Where the source is a repo output file, CHECKED means "traceable to a named team file", not "independently confirmed".
- **NEEDS A LIVE SOURCE**: at least one of these holds:
  - the source is vague, undated or a third-party copy;
  - the value is a labelled team assumption;
  - it is a claim about code, live services or outside rules that only a live check can confirm.
- **NOT SUPPORTED**: the text gives no source at all, or its own numbers contradict the figure.

## Step 1 – Every figure, date, program rule and citation

### A. Header, README, access

| # | Item | Where it came from (per text) | How current | Status | What the status rests on |
|---|---|---|---|---|---|
| 1 | "Data as of 2026-10-28" (PLAN header) | Team statement | 2026-10-28 | **NOT SUPPORTED** | The text uses inputs dated after it: ACS 2025 1-year released and fetched 2026-10-29; Hub layers fetched 2026-10-30; ArcGIS stress routing run 2026-10-30 |
| 2 | Official repo https://github.com/HAIC-2026/Kahu-Ola; mirror https://github.com/nguyenhuulong2222/haic2026-esf6-shelters; "All numbers below are read from files in it" | Team | Undated | **NEEDS A LIVE SOURCE** | URLs given; whether they exist and match the text needs a live check |
| 3 | Demo https://shelters.kahuola.org and https://haic2026-shelters.pages.dev | README §Access, PLAN §8 | Undated | **NEEDS A LIVE SOURCE** | Live check needed |
| 4 | Challenge PDF "HAIC_AI Challenge_Submission_DHS_Disaster_2026.pdf" (Hawaiʻi DHS, 2026), cited by page | PLAN preamble | 2026 (no release date) | **CHECKED** | Named document plus pages; the PDF was not supplied |
| 5 | Quotes p. 4 (fragmented information, no shared operating picture); p. 3 (pain points, manual steps); p. 4 (repetitive work, "only after an event begins"); p. 5 (no PII, "not replace them", "high-stress, low-connectivity"); p. 5–6 (scope in three parts) | Challenge PDF | 2026 | **CHECKED** | Named document plus page; quotes cannot be compared |
| 6 | p. 7: three measurable goals; "Teams may propose their own baseline and target time"; target 100% of Census areas; "within an agreed margin against past events" | Challenge PDF | 2026 | **CHECKED** | Named document plus page |
| 7 | p. 2: "Each County Emergency Management Agency leads mass care operations"; DHS and HI-EMA as State ESF-6 co-facilitators | Challenge PDF | 2026 | **CHECKED** | Named document plus page |
| 8 | pp. 1–3: partner types (DHS, County EM, HI-EMA, DOE, Public Library System, DOH, DOT, OHA, Red Cross, Salvation Army, VOAD, faith-based, health care, utilities, philanthropy, business, other agencies) | Challenge PDF | 2026 | **CHECKED** | Named document plus pages |
| 9 | p. 4: Datatrove named as the primary data source | Challenge PDF | 2026 | **CHECKED** | Named document plus page |
| 10 | pp. 4, 8: earthquake, sheltering in place and shelter-in-place support are named in the challenge | Challenge PDF | 2026 | **CHECKED** | Named document plus pages |
| 11 | Python 3.10+, standard library only; PDF output needs Chrome/Chromium or WeasyPrint | README | Undated | **NEEDS A LIVE SOURCE** | Claim about code; not verifiable from the text |
| 12 | Offline rebuild "about 1 minute" | README | Undated | **CHECKED** | Consistent with the measured 44.0 s (row 171) |
| 13 | 20 printable US-Letter playbooks; index `playbooks/index.html`; app pre-caches all 20 | README, PLAN §8 | Undated | **NEEDS A LIVE SOURCE** | Claim about deliverables; files not supplied |
| 14 | Licence MIT | README, PLAN §11 | Undated | **NEEDS A LIVE SOURCE** | LICENSE file not supplied |
| 15 | CI: pull requests to `main` run fast tests (`.github/workflows/tests.yml`) and fail on a stale `sw.js` VERSION | README | Undated | **NEEDS A LIVE SOURCE** | Claim about repository configuration |

### B. Approach (§2)

| # | Item | Where it came from | How current | Status | What the status rests on |
|---|---|---|---|---|---|
| 16 | 436 Census areas in 4 counties | `data/processed/coverage.json` | As of build | **CHECKED** | Named file |
| 17 | 4 × 5 = 20 county × hazard scenarios | Team design | n/a | **CHECKED** | Arithmetic ✓ |
| 18 | Pipeline is deterministic, standard library only, calls no AI | Team claim | n/a | **NEEDS A LIVE SOURCE** | Code not supplied |
| 19 | Top 10 outreach Census areas per county × hazard | `scripts/match.py`, playbooks | As of build | **CHECKED** | Named file (design rule) |

### C. Data sources (§3)

| # | Item | Where it came from | How current | Status | What the status rests on |
|---|---|---|---|---|---|
| 20 | CDC/ATSDR SVI 2022 (CMIST proxies) | §3 table | SVI 2022 (ACS 2018-2022); fetched 2026-10-27 | **CHECKED** | Named dataset plus vintage plus fetch date; no URL. Predates the 2023 Lahaina fire (§10.10) |
| 21 | FEMA NRI v1.20 (hurricane, wildfire, tsunami, inland and coastal flooding) | §3 | v1.20; fetched 2026-10-27 | **CHECKED** | Named dataset plus version plus date |
| 22 | Hawaiʻi Statewide GIS tsunami evacuation and extreme tsunami evacuation zones | §3 | Fetched 2026-10-27; layer vintage not given | **CHECKED** | Named layer plus fetch date; layer vintage unknown |
| 23 | TIGERweb 2020 Census Blocks, MapServer/10 URL | §3 | Fetched 2026-10-28 | **CHECKED** | URL plus date |
| 24 | State DFIRM (FEMA flood areas, "downloaded from FEMA 6/15/26"), 311 site points | §3, `site_flood_zones.csv` | Queried 2026-10-27 | **CHECKED** | Named layer, file and date. Note: 30 sites + 292 schools − 9 overlapping school sites = 313, not 311 [VERIFY] |
| 25 | HHS emPOWER county level (`Power_Dependent_Devices_DME`) | §3 | Fetched 2026-10-27; data month not given | **CHECKED** | Named dataset plus fetch date |
| 26 | Hawaiʻi DOE public schools, 292 candidate schools | §3 | Fetched 2026-10-27 | **CHECKED** | Named layer plus date |
| 27 | County announcements of 2026 shelter openings, one official URL per row | `county_shelter_activations.csv` | 2026 events | **CHECKED** | Named file with per-row URLs |
| 28 | U.S. Census Geocoder; Hawaiʻi and Maui County address points | `geocodes.csv` | Not dated in text | **CHECKED** | Named file with per-row URL; no date in text |
| 29 | ACS PUMS 2019-2023 5-year, Hawaiʻi person file | `languages_by_county.csv` | 2019-2023 | **CHECKED** | Named dataset plus vintage |
| 30 | DBEDT Data Book 2024, Table 1.44 (language validation) | `tests/test_languages_pums.py` | 2024 edition | **CHECKED** | Named table plus edition |
| 31 | ACS C16001, 2020-2024 5-year (secondary language source) | `languages_by_county_c16001.csv` | 2020-2024 | **CHECKED** | Named table plus vintage |
| 32 | NWS / NHC / CPHC / PTWC product definitions | URLs in `config/decision_points.json` | No date given | **NEEDS A LIVE SOURCE** | URLs not in text; no access date |
| 33 | USGS GNIS Domestic Names, Hawaii (BGN spellings) | `place_display_names.csv` | No date given | **NEEDS A LIVE SOURCE** | Named source, no vintage or fetch date |
| 34 | Census Population Estimates Vintage 2025 (`co-est2025-alldata`, `cc-est2025-alldata-15`) | `county_population_2020_2025.csv` | Released 2026-06-25 | **CHECKED** | Named files plus release date |
| 35 | ACS 2025 1-year (B01003, B02001, B02008–B02012, B03002) for 4 counties | `county_population_2020_2025.csv`, `race_ethnicity_by_county.csv` | Released 2026-10-29; fetched 2026-10-29 | **CHECKED** | Named tables plus dates (later than the header date, row 1) |
| 36 | ACS 2020-2024 5-year: B01003, B02001, B02008–B02012, B03002, B02015, B02016, B02018, B02019 | `communities_by_island.csv`, `race_ethnicity_by_county.csv` | 2020-2024 | **CHECKED** | Named tables plus vintage |
| 37 | 2020 Census PL 94-171 (P1) and DHC-A (T01001 by POPGROUP) | Same files, one table ID and URL per row | 2020 | **CHECKED** | Named tables |
| 38 | 2020 Block Assignment File plus PL block population (P1_001N); TIGERweb CDP polygons for 4 Census areas with no 2020 population | `tract_communities.csv`, `tract_cdp_population_2020.csv` | 2020 | **CHECKED** | Named files. See row 121 for a related count conflict |
| 39 | DBEDT State Data Book 2025, Table 01.12 (island and CDP) | `communities_by_island.csv` | 2025 edition | **CHECKED** | Named table plus edition |
| 40 | ACS 2020-2024 B18102, B18103, B18104, B09020 (hearing, vision, cognitive, 65+ alone) | `cmist_detail_by_tract.csv` | Fetched 2026-10-27 | **CHECKED** | Named tables plus date |
| 41 | Bridging the Gap 2026 PIT report (Hawaiʻi, Maui, Kauaʻi; night of Jan 25, 2026), URL | `county_lines.csv` | Fetched 2026-10-27 | **CHECKED** | URL plus date (no county figures given in text) |
| 42 | Partners In Care 2026 PIT, Oʻahu (Jan 26, 2026), released by City and County of Honolulu 2026-05-21; report PDF "could not be found" (§10.12) | `county_lines.csv` | 2026-05-21 | **NEEDS A LIVE SOURCE** | No URL; primary report not found; release gives the total only |
| 43 | Statewide GIS Coastline layer (Terrestrial/MapServer/3, from USGS DLG) | `islands.csv` | Fetched 2026-10-28 | **CHECKED** | Named layer plus date |
| 44 | DBEDT Data Book 2025, Table 7.06 (average daily visitor census 2025) | `county_lines.csv` | Fetched 2026-10-27 | **CHECKED** | Named table plus date |
| 45 | Esri ArcGIS World Geocoder (`forStorage=true`): 30 sites, Pukalani, 107 care facilities | `arcgis_summary.json` | Run 2026-10-28 | **CHECKED** | Named file plus date |
| 46 | Esri ArcGIS routing OD matrix, drive and walk, normal traffic | `arcgis_summary.json` | Run 2026-10-28 | **CHECKED** | Named file plus date |
| 47 | Ready Keiki "All Pre-K Sites" (item 5486617d…, service URL) | §3 | Fetched 2026-10-28; layer updated 2024-06-28 | **CHECKED** | Item, URL and dates |
| 48 | HI-EMA public siren layer (item 91253912…, service URL); siren system page URL | §3 | Fetched 2026-10-28; layer updated 2025-08-21; page access date not given | **CHECKED** | Item, URLs and dates |
| 49 | State dam evacuation zones (item fd890585…, service URL) | §3 | Fetched 2026-10-28; layer updated 2026-03-26 | **CHECKED** | Item, URL and dates |
| 50 | Census Geocoder on DOE school addresses | `doe_school_checks.csv` | Queried 2026-10-28 | **CHECKED** | Named file plus date |
| 51 | CMS Provider Data Catalog: dialysis (23ew-n7w9), nursing homes (4pq5-n9py), hospitals (xubh-q36u) | `arcgis_summary.json` | Fetched 2026-10-28 | **CHECKED** | Dataset IDs plus date |
| 52 | Hazards MapServer/13 "Tsunami Safe Zones" plus metadata PDF | §3 | Hawaiʻi Island March 2025 (corrected November 2025); Oʻahu April 2025; Kauaʻi March 2025; Maui, Molokaʻi, Lānaʻi 2013; fetched 2026-10-30 | **CHECKED** | URLs plus dates. The Maui County layer is 13 years old |
| 53 | Hazards MapServer/7 "Fire Risk Areas" (DLNR-DOFAW) plus metadata | §3 | 2007; boundaries confirmed 2017 and 2022; fetched 2026-10-30 | **CHECKED** | URLs plus dates |
| 54 | Climate MapServer/71 "SLR Potential Flooded Highways – 3.2 Ft" (PacIOOS viewer) | §3 | SLR report 2017; fetched 2026-10-30 | **CHECKED** | URL plus dates |
| 55 | PDC "Hawaii Emergency Shelters" (Red Cross capacity), via a third-party ArcGIS Online copy; PDC download link "no longer answers" | §3 | Ground condition 2009-10-08; fetched 2026-10-30 | **NEEDS A LIVE SOURCE** | Third-party copy; the original source is dead; data is 17 years old |
| 56 | HDOT HPMS centrelines (Transportation/12) and mile markers (layer 14); Routes 30, 360, 83, 560; Route 11 closure at MP 53.9 | §3 | HPMS 2024 (DOT, September 2025); mile markers 2023; fetched 2026-10-30 | **CHECKED** | URLs plus dates (closure locations are team assumptions, §5.10) |
| 57 | Esri routing with barriers, plus walking to safe-zone edges | `road_closures_summary.json`, `hub_layers_summary.json` | Run 2026-10-30 | **CHECKED** | Named files plus date |

### D. Privacy model (§4, README Privacy)

| # | Item | Where it came from | How current | Status | What the status rests on |
|---|---|---|---|---|---|
| 58 | PUMS suppression rule: cells under 100 weighted people or under 10 sample persons; 149 of 194 area × language cells suppressed | §4 | As of build | **CHECKED** | Rule stated; 194 = 90 + 53 + 51 ✓ (§5.4) |
| 59 | Per-area display rule: no count 1–9 shown; 0 shown as 0; "fewer than 10" | `scripts/privacy.py`, `scripts/area_view.py`, `tests/test_privacy.py` | As of build | **CHECKED** | Team rule plus named tests (not run here) |
| 60 | 12 Census areas under 100 residents (Honolulu 9, Maui 2 incl. Kalawao, Kauaʻi 1) | §4 | As of build | **CHECKED** | Arithmetic 9 + 2 + 1 = 12 ✓; source scripts named |
| 61 | Values affected: whole-area CMIST 1–9 values Honolulu 112, Maui 9, Kauaʻi 1, Hawaiʻi 0; risk-area 1–9 values Honolulu 27, Maui 14, Hawaiʻi 10, Kauaʻi 9 | §4 | As of build | **NEEDS A LIVE SOURCE** | No output file named |
| 62 | 49 views compared with a pre-change reference | §4 | Undated | **NEEDS A LIVE SOURCE** | No file or date named |
| 63 | Served-file rule: no value 1–9 in any file under `app/` | `tests/test_served_files.py` | As of build | **NEEDS A LIVE SOURCE** | Claim about code and tests |
| 64 | SVI table IDs: B16005 (ACS 2018–2022), DP02_0072E, S0101_C01_030E, DP04_0058E, S0601, with M_ MOE columns, "checked against the SVI 2022 documentation" | §4 | SVI 2022 | **CHECKED** | Named document plus vintage |
| 65 | Risk-area MOE = whole-area MOE × in-zone fraction | `data/sources/area_moe.csv` | As of build | **CHECKED** | Team method stated (an approximation, not a published MOE) |
| 66 | Per-area values can be derived by subtraction from county totals where one area is suppressed | README, §10.16 | n/a | **CHECKED** | Self-disclosed residual risk |

### E. Coverage, shelters, unsuitable sites (§5.1–5.3)

| # | Item | Where it came from | How current | Status | What the status rests on |
|---|---|---|---|---|---|
| 67 | CMIST 436/436 (100%); NRI 435/436 (99.8%); one Honolulu area has no NRI record | `coverage.json` | As of build | **CHECKED** | Named file; arithmetic ✓ |
| 68 | 30 sites opened in 2026 events: Kauaʻi 5, Honolulu 7, Maui 8, Hawaiʻi 10 | `shelters_2026.geojson` | 2026 | **CHECKED** | Sum 30 ✓ |
| 69 | Events: April 2026 severe weather, Hurricane Lala, Hurricane Lowell, Tropical Storm Nolo, Olowalu brush fire | `county_shelter_activations.csv` | 2026; no event dates in text | **NEEDS A LIVE SOURCE** | Event names only; dates and URLs not in text |
| 70 | 30 of 30 with official county source (kauai.gov, honolulu.gov, mauicounty.gov, hawaiicounty.gov); 0 news-only; 16 first found in news | Same CSV | 2026 | **CHECKED** | Named file with per-row URL |
| 71 | Naming variants "Yano Memorial Hall" / "Hisaoka Gym" in one Hawaiʻi County release | CSV notes | 2026 | **CHECKED** | Named file |
| 72 | Maui and Hawaiʻi County pages return HTTP 403; names and addresses confirmed by a team member 2026-10-27 | §5.2 | 2026-10-27 | **NEEDS A LIVE SOURCE** | One person's manual read; not reproducible from the text |
| 73 | Site check: 15 confirmed (2 sources, ≤ 300 m); 9 school sites (7 DOE + ArcGIS, 2 DOE + Census); 4 need review; Lahaina verified manually; Pukalani located (ArcGIS score 100) | `shelters_2026.geojson`, `arcgis_summary.json` | 2026-10-28 | **CHECKED** | 15 + 9 + 4 + 1 + 1 = 30 ✓; the 300 m threshold is a team rule |
| 74 | "The 5 non-school sites that still need review" (§5.7) vs "4 need review" (§5.2, §10.7) | §5.7 | 2026-10-28 | **NOT SUPPORTED** | Text conflict: §5.7 says 5 but then lists 4 plus Lahaina "resolved" |
| 75 | Lahaina Civic Center Gym: opened twice in 2026; Maui County facility page lists Kaʻaʻahi St & Honoapiʻilani Hwy (Wahikuli); ArcGIS point about 2 km (2,308 m) north, outside the tsunami zone; flood zone X at both points; verified 2026-10-28 | §5.3, §5.7 | 2026-10-28 | **CHECKED** | Named page plus date (no URL); 2 km is consistent with 2,308 m. Visual check on the State map still open |
| 76 | Kilohana Recreation Center (Molokaʻi): inside tsunami zone and FEMA zone AE | `shelters_2026.geojson` | As of build | **CHECKED** | Named file |
| 77 | 22 candidate schools in an SFHA; 22 Honolulu candidate schools in zone D | `candidates.geojson`, `needs_by_scenario.csv` | As of build | **CHECKED** | Named files. The same number appears twice [VERIFY] |
| 78 | FEMA zone rules: AE = SFHA; D = flood risk undetermined; A/AE/V/VE treated as high-risk screens | §5.3, §5.7 | n/a | **NEEDS A LIVE SOURCE** | Program definitions; no FEMA document cited |

### F. Languages (§5.4)

| # | Item | Where it came from | How current | Status | What the status rests on |
|---|---|---|---|---|---|
| 79 | Statewide limited-English counts match DBEDT Table 1.44 exactly for top 10 languages: Ilocano 34,269; Tagalog/Filipino 27,582; Chinese 21,856; Japanese 17,683 | `pums_language_state_summary.csv`; test | PUMS 2019-2023; Data Book 2024 | **CHECKED** | Named table plus test. Ilocano area sum 9,131 + 21,729 + 3,409 = 34,269 ✓ |
| 80 | Ilocano #1 in every area; Hawaiʻi Island #2 Pidgin 2,040 ±740 | `languages_by_county.csv` | 2019-2023 | **CHECKED** | Named file |
| 81 | C16001 lumps these into "Other Asian and Pacific Island languages" | §5.4 | ACS 2020-2024 | **NEEDS A LIVE SOURCE** | Claim about a Census table; not cited to its documentation |
| 82 | Kauaʻi and Maui share PUMA 00100 | `puma_county_2020.csv` | 2020 PUMAs | **CHECKED** | Named file |
| 83 | Languages listed: Honolulu 90, Kauaʻi + Maui 53, Hawaiʻi 51 | §5.4 | As of build | **CHECKED** | Consistent with 194 cells (row 58) |
| 84 | Low-reliability rule: CV > 40% (MOE ÷ 1.645 ÷ estimate) or suppressed cell | §5.4 | n/a | **CHECKED** | Team rule stated |
| 85 | Vietnamese: Honolulu 5,648 ±1,522; Kauaʻi + Maui 359 ±216; Hawaiʻi too few to estimate | `languages_by_county.csv` | 2019-2023 | **CHECKED** | Named file |
| 86 | Top-3 table: Kauaʻi + Maui Ilocano 9,131, Tagalog 5,074, Spanish 1,711; Honolulu Ilocano 21,729, Tagalog 21,584, Chinese 20,695; Hawaiʻi Ilocano 3,409, Pidgin 2,040, Japanese 1,408 | Same | 2019-2023 | **CHECKED** | Named file |
| 87 | Drafts available in 9 languages (Chinese, Hawaiian, Ilocano, Japanese, Korean, Pidgin, Spanish, Tagalog, Vietnamese); Chuukese and Marshallese need translators | `data/sources/messages/` | As of build | **CHECKED** | Named folder; consistent with §9 |

### G. Shelter demand (§5.5)

| # | Item | Where it came from | How current | Status | What the status rests on |
|---|---|---|---|---|---|
| 88 | Kauaʻi low/likely/high: hurricane 1,470/2,205/3,676; wildfire 433/1,082/2,423; tsunami 181/452/994; inland flood 428/1,070/2,354; coastal flood 384/959/2,110 | `needs_by_scenario.json` | As of build | **CHECKED** | Named file. The rates behind it are assumptions (rows 93–95) |
| 89 | Honolulu: hurricane 20,202/30,303/50,505; wildfire 6,285/15,713/35,197; tsunami 1,607/4,017/8,838; inland 7,389/18,473/40,641; coastal 4,868/12,170/26,775 | Same | As of build | **CHECKED** | Named file. Hurricane likely ÷ 3% ≈ 1.01 million, which implies the hurricane footprint is the whole county |
| 90 | Maui: hurricane 3,296/4,944/8,241; wildfire 977/2,442/5,469; tsunami 523/1,308/2,877; inland 1,053/2,633/5,792; coastal 734/1,834/4,035 | Same | As of build | **CHECKED** | Named file |
| 91 | Hawaiʻi: hurricane 4,043/6,065/10,108; wildfire 1,151/2,878/6,446; tsunami 242/605/1,331; inland 1,310/3,276/7,207; coastal 1,079/2,698/5,937 | Same | As of build | **CHECKED** | Named file |
| 92 | Largest single community (likely): Kauaʻi 404.01 225, 402.04 302, 409 207, 405 365 (×2); Honolulu 115 347/579/579, 96.10 308, 102.02 349; Maui 308 242/403, 310.01 349, 314.04 154, 319 266; Hawaiʻi 210.14 244/407/407, 206 146, 213 369 | `needs_by_tract.csv` | As of build | **CHECKED** | Named file. Lahaina 314.04 uses pre-fire population (§10.10) |
| 93 | Hurricane rates 2/3/5% | "South Carolina EMD Annex G" via `config/planning_factors.json` | No year or version | **NEEDS A LIVE SOURCE** | Named annex, no date, no URL, mainland source |
| 94 | Wildfire high rate 11.2% = Lahaina 2023 (1,418 / 12,702); low and central are team assumptions (implied 2% and 5% from 254/635 ÷ 12,702) | §5.5, §6 | 2023 | **NEEDS A LIVE SOURCE** | High rate rests on the Maui Now count (row 163); low and central are assumptions |
| 95 | Tsunami and flood rates 2/5/11% | Team assumption | n/a | **NEEDS A LIVE SOURCE** | Labelled assumption; no evidence |
| 96 | "County totals are upper bounds: every at-risk area hit at once" | §5.5 | n/a | **CHECKED** | Team method statement |

### H. Demographics (§5.6)

| # | Item | Where it came from | How current | Status | What the status rests on |
|---|---|---|---|---|---|
| 97 | 2020 → July 1, 2025: Honolulu 1,016,508 → 988,703 (−2.7%); Hawaiʻi 200,629 → 210,043 (+4.7%); Maui 164,754 → 160,592 (−2.5%); Kauaʻi 73,298 → 73,400 (+0.1%); Kalawao 82 → 82 | `county_population_2020_2025.csv` (2020 Census, Vintage 2025) | V2025 released 2026-06-25 | **CHECKED** | Percentages arithmetic ✓ |
| 98 | ACS 5-year → 1-year: Honolulu 1,001,146 → 988,703; Hawaiʻi 205,769 → 210,043; Maui 164,522 ±25 → 160,642 ±19; Kauaʻi 73,731 → 73,400; Kalawao 67 ±25 (5-year kept) | Same files | 2020-2024; 2025 1-year | **CHECKED** | Named tables plus vintages |
| 99 | Rule: 1-year county totals are controlled to population estimates, so they match V2025 with no MOE, "except Maui (±19)" | §5.6 | n/a | **NEEDS A LIVE SOURCE** | Census methodology claim, no document cited. Maui 1-year 160,642 vs V2025 160,592 (differs by 50), and the reason is not given |
| 100 | Rule: Kalawao under 65,000 people, so not in the ACS 1-year | §5.6 | n/a | **NEEDS A LIVE SOURCE** | Program threshold not cited |
| 101 | Maui 1-year 160,642 is down 3,880 (2.4%) from the 5-year and 4,112 (2.5%) below the 2020 Census | §5.6 | 2025 | **CHECKED** | Arithmetic ✓ |
| 102 | Detailed race tables B02015/16/18/19 not published in the 1-year (data.census.gov "returns no content"; none in the 2024 1-year either) | §5.6 | Observed by team, undated | **NEEDS A LIVE SOURCE** | Observation of a live site |
| 103 | Island table: Oʻahu 1,001,146; Urban Honolulu 345,482 ±70; East Honolulu 51,360 ±2,103; Pearl City 44,547 ±1,921; Waipahu 40,482 ±2,530; Kailua 39,640 ±1,744; outside CDP 16,007 (1.6%) | `communities_by_island.csv`; DBEDT 01.12 | ACS 2020-2024; DBEDT 2025 | **CHECKED** | 1.6% ✓ |
| 104 | Hawaiʻi Island 205,769; Hilo 50,404 ±2,228; Kailua (Kona) 21,818 ±2,034; HPP 13,203 ±1,721; Kaiminani 11,465 ±1,347; Waimea 9,286 ±1,189; outside 13,267 (6.4%) | Same | Same | **CHECKED** | 6.4% ✓ |
| 105 | Maui 152,418; Kahului 28,288 ±1,914; Kīhei 21,567 ±1,407; Wailuku 16,926 ±1,455; Waiheʻe-Waiehu 10,988 ±1,300; Lahaina 10,162 ±1,143; Maui County outside CDPs 4,225 (2.6%) | Same | Same | **CHECKED** | Maui + Molokaʻi + Lānaʻi = 164,589 = 164,522 + 67 ✓ |
| 106 | Molokaʻi 8,728 (incl. Kalawao): Kaunakakai 4,360 ±985; Kualapuʻu 2,535 ±421; ʻUalapuʻe 440 ±168; Maunaloa 293 ±133. Lānaʻi 3,443: Lānaʻi City 3,393 ±431; Manele 50 ±33 | Same | Same | **CHECKED** | Lānaʻi sum ✓ |
| 107 | Kauaʻi 73,731: Kapaʻa 11,094 ±1,301; Līhuʻe 7,901 ±872; Wailua Homesteads 5,431 ±920; Hanamāʻulu 4,972 ±832; Kalāheo 4,435 ±676; outside 2,722 (3.7%); Niʻihau has no CDPs (DBEDT note) | Same | Same | **CHECKED** | 3.7% ✓ |
| 108 | Detailed groups (alone or in combination, % of county): Honolulu Filipino 252,603 (25.2%), Japanese 241,669 (24.1%), Native Hawaiian 196,688 (19.7%), Chinese 173,593 (17.3%); Hawaiʻi NH 63,390 (30.8%), Filipino 45,200 (22.0%), Japanese 38,478 (18.7%), Chinese 26,464 (12.9%); Maui Filipino 49,560 (30.1%), NH 41,614 (25.3%), Japanese 23,883 (14.5%), Chinese 18,146 (11.0%); Kauaʻi Filipino 24,637 (33.4%), NH 18,341 (24.9%), Japanese 13,705 (18.6%), Chinese 7,500 (10.2%) | `race_ethnicity_by_county.csv` | ACS 2020-2024 | **CHECKED** | All percentages ✓ against the 5-year county totals |
| 109 | 27.0% statewide report two or more races (B02001) | Same | 2020-2024 | **CHECKED** | Named table |
| 110 | Native Hawaiian statewide 320,047 ±5,615 (22.1%), alone 87,937 ±3,241; 2020 DHC-A 317,497 and 94,025 alone | Same | ACS 2020-2024; 2020 Census | **CHECKED** | 22.1% ✓ against the sum of county totals |
| 111 | Statewide (alone or in combination): Samoan 36,705 ±2,419; Tongan 9,504 ±1,335; Marshallese 9,232 ±1,460; Chamorro 7,246 ±1,260; Chuukese 5,153 ±1,589; other Micronesian 17,765 ±2,554. Chuukese, Hawaiʻi County ACS 114 ±95 vs 2020 Census 715. "Other Micronesian" 2020 statewide only 11,481 alone; suppressed cells left blank | Same | 2020-2024; 2020 | **CHECKED** | Named file. Large ACS-vs-Census gaps are disclosed |
| 112 | Limited-English: Chuukese 4,948 and Marshallese 1,021 in Honolulu; Marshallese 538 on Hawaiʻi Island, 633 in Kauaʻi + Maui | `languages_by_county.csv` | PUMS 2019-2023 | **CHECKED** | Named file. Tension: 4,948 limited-English Chuukese in Honolulu is about 96% of all Chuukese statewide (5,153, row 111); different sources and years [VERIFY] |
| 113 | "Native Hawaiian residents are about a quarter to a third of each neighbor-island county" | §5.6 | 2020-2024 | **CHECKED** | 24.9%, 25.3%, 30.8% ✓ (approximate) |
| 114 | OHA and Native Hawaiian organisations listed as trusted messengers; Hawaiian always in message languages | `config/communication.json` | As of build | **CHECKED** | Named file |

### I. Travel times, credits, care facilities (§5.7)

| # | Item | Where it came from | How current | Status | What the status rests on |
|---|---|---|---|---|---|
| 115 | Credit budget 22, plus 3 in reserve; log `arcgis_credits.json` "at Esri's published rates" | §5.7 | 2026-10-28 | **NEEDS A LIVE SOURCE** | Esri rate sheet not cited or dated (rates implied: 0.04 per geocode, 0.0005 per pair) |
| 116 | Credits: geocode 30 = 1.20; 107 = 4.28; drive matrix 2,981 pairs = 1.49; walk first run 2,981 = 1.49; walk per site 479 = 0.24; school matrix 2,757 = 1.38; Lahaina rerun 41 + 7 = 0.02; polygons skipped (30 × 0.5 = 15); total 10.10 | `arcgis_credits.json` | 2026-10-28 | **CHECKED** | Arithmetic ✓ for every line and the total |
| 117 | Service limits: at most 50 origins per request; walking rejects inputs more than 27 miles (43 km) apart; 2,100 rejected pairs per mode not counted | §5.7 | Observed 2026-10-28 | **NEEDS A LIVE SOURCE** | Observed service behaviour, not a cited Esri document |
| 118 | Walk times only within 12 km straight line | §5.7 | n/a | **CHECKED** | Team rule |
| 119 | Kahuku Elementary and Nānākuli High & Intermediate: Census Geocoder 125 m and 74 m from the DOE point | `doe_school_checks.csv` | 2026-10-28 | **CHECKED** | Named file |
| 120 | Review distances: Keaʻau Armory 546 m, Puʻuʻeo Community Center 518 m, Pāpaʻaloa Park Annex 8,655 m, South Maui Community Park Gym 455 m; Lahaina 2,308 m resolved | `docs/site_review.md` | 2026-10-28 | **CHECKED** | Named file |
| 121 | Populated areas: Hawaiʻi 43, Honolulu 322, Maui 45, Kauaʻi 17 (total 427) | §5.7 | As of build | **NOT SUPPORTED** | 436 areas − 4 with no 2020 population (§3) = 432, not 427. The text does not reconcile the gap; I don't know which figure is right |
| 122 | Areas with no usable 2026 site within 15 min, (1) → (2): Hawaiʻi 32 → 15 (all hazards); Honolulu 169 → 8 (hurricane, wildfire), 174 → 17 (tsunami), 169 → 14 (floods); Maui 19 → 13 (hurricane, wildfire, tsunami), 19 → 14 (floods); Kauaʻi 6 → 5 | `arcgis_summary.json` | 2026-10-28 | **CHECKED** | Named file. Depends on the 2026 site sample |
| 123 | 107 care facilities: Honolulu 64, Hawaiʻi 19, Maui 14, Kauaʻi 10 (41 dialysis, 43 nursing homes, 23 hospitals) | CMS plus `arcgis_summary.json` | 2026-10-28 | **CHECKED** | Both sums = 107 ✓ |
| 124 | Care facilities in zones: Honolulu tsunami 5 (dialysis Hawaii Kai, Waianae ×2, Nanakuli; nursing home Hale Malamalama), flood 1 (Hale Malamalama, AE); Maui tsunami 3 (Kahana, Molokai, Lahaina dialysis), flood 1 (Molokai dialysis, AE); Hawaiʻi tsunami 0, flood 1 (USRC Hilo Dialysis, A); Kauaʻi 0; plus 3 Honolulu dialysis in zone D | Same | 2026-10-28 | **CHECKED** | Named file; Honolulu tsunami count 4 + 1 = 5 ✓ |
| 125 | Esri Product-Specific Terms of Use (E300, footnote 66) allow storing World Geocoding results for paid subscribers | §5.7 | No version or date | **NEEDS A LIVE SOURCE** | Licence term cited without version or date |
| 126 | Fail-closed build rule (`scripts/raw_inputs.py`); token only from an environment variable, never written (tests) | §5.7, README | n/a | **NEEDS A LIVE SOURCE** | Claim about code |

### J. Childcare, sirens, dam zones (§5.8)

| # | Item | Where it came from | How current | Status | What the status rests on |
|---|---|---|---|---|---|
| 127 | 422 centres = 377 PATCH + 30 EOEL + 15 charter pre-K; Honolulu 263, Hawaiʻi 71, Maui 62, Kauaʻi 26; 13 placeholder rows dropped; no family child care homes | Ready Keiki layer | Layer 2024-06-28; fetched 2026-10-28 | **CHECKED** | Both sums = 422 ✓ |
| 128 | Childcare in zones: Honolulu tsunami 29, inland 19, coastal 19; Maui 15/4/4; Kauaʻi 8/6/6; Hawaiʻi 6/4/4; zone D 21 (Honolulu 20, Hawaiʻi 1) | Same | Same | **CHECKED** | 20 + 1 = 21 ✓ |
| 129 | 413 permanent sirens: Honolulu 180, Hawaiʻi 94, Maui 85, Kauaʻi 54; one mobile siren not counted | HI-EMA siren layer | Layer 2025-08-21 | **CHECKED** | Sum ✓ |
| 130 | Rated audible radius 3,400 ft (quote: "propagate with a manufacture radius of 3,400 feet…") | HI-EMA siren system page URL | Page access date not given | **CHECKED** | URL plus quote; it is a manufacturer rating, outdoors only |
| 131 | Siren table: 0 sirens inside — Honolulu 206, Hawaiʻi 10, Maui 9, Kauaʻi 2; land point beyond 3,400 ft — 110, 36, 24, 14; under 50% within range (area → people) — 108 → 74, 37 → 31, 27 → 13, 17 → 4 | §5.8 | As of build | **CHECKED** | Derived from named layers; no output file named for this table |
| 132 | People in dam evacuation zones: Honolulu 37,250; Maui 25,567; Kauaʻi 8,369; Hawaiʻi 4,545 (area-weighted before: 31,172; 26,251; 10,819; 1,360) | Dam layer plus 2020 blocks | Layer 2026-03-26 | **CHECKED** | Named layer plus method |
| 133 | Shelter sites in a dam zone: Kahilu Town Hall (Puʻukapu watershed dam, Waikoloa reservoirs 1–3); Molokaʻi Baptist Church (Kualapuʻu reservoir) | Same | Same | **CHECKED** | Named layer |

### K. Population-weighted shares (§5.9)

| # | Item | Where it came from | How current | Status | What the status rests on |
|---|---|---|---|---|---|
| 134 | 10,169 populated blocks; 279 (2.7%) TIGERweb points differ from the PL header by up to about 2 km; fallback is about 100 grid points per area | TIGERweb, PL 94-171 | 2020; fetched 2026-10-28 | **CHECKED** | 279 / 10,169 = 2.7% ✓ |
| 135 | Tsunami standard zone people: Honolulu 82,204 → 80,344; Maui 18,239 → 26,158; Kauaʻi 6,161 → 9,034; Hawaiʻi 12,462 → 12,102 | §5.9 | As of build | **CHECKED** | Consistent with tsunami likely demand at 5% ✓ |
| 136 | Extreme tsunami zone: Honolulu 177,475 → 208,201; Maui 24,391 → 38,773; Kauaʻi 6,903 → 9,862; Hawaiʻi 14,008 → 13,808 | §5.9 | As of build | **CHECKED** | Method stated |
| 137 | Tsunami likely demand: Honolulu 4,110 → 4,017; Maui 912 → 1,308; Kauaʻi 308 → 452; Hawaiʻi 623 → 605 | §5.9 | As of build | **CHECKED** | = zone people × 5% ✓ |
| 138 | Lahaina backtest unchanged: observed 1,418; model 254 / 635 / 1,423; "calibration, not validation" | `backtest.csv` | 2023 event | **CHECKED** | Named file (observed value: see row 163) |

### L. Stress tests (§5.10)

| # | Item | Where it came from | How current | Status | What the status rests on |
|---|---|---|---|---|---|
| 139 | Losing Mānoa Valley District Park (hurricane): 85 areas, 215,418 people; all ≤ 14.9 min before and ≥ 17.5 min after | `stress_tests.json` | As of build | **CHECKED** | Named file |
| 140 | Ten-largest table: 27.02 5,029 (6.2 → 24.9); 38.02 4,992 (12.2 → 23.2); 34.04 4,959 (7.3 → 22.7); 34.14 4,690 (5.6 → 21.6); 30 4,658 (2.3 → 23.5); 53 4,453 (14.9 → 20.7); 13 4,225 (9.6 → 25.0); 26 3,981 (8.1 → 22.5); East Honolulu 4.02 3,912 (14.8 → 30.3); 8 3,879 (11.2 → 26.6) | Same | As of build | **CHECKED** | Consistent with row 139's bounds ✓ |
| 141 | 861 results; settings in `config/stress_tests.json`, `config/stress_roads.json` | Same | As of build | **CHECKED** | Named files |
| 142 | Team assumptions in tests: 250 people per site; one person counted once at the higher rate; one charge a day per power-dependent person; 72-hour factors to 3 days, 2-week factors beyond; rate range 2–20%; stays 3/7/14/30 days; outages 1/3/7/14 days | `config/stress_tests.json` | n/a | **NEEDS A LIVE SOURCE** | Labelled team assumptions |
| 143 | Test 16: Chuukese and Marshallese 0 of 15 messages translated; reliability CV ≤ 40% | §5.10 | As of build | **CHECKED** | Consistent with §9 |
| 144 | Test 18: 2026 unsheltered count added (Oʻahu total only; upper bound) | `county_lines.csv` | 2026 PIT | **NEEDS A LIVE SOURCE** | Rests on the Oʻahu release (row 42) |
| 145 | Test 24 closures: Honoapiʻilani Hwy (Pali, Olowalu), Hāna Hwy (Keʻanae), Kamehameha Hwy (Waimea Bay), Kūhiō Hwy (Hanalei bridge), Hwy 11 (Kaʻū, MP 53.9), SLR 3.2 ft (SLR-XA); 45-minute cut-off rule | `config/stress_roads.json` | n/a | **NEEDS A LIVE SOURCE** | Closure locations are "team assumptions (exposed stretches)" |
| 146 | Questions for counties: earthquake and wind resilience, inter-island resupply, cell outages, school shelter duration, Survey123 capacity form | §5.10 | n/a | **CHECKED** | Self-described data gaps |
| 147 | All four counties, hurricane: 43,518 people = cots = water; earlier 43,517 people and 43,519 cots; staff per shift 2,921 | `stress_tests.json` | As of build | **CHECKED** | Sum of the county likely values = 43,517; rounding explanation is plausible |
| 148 | Maui SLR headline "+92 min to any known site; +3.8 min to a 2026 site" vs top-3 entry "tested against 2026 sites … up to 92 minutes added" | §5.10 | As of build | **NOT SUPPORTED** | The two statements give 92 min to different site sets; the text conflicts |
| 149 | Census area 320: Launiupoko 688 (62%), Māʻalaea 310 (28%), Olowalu 100 (9%), 14 outside any place; cut off in the SLR scenario | Block Assignment File | 2020 | **CHECKED** | Percentages ✓ (total 1,112) |
| 150 | Honolulu top 3: Wahiawā + Mānoa losses 306,869 (115 areas; 91,451 more than either alone); 236,444 in State-High-but-not-NRI areas; Mānoa alone 215,418 | `stress_tests.json` | As of build | **CHECKED** | 306,869 − 215,418 = 91,451 ✓ |
| 151 | Maui top 3: SLR 70,875 people (18 areas; area 320 cut off; up to 92 min); Baldwin HS + Mayor Hannibal Tavares CC 69,957; Honoapiʻilani closure 68,353 (up to 104 min; no area cut off because Kahekili Hwy remains open in the network) | Same | As of build | **CHECKED** | Named file. The 92-minute wording conflicts with row 148; whether Kahekili Hwy is usable in an event is unverified |
| 152 | Hawaiʻi top 3: Keaʻau Armory + Puʻuʻeo 48,669 (28,820 more than either alone); four-county hurricane 43,518 cots, 2,921 staff; 35,640 visitors on an average day | Same; DBEDT 7.06 | 2025 visitors | **CHECKED** | Named sources |
| 153 | Kauaʻi top 3: Kapaʻa MS + Kauaʻi HS Gym 33,883; Kalāheo NC + Kapaʻa MS 32,787 | Same | As of build | **CHECKED** | Named file |
| 154 | Unplaced flooded-highway segments: at least 5 of 369 on Oʻahu, 1 on Maui; Kaʻū re-run as a 150 m polygon (first 0.06 credits counted) | §5.10 | 2026-10-30 | **CHECKED** | Self-reported limitation |
| 155 | Second credit set: safe-zone walking 0.189 (378 pairs); closures driving 0.668 (1,336); walking 0.0585 (117); flooded highways 1.37 (2,740); "Total 12.3885 of 22" | §5.10 | 2026-10-30 | **NOT SUPPORTED** | Lines are ✓ at 0.0005 per pair, but 10.10 + 0.189 + 0.668 + 0.0585 + 1.37 = 12.3855, not 12.3885 |

### M. What-if engine (§5.11)

| # | Item | Where it came from | How current | Status | What the status rests on |
|---|---|---|---|---|---|
| 156 | Input ranges and defaults: rate 1–25% (default 3% hurricane, 5% others); stay 1–30 days (3); outage 0–14 (0); people per vehicle trip 4–40 (20, team assumption); support share 0–30% (ACS disability via SVI); capacity blank or 2009 PDC (4 sites matched) | `app/whatif.js` | As of build | **CHECKED** | Defaults consistent with §5.5 rates. The 20-per-trip value is an unsourced assumption |
| 157 | Factors: floor 20 sq ft per person to 3 days, 40 beyond; toilets 1 per 40 to 3 days, 1 per 20 beyond | `scripts/model_needs.py` | n/a | **NOT SUPPORTED** | No source named in the text (§10.4 cites Florida DEM only for meals, water and staffing) |
| 158 | Meals 2 per person per day, water 1 gal per person per day, staff ratios (Florida DEM 2010); children's area 1 per 12 children | §5.11, §10.4 | 2010 | **NEEDS A LIVE SOURCE** | Named agency and year, no document title or URL. The children ratio has no source |
| 159 | One cot per person in shelter | §10.4 | n/a | **NEEDS A LIVE SOURCE** | Labelled team assumption; "no published per-person cot factor is cited" |
| 160 | Pets: dogs 44.6% of households, cats 26% | §5.11 | n/a | **NOT SUPPORTED** | No source given |
| 161 | Checks: reproduces all 20 scenarios; Python reference matches JS for 50 random input sets; 44 px targets; works at 390 px | §5.11 | As of build | **NEEDS A LIVE SOURCE** | Claims about code and tests |

### N. State Hub layers (§5.12)

| # | Item | Where it came from | How current | Status | What the status rests on |
|---|---|---|---|---|---|
| 162 | Test 23a: 126 areas; over 15 min walk — Honolulu 23 of 76 (5,298 people without a car; 2 over 30 min), Maui 3 of 24 (463), Hawaiʻi 2 of 15 (461; 1 over 30 min, longest 79.5 min), Kauaʻi 1 of 11 (292) | `hub_layers_summary.json` | 2026-10-30; Maui zones 2013 | **CHECKED** | 76 + 24 + 15 + 11 = 126 ✓ |
| 163 | Lahaina observed 1,418 people in shelters (Maui Now); date given as 2023-08-11 (§6) while the fire is dated "August 8, 2023" (§10.10) | `past_events.csv`, `backtest.csv` | 2023 | **NEEDS A LIVE SOURCE** | News outlet with no article title, URL or date in the text. Whether 2023-08-11 is the count date or the fire date is unclear |
| 164 | Fire Risk vs NRI: Honolulu 44/70/39, 29%, 396,661 vs 314,263; Maui 8/18/4, 27%, 87,832 vs 48,834; Hawaiʻi 4/7/7, 22%, 47,251 vs 57,557; Kauaʻi 1/3/4, 13%, 21,359 vs 21,633. "High" = at least half of people in a High area (team assumption); NRI footprint = top 25% per county | `hub_layers_summary.json` | Fire layer 2007/2022 | **CHECKED** | Agreement % ✓; NRI people = wildfire likely ÷ 5% ✓ |
| 165 | Flooded highways: "282 features (650 line pieces)": Oʻahu 369 (28.5 km), Maui County 234 (Maui 105, Molokaʻi 107, Lānaʻi 22; 22.0 km), Kauaʻi 173 (10.4 km), Hawaiʻi 3 (0.1 km) | Climate/71 layer | 2017 report; fetched 2026-10-30 | **NOT SUPPORTED** | The listed pieces sum to 779, not 650 (the Maui County split 105 + 107 + 22 = 234 is ✓) |
| 166 | PDC 2009: 237 shelters, 30 with capacity above 0, 203 matched, 26 with capacity (4 of the 2026 sites + 22 DOE); Baldwin HS 2,078, Kauaʻi HS Gym 2,283, Kapaʻa MS 467, Waimea Canyon MS 2,649; matching rule: shared word, same school level, within 400 m | PDC via third-party copy | 2009-10-08 | **NEEDS A LIVE SOURCE** | Third-party copy of 2009 data (row 55). A gym capacity of 2,283 [VERIFY] |

### O. DHS metrics (§6)

| # | Item | Where it came from | How current | Status | What the status rests on |
|---|---|---|---|---|---|
| 167 | Metric 1: 100% (436/436), 99.8% (435/436), 20 maps | `coverage.json`, playbooks | As of build | **CHECKED** | See row 67 |
| 168 | Metric 2: high estimate 0.3% from observed; rate 1,418 / 12,702 = 0.112; observed count includes visitors and evacuees from other fires | `backtest.csv`, `past_events.csv` | 2023 | **CHECKED** | Arithmetic ✓; the observed value itself is row 163 |
| 169 | Validation needs 2026 occupancy for Lala, Lowell, Nolo; the repo has no occupancy | §6(2) | 2026 | **CHECKED** | Self-disclosed gap |
| 170 | Baseline at least 2 working days per county per event, about 8 statewide; target under 1 working day | Team assumption | n/a | **NEEDS A LIVE SOURCE** | Labelled assumption "to be confirmed with DHS" |
| 171 | Full rebuild 44.0 s on an Apple M4 laptop, 14 build steps, measured 2026-10-28 | `scripts/time_rebuild.py`, `rebuild_timing.json` | 2026-10-28 | **CHECKED** | Named file plus date; 14 steps match the README list ✓ |
| 172 | 427 automated tests, about 3 minutes | `tests/` | As of build | **NEEDS A LIVE SOURCE** | Claim about the test suite |
| 173 | Flood-zone refresh paced at 1 s per point × 311 points = "at least 5.2 minutes"; refresh not timed end to end | §6(3) | n/a | **CHECKED** | 311 s = 5.18 min (rounded to 5.2; "at least" slightly overstates) |
| 174 | Measurement plan: timed tabletop; start = hazard selected, stop = draft approved | §6(3) | Proposed | **CHECKED** | Proposal only; not done |

### P. Roles, decisions, communication (§7)

| # | Item | Where it came from | How current | Status | What the status rests on |
|---|---|---|---|---|---|
| 175 | 20 partner entries; capacity and contact fields empty; 405 need lines in `match_plan.csv` | `config/partners.json`, `match_plan.csv` | As of build | **CHECKED** | Named files |
| 176 | Hurricane season start June 1; Hurricane Watch 48 h; Hurricane Warning 36 h | `config/decision_points.json` | No date | **NEEDS A LIVE SOURCE** | Program definitions; URLs not shown in text |
| 177 | Triggers: Red Flag Warning, county evacuation order, PTWC Tsunami Warning, Flash Flood Warning, Coastal Flood Warning | Same | No date | **NEEDS A LIVE SOURCE** | Same |
| 178 | Languages per county: top 6 plus Hawaiian, Chuukese, Marshallese where above the suppression threshold | `config/communication.json` | As of build | **CHECKED** | Team rule |

### Q. Low connectivity, AI use, limitations (§8–§10)

| # | Item | Where it came from | How current | Status | What the status rests on |
|---|---|---|---|---|---|
| 179 | Data bundle 814 KB; tested in airplane mode in Chrome | §8 | Undated | **NEEDS A LIVE SOURCE** | Claim about the app |
| 180 | Playbooks 27–30 pages, US Letter; annexes Hawaiʻi 26, Kauaʻi 32, Maui 32, Honolulu 34 pages; smallest text 9 pt | §8 | Undated | **NEEDS A LIVE SOURCE** | Files not supplied |
| 181 | Census API "began to require a key" | §9.2 | Undated | **NOT SUPPORTED** | No source or date |
| 182 | 15 English messages (3 × 5 hazards), drafts in 9 languages; status DRAFT, approved = no; a test blocks approval without a named reviewer and date; no Chuukese or Marshallese drafts | `data/sources/messages/` | As of build | **CHECKED** | Named folder; test claim not run |
| 183 | AI (Claude) compiled the activation table from press releases and news; a team member reviewed it | §9.3 | 2026 | **CHECKED** | Self-disclosure (no review date given) |
| 184 | §10.4 assumption list: tsunami/flood 2/5/11%, wildfire low and central, top-25% footprint, one outlet per power-dependent person, one cot per person | `config/planning_factors.json` | n/a | **NEEDS A LIVE SOURCE** | Labelled "team_assumption" |
| 185 | SVI "less than well" vs PUMS "less than very well" definitions differ | §10.7 | n/a | **CHECKED** | Self-disclosed |
| 186 | Lahaina CDP 10,162 ±1,143 (ACS 2020-2024) vs 12,702 (2020 Census); areas 314.02, 314.04, 314.05; fire "August 8, 2023" | §10.10 | 2020; 2020-2024 | **CHECKED** | Named tables. The fire date itself has no cited source (see row 163) |
| 187 | ACS 2025 1-year "released October 29, 2026" | §10.11 | 2026-10-29 | **CHECKED** | Same as row 35 |
| 188 | Oʻahu PIT total 4,539 (City and County of Honolulu release 2026-05-21); neighbor-island CoC is Bridging the Gap | §10.12 | 2026 | **NEEDS A LIVE SOURCE** | No URL; primary report not found |
| 189 | E_MUNIT (10+ unit buildings) counts housing units, not people | §10.12 | SVI 2022 | **CHECKED** | Named variable |
| 190 | Hawaiʻi State Office of Language Access (DOH) keeps an interpreter roster and publishes Chuukese/Marshallese materials, https://health.hawaii.gov/ola/ | §10.9 | Undated | **NEEDS A LIVE SOURCE** | URL with no access date |
| 191 | We Are Oceania helpline offers Chuukese and Marshallese help (Civil Beat COVID-19 resource guide URL) | §10.9 | COVID-era listing | **NEEDS A LIVE SOURCE** | Dated listing; the plan itself says to confirm availability |
| 192 | Survey123 county form proposal (site, floor area, cots, generator, pet space, accessible toilets, pledges) | §10.14 | Proposed | **CHECKED** | Proposal only |
| 193 | Team: Tiffanie Nguyen (Captain, UI), Long Nguyen (data and AI), Kim Quynh Do (UI, Vietnamese review) | README, §11 | Current | **CHECKED** | Self-stated |

**Status counts (193 rows): CHECKED 138 · NEEDS A LIVE SOURCE 46 · NOT SUPPORTED 9.**

There are 9 NOT SUPPORTED rows:
- the header date (row 1);
- 5 vs 4 sites under review (row 74);
- 427 vs 432 populated areas (row 121);
- the 92-minute SLR wording (row 148);
- the credit total 12.3885 (row 155);
- the floor-space and toilet factors (row 157);
- the pet ownership shares (row 160);
- the 650 flooded-highway pieces (row 165);
- the Census API key claim (row 181).

## Step 2 – The three facts that matter most to the decision

1. **Capacity is unknown everywhere.** Every pledged-capacity field is blank, and every stress test and what-if result uses a 250-people-per-site team assumption (§7, §10.1, §10.14). The MATCH step has no matched supply.
2. **The only "validation" is calibration.** Lahaina 1,418 was used to set the wildfire high rate. No out-of-sample event has been tested, and the tsunami and flood rates (2/5/11%) are pure team assumptions (§5.5, §6(2)).
3. **The shelter universe is the 30 sites opened in 2026 events,** compiled by AI from press releases, with 7 in Honolulu. All access, drive-time and "people pushed past 15 minutes" figures depend on that sample, not on county-designated shelter lists (§5.2, §5.7, §5.10, §9.3).

## Step 3 – What should be in the plan and is not (the skeptic's list)

- **DHS's own program data.** The plan has no de-identified DHS program data and no data-sharing or governance path for it, even though fragmented program data is the core problem it quotes (§1).
- **Evidence of user testing.** Nothing shows a test with any county or DHS planner, and no county sign-off on footprints, roles or triggers is recorded.
- **County-designated shelter lists,** or an explanation of why they cannot be used.
- **Out-of-sample validation.** It needs 2026 occupancy data, and there is no date by which that will be requested.
- **An owner, refresh cycle, hosting plan and cost after the competition.** This includes the Esri credits and token, the domain, and who re-runs the pipeline.
- **Independent review of AI-produced inputs.** That covers the 30-site table, the source checks, and the translations, Hawaiian and Pidgin included.
- **Missing hazards and settings.** Earthquake, shelter in place and high-rise power loss are not modelled (§10.8). Medical or special-needs shelter types are not separated from general shelters.
- **Missing population groups.** Care-facility residents are not modelled. Visitors in tsunami zones are not counted.
- **Disaster-condition travel times and transport capacity.** Bus and paratransit capacity are missing, and the vehicle-trip size is unsourced.
- **Inter-island logistics** for Molokaʻi, Lānaʻi and Niʻihau, raised only as a question.
- **A cost or staffing estimate** for the human review the plan relies on.

## Step 4 – Two downside scenarios

**Scenario A – Hurricane season 2027 starts with capacity still blank (from 2027-06-01, the season start the plan uses).**
- *Consequence:* County and DHS staff use the playbook demand figures (for example Honolulu likely 30,303) and the site lists as if they were a plan. With no pledged capacity, the "gap" column still reads "unknown". The 2026 activation sites may not open, or may be full. Precise-looking numbers create false confidence, and partner calls happen during the event anyway, which is the problem the challenge describes.
- *Early warning signs (before 2027-06-01):*
  - no county has run the Survey123 form;
  - `config/partners.json` capacity fields are still empty;
  - the timed tabletop (§6(3)) has not been scheduled;
  - the counties have not provided 2026 occupancy counts.

**Scenario B – The data goes stale and is misused in a no-notice Maui event (any time after 2026-10-28; the risk grows with each planning cycle).**
- *Consequence:* A wildfire or tsunami hits West Maui. The app shows pre-fire Lahaina populations, Maui safe zones from 2013, and 2026-only sites. A cached PWA shows "data as of 2026-10-28" months or years later. Residents or partners treat the public demo as a shelter list, despite the disclaimer.
- *Early warning signs:*
  - no rebuild after the competition, so the "data as of" date stops moving;
  - new county shelter activations do not appear in `county_shelter_activations.csv`;
  - the demo domain is still public with no named owner;
  - the Esri token or credits lapse, so refreshes fall back to the committed summary;
  - no updated Maui safe-zone layer has been fetched.

I don't know the actual likelihood of either scenario.

## Step 5 – Personal or sensitive information in the text

- **Named individuals.** Tiffanie Nguyen, Long Nguyen and Kim Quynh Do are named, with roles (README, §9.4, §11). That is normal attribution, but the team should confirm all three consent to public naming. §9.4 publicly assigns Kim Quynh Do a review duty.
- **Personal GitHub handle.** The mirror URL contains "nguyenhuulong2222", a personal account handle. The team should consider whether it should appear in a DHS submission.
- **Named care facilities flagged as in hazard zones.** "Hale Malamalama" (a nursing home) and dialysis centres are named by location. These are public CMS facilities and not PII, but naming vulnerable-population facilities with hazard flags in a public document is sensitive. DHS may prefer counts in the public version.
- **Residual small-number disclosure.** The text itself says suppressed per-area values can be derived by subtraction from county totals (README; §10.16). The data is public estimates, not records, but the residual risk is stated rather than closed.
- **Small-population figures.** Kalawao 82 (2020) and 67 ±25, and Census area 320's place counts (Olowalu 100), are shown. These are aggregate public Census figures. I don't know whether DHS considers them sensitive.
- **No PII found.** No addresses of individuals, no client data, and no tokens or credentials appear in the text.
