# Hawaiʻi ESF-6 AFN Planning Framework – AI-Developed Plan

**HAIC 2026 · DHS challenge "Enhancing ESF-6 Planning Through AI-Supported Insights"**
**Team Kahu Ola** · Data as of 2026-10-28 · Official repository: https://github.com/HAIC-2026/Kahu-Ola (mirror: https://github.com/nguyenhuulong2222/haic2026-esf6-shelters). All numbers below are read from files in it.

> Planning aid. Supports, does not replace, county emergency plans. Not an official shelter list.
> Every role, decision point and message in this plan is **proposed – supports, does not replace, county plans**.

Sources are cited as file paths. "Challenge PDF" = `HAIC_AI Challenge_Submission_DHS_Disaster_2026.pdf` (Hawaiʻi DHS, 2026 HAIC AI Challenge Submission), cited by page.

---

## 1. Problem

The challenge PDF describes AFN planning that is fragmented and manual:

- "Information about AFN individuals and households, hazard exposure, and available resources is fragmented across programs, partners, and agencies, so no shared operating picture exists before or during a disaster." (p. 4)
- Pain points (p. 3): Counties and the State do not co-plan, and each County defines sheltering its own way. There is "no single, current view of where AFN populations live relative to hazard type". Needs "are estimated ad hoc for each event". "Partner resources and roles are not consistently mapped". Privacy rules limit sharing of client data.
- Manual steps (p. 3): "Pulling program and provider reports, cross-referencing lists with hazard zones, contacting partners (phone, text, email) to confirm shelter, transport, staffing, and supply capacity."
- Repetitive work (p. 4): "Recompiling shelter and refuge lists, locations, and hours … calling partners to confirm capacity for each planning cycle and each event."
- Constraints (p. 5): de-identified data only, no PII; the plan must work alongside existing state and county plans, "not replace them"; it must be usable "during high-stress, low-connectivity conditions".

Scope (p. 5–6) has three parts: population mapping, resource identification and coordinated response. We map them to **MAP → MODEL → MATCH**.

## 2. Approach: MAP → MODEL → MATCH

| Step | What it does | Code | Output |
|---|---|---|---|
| **MAP** | CMIST counts for 436 Census areas (Census tracts) in 4 counties, joined to hazard exposure (FEMA NRI v1.20, State tsunami evacuation and extreme zones); HHS emPOWER power-dependent counts allocated to Census areas | `scripts/fetch_data.py`, `scripts/build_map.py` | `data/processed/afn_tracts.geojson`, `coverage.json` |
| **MAP** (sites) | Sites the counties actually opened in 2026 events, located from public sources; site-level FEMA flood zone | `scripts/build_shelters.py`, `scripts/geocode_shelters.py`, `scripts/fetch_flood_zones.py` | `data/processed/shelters_2026.geojson`, `data/sources/site_flood_zones.csv` |
| **MODEL** | For each county × hazard (4 × 5 = 20): footprint, at-risk population, shelter demand (low / central / high), CMIST counts, resources (cots, space, water, meals, toilets, staff, power outlets, pets), usable sites | `scripts/model_needs.py`, `config/planning_factors.json` | `data/processed/needs_by_scenario.json`, `needs_by_tract.csv`, `backtest.csv` |
| **MATCH** | Each need → proposed lead and support partner types → pledged capacity (blank) → gap; decision points; communication pathways; top 10 outreach Census areas | `scripts/match.py`, `config/partners.json`, `config/decision_points.json`, `config/communication.json` | `data/processed/match_plan.json`, `match_plan.csv` |
| **Deliver** | 20 printable playbooks and an offline web app | `scripts/build_playbooks.py`, `scripts/build_app_data.py` | `playbooks/`, `app/` |

The pipeline is deterministic Python (standard library only). AI is not needed to run it, and it does not call AI.

## 3. Data sources and dates

All sources are public. Fetch dates are recorded in the build metadata (`data/processed/afn_tracts.geojson` → `metadata.sources`) and in each source table.

| Source | Use | Vintage / fetched |
|---|---|---|
| CDC/ATSDR Social Vulnerability Index 2022, by Census area | CMIST proxies (limited English, disability, 65+, under 18, no vehicle, group quarters) | SVI 2022; fetched 2026-10-27 |
| FEMA National Risk Index v1.20, by Census area (hurricane, wildfire, tsunami, inland and coastal flooding) | Hazard footprint (NRI risk score) | v1.20; fetched 2026-10-27 |
| Hawaiʻi Statewide GIS: tsunami evacuation zones and extreme tsunami evacuation zones | Tsunami footprint; site exclusion | fetched 2026-10-27 |
| Hawaiʻi Statewide GIS "State DFIRM" (FEMA flood hazard areas, downloaded from FEMA 6/15/26) | Site-level flood zone for 311 site points | queried 2026-10-27 (`data/sources/site_flood_zones.csv`) |
| HHS emPOWER, county level (`Power_Dependent_Devices_DME`) | Power-dependent residents, allocated to Census areas by 65+ share (estimate) | fetched 2026-10-27 |
| Hawaiʻi DOE public schools (Statewide GIS) | Candidate sites (292 schools) | fetched 2026-10-27 |
| County announcements of shelters opened in 2026 events (official county releases; earlier news reports kept in notes) | Commonly used shelters | `data/sources/county_shelter_activations.csv`, one official source URL per row |
| U.S. Census Geocoder; Hawaiʻi and Maui County address points | Locating shelter addresses | `data/sources/geocodes.csv`, source URL per row |
| ACS PUMS 2019-2023 5-year, Hawaiʻi person file | Detailed languages (limited English) | `data/sources/languages_by_county.csv` |
| DBEDT State of Hawaii Data Book 2024, Table 1.44 | Validation of the language counts | cited in `tests/test_languages_pums.py` |
| ACS table C16001 (2020-2024 5-year) | Secondary language source | `data/sources/languages_by_county_c16001.csv` |
| NWS / NHC / CPHC / PTWC product definitions | Decision-point triggers | URLs in `config/decision_points.json` |
| USGS GNIS Domestic Names, Hawaii (Board on Geographic Names spellings) | Hawaiian spelling (ʻokina, kahakō) of every community name people read | `data/sources/place_display_names.csv` |
| Census Bureau Population Estimates, Vintage 2025 (`co-est2025-alldata`, `cc-est2025-alldata-15`) | County totals July 1, 2025; broad race groups | released 2026-06-25; `data/sources/county_population_2020_2025.csv` |
| ACS 2020-2024 5-year: B01003 (places, counties), B02001, B02008–B02012, B03002, B02015, B02016, B02018, B02019 | Communities by island; detailed race/ethnicity by county | `data/sources/communities_by_island.csv`, `race_ethnicity_by_county.csv` |
| 2020 Census PL 94-171 (P1) and DHC-A (T01001 by POPGROUP) | 2020 baseline and cross-check | same files, one table ID and URL per row |
| 2020 Census Block Assignment File (place/CDP) and 2020 PL 94-171 block population (P1_001N) | Community name for every Census area, weighted by where its people live ("Waikapū / Waiheʻe-Waiehu", Census area 308); TIGERweb CDP polygons only for the 4 Census areas with no 2020 population | `data/sources/tract_communities.csv`, `tract_cdp_population_2020.csv` |
| DBEDT State Data Book 2025, Table 01.12 (island and CDP) | Assigns every CDP to an island; island totals | `data/sources/communities_by_island.csv` |
| ACS 2020-2024 5-year, Census-area tables B18102, B18103, B18104, B09020 | Hearing, vision and cognitive difficulty; age 65 and older living alone | `data/sources/cmist_detail_by_tract.csv` (fetched 2026-10-27) |
| Bridging the Gap, 2026 Point-in-Time Count Report (Hawaiʻi, Maui, Kauaʻi; night of Jan 25, 2026), https://www.btghawaii.org/media/uploads/2026_btg_pit_report_final.pdf | People experiencing homelessness by county (separate county line) | `data/sources/county_lines.csv` (fetched 2026-10-27) |
| Partners In Care 2026 Point-in-Time Count for Oʻahu (Jan 26, 2026), as released by the City and County of Honolulu on 2026-05-21 | People experiencing homelessness, Oʻahu | `data/sources/county_lines.csv` |
| DBEDT State of Hawaiʻi Data Book 2025, Table 7.06 (average daily visitor census, 2025) | Visitors on island (separate county line) | `data/sources/county_lines.csv` (fetched 2026-10-27) |

## 4. Privacy model

- **Aggregate data only.** The model works on Census-area and county totals. No individual records, no client data, no registries (challenge PDF p. 5: "no personally identifiable information").
- The only names and addresses in the outputs are those of **public facilities** (shelters, schools). Tests check that the app data bundle has no person-level fields (`tests/test_deliverables.py`).
- The language table comes from Census microdata (PUMS). The microdata stays in `data/raw/` (gitignored) and is never committed or printed. Outputs are aggregates, and any cell under 100 weighted people or under 10 sample persons is suppressed (149 of 194 area × language cells).
- The web app has no accounts, no analytics and no location access, and it makes no calls to outside services. It only reads its own data file.

## 5. Key findings

### 5.1 Coverage
- **CMIST data for 436 of 436 Census areas (100%)** in all four counties. FEMA NRI joined for **435 of 436** (one Honolulu Census area has no NRI record). Source: `data/processed/coverage.json`.

### 5.2 Shelters: no standing public list
- Counties announce sites when they open them. The challenge PDF lists "recompiling shelter and refuge lists" as repetitive work (p. 4). We compiled **30 sites opened in 2026 events** (Kauaʻi 5, Honolulu 7, Maui 8, Hawaiʻi 10). The events were April 2026 severe weather, Hurricane Lala, Hurricane Lowell, Tropical Storm Nolo, and the Olowalu brush fire. All **30 of 30 sites have an official county source** (kauai.gov, honolulu.gov, mauicounty.gov, hawaiicounty.gov); 0 rely on news media only. Sixteen sites were first found in news reports; we then matched each to the county release and kept the news URL in the notes. Names and addresses matched the county releases. Two naming variants are recorded in the notes rather than changed: "Yano Memorial Hall" and "Hisaoka Gym" appear in one Hawaiʻi County release. The Maui County and Hawaiʻi County pages block automated downloads (HTTP 403); their shelter names and addresses were confirmed by a team member reading the county page on 2026-10-27. 29 of 30 are located. The Mayor Hannibal Tavares Community Center (Pukalani) has no verifiable point and is left unlocated. Source: `data/processed/shelters_2026.geojson`.

### 5.3 Sites unsuitable by hazard
- **Lahaina Civic Center Gym** (opened twice in 2026): inside the tsunami evacuation zone, so it is excluded for tsunami. Its FEMA flood zone is X.
- **Kilohana Recreation Center** (Molokaʻi): inside the tsunami evacuation zone **and** in FEMA flood zone **AE** (Special Flood Hazard Area). It is excluded for tsunami and flagged "check" for both flood hazards.
- 22 candidate schools are in an SFHA; 22 Honolulu candidate schools are in zone D (flood risk undetermined, counted separately, never as usable). Source: `data/processed/shelters_2026.geojson`, `candidates.geojson`, `needs_by_scenario.csv`.

### 5.4 Languages (validated against DBEDT)
- Our statewide counts of people who speak English less than "very well" **match DBEDT Data Book 2024, Table 1.44 exactly** for all 10 top languages (e.g. Ilocano 34,269; Tagalog/Filipino 27,582; Chinese 21,856; Japanese 17,683). Source: `data/sources/pums_language_state_summary.csv`, test `tests/test_languages_pums.py`.
- **Ilocano is #1 in every area.** On Hawaiʻi Island, **Hawaiʻi Creole English (Pidgin, "Other English-based Creole languages") is #2** (2,040 ±740). ACS table C16001 lumps all of these into "Other Asian and Pacific Island languages".
- Kauaʻi and Maui share one Census microdata area (PUMA 00100), so they share one language list (`data/sources/puma_county_2020.csv`).

| Area | #1 | #2 | #3 |
|---|---|---|---|
| Kauaʻi + Maui | Ilocano 9,131 | Tagalog/Filipino 5,074 | Spanish 1,711 |
| Honolulu | Ilocano 21,729 | Tagalog/Filipino 21,584 | Chinese 20,695 |
| Hawaiʻi | Ilocano 3,409 | Pidgin 2,040 | Japanese 1,408 |

### 5.5 Shelter demand by county × hazard

**County totals are upper bounds:** they assume every at-risk Census area is hit at once. The "largest single community" column is the highest-demand Census area, which is a realistic one-community scenario. Source: `data/processed/needs_by_scenario.json`, `needs_by_tract.csv`.

| County | Hazard | May need a public shelter: low / **likely** / high (people) | Largest single community (Census area): likely shelter demand |
|---|---|---|---|
| Kauaʻi | Hurricane | 1,470 / **2,205** / 3,676 | Hanamāʻulu / Puhi (Census area 404.01): 225 |
| Kauaʻi | Wildfire | 433 / **1,082** / 2,423 | Wailua Homesteads / Kapaʻa (Census area 402.04): 302 |
| Kauaʻi | Tsunami | 123 / **308** / 678 | Kapaʻa (Census area 403.02): 68 |
| Kauaʻi | Inland flooding | 428 / **1,070** / 2,354 | Līhuʻe (Census area 405): 365 |
| Kauaʻi | Coastal flooding | 384 / **959** / 2,110 | Līhuʻe (Census area 405): 365 |
| Honolulu | Hurricane | 20,202 / **30,303** / 50,505 | Kapolei (Census area 115): 347 |
| Honolulu | Wildfire | 6,285 / **15,713** / 35,197 | Kapolei (Census area 115): 579 |
| Honolulu | Tsunami | 1,644 / **4,110** / 9,042 | Māʻili (Census area 96.10): 302 |
| Honolulu | Inland flooding | 7,389 / **18,473** / 40,641 | Kapolei (Census area 115): 579 |
| Honolulu | Coastal flooding | 4,868 / **12,170** / 26,775 | Lāʻie (Census area 102.02): 349 |
| Maui | Hurricane | 3,296 / **4,944** / 8,241 | Waikapū / Waiheʻe-Waiehu (Census area 308): 242 |
| Maui | Wildfire | 977 / **2,442** / 5,469 | Wailuku (Census area 310.01): 349 |
| Maui | Tsunami | 365 / **912** / 2,006 | Kīhei (Census area 307.13): 128 |
| Maui | Inland flooding | 1,053 / **2,633** / 5,792 | Waikapū / Waiheʻe-Waiehu (Census area 308): 403 |
| Maui | Coastal flooding | 734 / **1,834** / 4,035 | Kahului (Census area 319): 266 |
| Hawaiʻi | Hurricane | 4,043 / **6,065** / 10,108 | Hawaiian Paradise Park (Census area 210.14): 244 |
| Hawaiʻi | Wildfire | 1,151 / **2,878** / 6,446 | Hawaiian Paradise Park (Census area 210.14): 407 |
| Hawaiʻi | Tsunami | 249 / **623** / 1,371 | Kailua (Census area 216.08): 99 |
| Hawaiʻi | Inland flooding | 1,310 / **3,276** / 7,207 | Hawaiian Paradise Park (Census area 210.14): 407 |
| Hawaiʻi | Coastal flooding | 1,079 / **2,698** / 5,937 | Hōnaunau-Nāpōʻopoʻo (Census area 213): 369 |

Shelter-seeking rates (`config/planning_factors.json`): hurricane 2 / 3 / 5% (South Carolina EMD Annex G). Wildfire high 11.2%, the observed Lahaina 2023 rate (central and low are team assumptions). Tsunami and flood 2 / 5 / 11% (team assumption). Each scenario also has CMIST counts, resources (cots, floor space, water, meals, toilets, staff, power outlets, pet households) and an extreme-zone number for tsunami. These are in the playbooks.

### 5.6 Who lives where

Census publishes detailed race only down to county. **Honolulu County is Oʻahu and Hawaiʻi County is Hawaiʻi Island**, so those are island figures; **Maui County** (Maui, Molokaʻi, Lānaʻi, Kahoʻolawe) and **Kauaʻi County** (Kauaʻi, Niʻihau) are multi-island. Sources: `data/sources/county_population_2020_2025.csv`, `communities_by_island.csv`, `race_ethnicity_by_county.csv` (built by `scripts/build_demographics.py`; every row carries its table ID, URL and vintage).

**County population, 2020 Census → July 1, 2025 (Vintage 2025):** Honolulu 1,016,508 → 988,703 (−2.7%); Hawaiʻi 200,629 → 210,043 (+4.7%); Maui 164,754 → 160,592 (−2.5%); Kauaʻi 73,298 → 73,400 (+0.1%); Kalawao 82 → 82.

**Largest communities (Census Designated Places), ACS 2020-2024 5-year.** Island totals and the place-to-island assignment are from DBEDT Data Book 2025 Table 01.12.

| Island (ACS total) | Largest communities (population ± 90% MOE) | Outside any CDP |
|---|---|---|
| Oʻahu (1,001,146) | Urban Honolulu 345,482 ±70; East Honolulu 51,360 ±2,103; Pearl City 44,547 ±1,921; Waipahu 40,482 ±2,530; Kailua 39,640 ±1,744 | 16,007 (1.6%) |
| Hawaiʻi Island (205,769) | Hilo 50,404 ±2,228; Kailua (Kona) 21,818 ±2,034; Hawaiian Paradise Park 13,203 ±1,721; Kaiminani 11,465 ±1,347; Waimea 9,286 ±1,189 | 13,267 (6.4%) |
| Maui (152,418) | Kahului 28,288 ±1,914; Kīhei 21,567 ±1,407; Wailuku 16,926 ±1,455; Waiheʻe-Waiehu 10,988 ±1,300; Lahaina 10,162 ±1,143 | Maui County, all islands: 4,225 (2.6%) |
| Molokaʻi (8,728, includes Kalawao) | Kaunakakai 4,360 ±985; Kualapuʻu 2,535 ±421; ʻUalapuʻe 440 ±168; Maunaloa 293 ±133 | (in Maui County figure) |
| Lānaʻi (3,443) | Lānaʻi City 3,393 ±431; Manele 50 ±33 | (in Maui County figure) |
| Kauaʻi (73,731) | Kapaʻa 11,094 ±1,301; Līhuʻe 7,901 ±872; Wailua Homesteads 5,431 ±920; Hanamāʻulu 4,972 ±832; Kalāheo 4,435 ±676 | Kauaʻi County, both islands: 2,722 (3.7%) |
| Niʻihau | No Census Designated Places (DBEDT note) | (in Kauaʻi County figure) |

**Largest detailed groups by county, ACS 2020-2024 5-year, alone or in any combination (% of county).** "Alone" counts are much smaller because about a quarter of residents report two or more races (27.0% statewide, B02001).

| County | #1 | #2 | #3 | #4 |
|---|---|---|---|---|
| Honolulu (Oʻahu) | Filipino 252,603 (25.2%) | Japanese 241,669 (24.1%) | Native Hawaiian 196,688 (19.7%) | Chinese 173,593 (17.3%) |
| Hawaiʻi (Hawaiʻi Island) | Native Hawaiian 63,390 (30.8%) | Filipino 45,200 (22.0%) | Japanese 38,478 (18.7%) | Chinese 26,464 (12.9%) |
| Maui County (multi-island) | Filipino 49,560 (30.1%) | Native Hawaiian 41,614 (25.3%) | Japanese 23,883 (14.5%) | Chinese 18,146 (11.0%) |
| Kauaʻi County (multi-island) | Filipino 24,637 (33.4%) | Native Hawaiian 18,341 (24.9%) | Japanese 13,705 (18.6%) | Chinese 7,500 (10.2%) |

- **Native Hawaiian, statewide:** 320,047 ±5,615 alone or in any combination (22.1%) and 87,937 ±3,241 alone (ACS). The 2020 Census DHC-A count is 317,497 alone or in any combination and 94,025 alone.
- **Pacific Islander groups with small counts and large margins:** Samoan 36,705 ±2,419, Tongan 9,504 ±1,335, Marshallese 9,232 ±1,460, Chamorro 7,246 ±1,260, Chuukese 5,153 ±1,589 and other Micronesian 17,765 ±2,554 statewide (alone or in any combination). Outside Honolulu several county estimates have margins as large as the estimate, and some differ widely from the 2020 count (e.g. Chuukese, Hawaiʻi County: ACS 114 ±95, 2020 Census 715). Use both columns, not one number.
- **Suppressed in 2020 DHC-A:** "Other Micronesian" in every county (published statewide only: 11,481 alone), Chuukese in Kauaʻi County, and most groups in Kalawao. These cells are left blank, not estimated.

**How this guides outreach.** Together with the language table (§5.4), these numbers tell each county which communities to reach through which trusted messengers:
- Filipino residents are the largest group in Honolulu, Maui and Kauaʻi counties, and Ilocano and Tagalog/Filipino are the top two limited-English languages in Kauaʻi + Maui and in Honolulu. Messages in those languages can go through the trusted-messenger channel (faith-based groups and community nonprofits).
- Native Hawaiian residents are about a quarter to a third of each neighbor-island county. OHA and Native Hawaiian organizations are listed trusted messengers (`config/communication.json`), and Hawaiian is always in each county's message languages.
- Marshallese, Chuukese and other Micronesian residents are few in number, but limited-English speakers are counted: Chuukese 4,948 and Marshallese 1,021 in Honolulu, Marshallese 538 on Hawaiʻi Island and 633 in Kauaʻi + Maui (`languages_by_county.csv`). Those messages need human translators and Micronesian-led community partners (§10, item 9).
- Roles stay "proposed – to be confirmed with partner". The numbers say where people live; they say nothing about individual needs.

## 6. The three DHS metrics

The challenge PDF (p. 7) sets three measurable goals.

**(1) Hazard-specific AFN maps covering every county – target 100% of Census areas.**
Result: CMIST coverage **100% (436/436 Census areas)**, NRI hazard join **99.8% (435/436)**, for all 5 hazards and 4 counties: 20 maps, one in each playbook (`playbooks/*.pdf`) and in the app.

**(2) Needs estimates validated "within an agreed margin against past events".**
Result: Lahaina wildfire, 2023-08-11. Observed 1,418 people in shelters (Maui Now). Model 254 / 635 / **1,423** (low / central / high). The observed count is **inside the band**, and the high estimate is 0.3% from it (`data/processed/backtest.csv`).
**This is a calibration event, not validation:** the high wildfire rate was set from this same event (1,418 / 12,702 = 0.112), so agreement is expected. The observed count also includes visitors and evacuees from other fires (`data/sources/past_events.csv`).
**For true validation** we need an event the model has not seen: the number of people sheltered per site and day in the **2026 events (Hurricane Lala, Hurricane Lowell, Tropical Storm Nolo)**, from the counties. The repo has which sites opened, but **not** how many people used them.

**(3) Time to produce a coordinated needs-and-resources plan.**
The challenge PDF gives no baseline number ("Teams may propose their own baseline and target time", p. 7).
- **Baseline (team assumption, to be confirmed with DHS):** at least **2 working days per county per event**, about 8 working days statewide. Reasoning: the manual steps DHS describes (p. 3–4): pull program and provider reports, cross-reference lists with hazard zones, recompile shelter lists, and call partners to confirm capacity "for each planning cycle and each event". These steps are done by hand, often "only after an event begins" (p. 4).
- **Target:** same day, under 1 working day statewide.
- **Measured:** a full rebuild from local data (all 11 build steps, 20 scenarios, 20 PDFs, app bundle) takes **69.0 seconds** on an Apple M4 laptop (measured 2026-10-27 with `scripts/time_rebuild.py`; result in `data/processed/rebuild_timing.json`). The test suite (222 automated tests, including headless-browser checks of every view) takes about 11 s. A full data refresh from the internet adds downloads plus the flood-zone queries, which are paced at 1 s per point for 311 points (at least 5.2 minutes). That refresh is not timed end to end.
- **Plus human review (team assumption):** one review session per county to confirm sites, roles and pledges. The pipeline removes the compiling and arithmetic; it does not remove the partner calls. It turns them into filling in blank capacity fields.
- **Measurement plan.** The baseline above stays a team assumption until it is measured. We propose a timed tabletop exercise with DHS and one county. The same planners produce a needs-and-resources draft for one county × hazard scenario twice: once with their current manual process (baseline) and once with this tool (tool-assisted). **Start** = hazard selected; **stop** = needs-and-resources draft approved by the county or DHS lead. We report both times in minutes (baseline vs tool-assisted), with the number of partner calls and corrections made during review.

## 7. Roles, decision points and communication pathways

All proposed – supports, does not replace, county plans.

**Roles** (`config/partners.json`, 20 partner entries). The partner types are taken from the challenge PDF (pp. 1–3): DHS, County Emergency Management (one per county), HI-EMA, DOE, the State Public Library System, DOH, DOT, OHA, American Red Cross, Salvation Army, Hawaiʻi VOAD, faith-based organizations, health care organizations, utilities, philanthropy, the business community, and other state and county agencies. Each has proposed functions (shelter operations, feeding, AFN support/medical, power for medical devices, transportation, language access, pets, donations/volunteers) with lead or support roles, all "proposed – to be confirmed with partner". Capacity and contact fields are **empty**.
- County Emergency Management leads shelter operations; this is from the PDF (p. 2: "Each County Emergency Management Agency leads mass care operations"). DHS and HI-EMA support it as State ESF-6 co-facilitators (p. 2). The other lead assignments are team proposals.
- `data/processed/match_plan.csv` has 405 need lines. Each one is need → quantity → proposed lead and support → pledged capacity (blank) → gap ("unknown – confirm with partner").

**Decision points** (`config/decision_points.json`). The triggers are official products, each quoted with its definition and URL:
- **Hurricane:** season start (June 1) → Hurricane Watch (48 h) → Hurricane Warning (36 h) → all clear.
- **Wildfire:** pre-positioning **before** the season (no-notice hazard) → Red Flag Warning → county evacuation order → all clear.
- **Tsunami:** annual pre-positioning **before** any event (no-notice hazard) → PTWC Tsunami Warning → all clear.
- **Inland flooding:** pre-season site review → Flash Flood Warning → all clear.
- **Coastal flooding:** pre-season site review → Coastal Flood Warning → all clear.

**Communication pathways** (`config/communication.json`):
- **Channels:** official alerts (WEA/EAS and county sign-ups), radio, trusted community messengers (faith-based groups, OHA, health care, community nonprofits), and printed notices at shelters, libraries and schools.
- **Languages per county:** from §5.4, the top 6 plus Hawaiian, Chuukese and Marshallese where above the suppression threshold.
- **Message library:** `data/sources/messages/` (see §9).
- **Priority outreach:** top 10 Census areas per county × hazard by AFN need (Census-area counts only), in each playbook.

## 8. Low-connectivity operation

The challenge PDF requires usability "during high-stress, low-connectivity conditions" (p. 5). We provide four tiers. **No tier needs AI during an event.**

| Tier | Conditions | What works |
|---|---|---|
| 1. Online | Normal internet | Web app (https://shelters.kahuola.org, also https://haic2026-shelters.pages.dev) |
| 2. Weak | Slow or intermittent | The app loads from its local cache. The only data is one 630 KB bundle, and every PDF is already cached |
| 3. Offline | No internet (after one earlier visit) | Installed web app (PWA). The service worker pre-caches the app, the data and all 20 PDFs, and the app shows "Offline – data as of <date>". Tested in airplane mode in Chrome. |
| 4. Paper | No power or devices | 20 printed playbooks (`playbooks/*.pdf`): US Letter, black-and-white safe, 13 pages each, with the disclaimer and "Data as of" on every page |

## 9. How AI was used

We used AI to **build** the framework and **draft** content, not to run it. Specifically:

1. **Building the pipeline – Claude Code.** An AI coding assistant wrote and tested most of the Python pipeline, the playbook generator and the web app, under team direction and review. That included checking sources (opening each cited document and comparing values), the DBEDT validation, and the browser tests in airplane mode. The 110 automated tests are in `tests/`.
2. **Data discovery – Datatrove.** The challenge names Datatrove as the primary data source (p. 4). We used Datatrove to find current FEMA NRI v1.20 Census-area layers and their field names, the HHS emPOWER county fields, and a keyless Census download route when the Census API began to require a key.
3. **Shelter announcement normalization.** The 2026 shelter activation table was compiled by an AI assistant (Claude) from county press releases and news reports via web search, extracting site name, address, event, date and pet policy, each row with its source URL. A team member reviewed the table; deterministic code then grouped, geocoded and hazard-checked the sites. The table is `data/sources/county_shelter_activations.csv`; the code is `scripts/build_shelters.py` (grouping, name normalization including ʻokina and diacritics, DOE school matching), `scripts/fetch_flood_zones.py` and `scripts/model_needs.py`.
4. **Multilingual message drafting, with mandatory human review.** AI drafted 15 short English messages (before / evacuate / shelter open × 5 hazards) and translations into 9 languages. Every draft has status "DRAFT – AI translation, needs native-speaker review", `approved = no`, and an empty reviewer field. A test blocks any approved row without a named reviewer and review date. For **Chuukese and Marshallese the AI did not produce drafts**: its output in those languages is not reliable enough to help a reviewer, so those rows are marked "NEEDS HUMAN TRANSLATION". Vietnamese drafts are assigned to Kim Quynh Do for review. The messages make no promises the counties have not made: they say "follow county announcements", and they make no statements about law enforcement at shelters.

AI is **not** used at run time: the model, the matching, the playbooks and the app are deterministic and offline.

## 10. Limitations and next steps

1. **Capacity is unknown.** No partner capacity or shelter capacity is in the repo; every pledged-capacity field is blank and every gap reads "confirm with partner". Next: collect capacities from counties and partners in `config/partners.json`.
2. **Roles need partner confirmation.** Apart from County Emergency Management leading shelter operations, roles are team proposals.
3. **Kauaʻi + Maui share one language list,** because Census microdata cannot separate them (PUMA 00100). Interpreter quantities still use each county's own limited-English count.
4. **Assumptions in `config/planning_factors.json`:**
   - tsunami and flood shelter-seeking rates (2 / 5 / 11%);
   - the wildfire low and central rates;
   - the footprint rule (top 25% of each county's Census areas by NRI score);
   - one power outlet per power-dependent person.

   All are marked "team_assumption" and should be replaced with county figures.
5. **Validation:** see §6(2). We need 2026 shelter counts from the counties.
6. **Upper bounds:** county totals assume all at-risk Census areas are hit at once. Use the largest-single-community rows for realistic planning.
7. **Data gaps:**
   - one shelter is unlocated (Pukalani);
   - one Census area has no NRI record;
   - 22 Honolulu candidate schools are in flood zone D (undetermined);
   - power-dependent counts are an allocation of county totals, not Census-area data;
   - limited-English counts in shelter (CDC SVI, "less than well") and the language mix (PUMS, "less than very well") use different definitions.
8. **Not yet modeled:** earthquake, sheltering in place (including high-rise power loss), and shelter-in-place support, all named in the challenge PDF (pp. 4, 8).
9. **Messages:** all drafts need native-speaker and county review. **Chuukese and Marshallese need human translators.** Next: request translators through the Hawaiʻi State Office of Language Access (Department of Health; it keeps an interpreter roster and publishes materials in Chuukese and Marshallese: https://health.hawaii.gov/ola/), or through community partners such as We Are Oceania, a Micronesian-led organization whose helpline offers help in Chuukese and Marshallese (Civil Beat resource guide: https://www.civilbeat.org/covid-19-resources/). Confirm availability with each organization; the helpline listing dates from the COVID-19 response.
10. **Population figures predate the Lahaina fire.** CDC SVI 2022 (ACS 2018-2022) and the 2020 Census mostly predate the **August 8, 2023 Lahaina fire**, so West Maui Census-area populations in the AFN layer may be overstated. ACS 2020-2024 shows Lahaina CDP at 10,162 ±1,143 against 12,702 in the 2020 Census, and part of that 5-year window is before the fire. Planners should use current County of Maui figures for Lahaina.
11. **TODO – ACS 2025 1-year (released October 29, 2026):** refresh county figures for Honolulu, Hawaiʻi, Maui and Kauaʻi counties (`scripts/build_demographics.py`). Kalawao is too small for 1-year data and keeps the 5-year figures.
12. **County lines and high-rise homes.** The Partners In Care 2026 Point-in-Time report PDF for Oʻahu could not be found; the Oʻahu total (4,539) comes from the City and County of Honolulu release of 2026-05-21, which gives the total only. The neighbor-island Continuum of Care is Bridging the Gap (BTG). Homelessness and visitor counts are county lines, never added to Census-area totals. "Homes in buildings with 10+ units" (CDC SVI E_MUNIT) counts housing units, not people.
13. **More CMIST detail uses a newer ACS release.** Hearing, vision and cognitive difficulty and age 65+ living alone come from ACS 2020-2024; the other CMIST counts come from CDC SVI 2022 (ACS 2018-2022). Both use 2020 Census tracts.

## 11. Team

- **Tiffanie Nguyen** – Team Captain, UI
- **Long Nguyen** – data and AI pipeline
- **Kim Quynh Do** – UI; Vietnamese review

Official repository: https://github.com/HAIC-2026/Kahu-Ola · Mirror: https://github.com/nguyenhuulong2222/haic2026-esf6-shelters

License: MIT (`LICENSE`).
