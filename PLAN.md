# Hawaiʻi ESF-6 AFN Planning Framework – AI-Developed Plan

**HAIC 2026 · DHS challenge "Enhancing ESF-6 Planning Through AI-Supported Insights"**
**Team Kahu Ola** · Data as of 2026-10-27 · Repository: this repo (all numbers below are read from files in it)

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
| **MAP** | CMIST counts per census tract (436 tracts, 4 counties) joined to hazard exposure (FEMA NRI v1.20, State tsunami evacuation and extreme zones); HHS emPOWER power-dependent counts allocated to tracts | `scripts/fetch_data.py`, `scripts/build_map.py` | `data/processed/afn_tracts.geojson`, `coverage.json` |
| **MAP** (sites) | Sites the counties actually opened in 2026 events, located from public sources; site-level FEMA flood zone | `scripts/build_shelters.py`, `scripts/geocode_shelters.py`, `scripts/fetch_flood_zones.py` | `data/processed/shelters_2026.geojson`, `data/sources/site_flood_zones.csv` |
| **MODEL** | For each county × hazard (4 × 5 = 20): footprint, at-risk population, shelter demand (low / central / high), CMIST counts, resources (cots, space, water, meals, toilets, staff, power outlets, pets), usable sites | `scripts/model_needs.py`, `config/planning_factors.json` | `data/processed/needs_by_scenario.json`, `needs_by_tract.csv`, `backtest.csv` |
| **MATCH** | Each need → proposed lead and support partner types → pledged capacity (blank) → gap; decision points; communication pathways; top 10 outreach tracts | `scripts/match.py`, `config/partners.json`, `config/decision_points.json`, `config/communication.json` | `data/processed/match_plan.json`, `match_plan.csv` |
| **Deliver** | 20 printable playbooks and an offline web app | `scripts/build_playbooks.py`, `scripts/build_app_data.py` | `playbooks/`, `app/` |

The pipeline is deterministic Python (standard library only). AI is not needed to run it, and it does not call AI.

## 3. Data sources and dates

All sources are public. Fetch dates are recorded in the build metadata (`data/processed/afn_tracts.geojson` → `metadata.sources`) and in each source table.

| Source | Use | Vintage / fetched |
|---|---|---|
| CDC/ATSDR Social Vulnerability Index 2022, census tracts | CMIST proxies (limited English, disability, 65+, under 18, no vehicle, group quarters) | SVI 2022; fetched 2026-10-27 |
| FEMA National Risk Index v1.20, census tracts (hurricane, wildfire, tsunami, inland and coastal flooding) | Hazard footprint (NRI risk score) | v1.20; fetched 2026-10-27 |
| Hawaiʻi Statewide GIS: tsunami evacuation zones and extreme tsunami evacuation zones | Tsunami footprint; site exclusion | fetched 2026-10-27 |
| Hawaiʻi Statewide GIS "State DFIRM" (FEMA flood hazard areas, downloaded from FEMA 6/15/26) | Site-level flood zone for 311 site points | queried 2026-10-27 (`data/sources/site_flood_zones.csv`) |
| HHS emPOWER, county level (`Power_Dependent_Devices_DME`) | Power-dependent residents, allocated to tracts by 65+ share (estimate) | fetched 2026-10-27 |
| Hawaiʻi DOE public schools (Statewide GIS) | Candidate sites (292 schools) | fetched 2026-10-27 |
| County announcements of shelters opened in 2026 events (official county releases; earlier news reports kept in notes) | Commonly used shelters | `data/sources/county_shelter_activations.csv`, one official source URL per row |
| U.S. Census Geocoder; Hawaiʻi and Maui County address points | Locating shelter addresses | `data/sources/geocodes.csv`, source URL per row |
| ACS PUMS 2019-2023 5-year, Hawaiʻi person file | Detailed languages (limited English) | `data/sources/languages_by_county.csv` |
| DBEDT State of Hawaii Data Book 2024, Table 1.44 | Validation of the language counts | cited in `tests/test_languages_pums.py` |
| ACS table C16001 (2020-2024 5-year) | Secondary language source | `data/sources/languages_by_county_c16001.csv` |
| NWS / NHC / CPHC / PTWC product definitions | Decision-point triggers | URLs in `config/decision_points.json` |

## 4. Privacy model

- **Aggregate data only.** The model works on census-tract and county totals. No individual records, no client data, no registries (challenge PDF p. 5: "no personally identifiable information").
- The only names and addresses in the outputs are those of **public facilities** (shelters, schools). Tests check that the app data bundle has no person-level fields (`tests/test_deliverables.py`).
- The language table comes from Census microdata (PUMS). The microdata stays in `data/raw/` (gitignored) and is never committed or printed. Outputs are aggregates, and any cell under 100 weighted people or under 10 sample persons is suppressed (149 of 194 area × language cells).
- The web app has no accounts, no analytics and no location access, and it makes no calls to outside services. It only reads its own data file.

## 5. Key findings

### 5.1 Coverage
- **CMIST data for 436 of 436 census tracts (100%)** in all four counties. FEMA NRI joined for **435 of 436** (one Honolulu tract has no NRI record). Source: `data/processed/coverage.json`.

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

**County totals are upper bounds:** they assume every at-risk tract is hit at once. The "largest single community" column is the highest-demand census tract, which is a realistic one-community scenario. Source: `data/processed/needs_by_scenario.json`, `needs_by_tract.csv`.

| County | Hazard | Demand low / **central** / high (people) | Largest single community: tract, central demand |
|---|---|---|---|
| Kauaʻi | Hurricane | 1,470 / **2,205** / 3,676 | 15007040401: 225 |
| Kauaʻi | Wildfire | 433 / **1,082** / 2,423 | 15007040204: 302 |
| Kauaʻi | Tsunami | 123 / **308** / 678 | 15007040302: 68 |
| Kauaʻi | Inland flooding | 428 / **1,070** / 2,354 | 15007040500: 365 |
| Kauaʻi | Coastal flooding | 384 / **959** / 2,110 | 15007040500: 365 |
| Honolulu | Hurricane | 20,202 / **30,303** / 50,505 | 15003011500: 347 |
| Honolulu | Wildfire | 6,285 / **15,713** / 35,197 | 15003011500: 579 |
| Honolulu | Tsunami | 1,644 / **4,110** / 9,042 | 15003009610: 302 |
| Honolulu | Inland flooding | 7,389 / **18,473** / 40,641 | 15003011500: 579 |
| Honolulu | Coastal flooding | 4,868 / **12,170** / 26,775 | 15003010202: 349 |
| Maui | Hurricane | 3,296 / **4,944** / 8,241 | 15009030800: 242 |
| Maui | Wildfire | 977 / **2,442** / 5,469 | 15009031001: 349 |
| Maui | Tsunami | 365 / **912** / 2,006 | 15009030713: 128 |
| Maui | Inland flooding | 1,053 / **2,633** / 5,792 | 15009030800: 403 |
| Maui | Coastal flooding | 734 / **1,834** / 4,035 | 15009031900: 266 |
| Hawaiʻi | Hurricane | 4,043 / **6,065** / 10,108 | 15001021014: 244 |
| Hawaiʻi | Wildfire | 1,151 / **2,878** / 6,446 | 15001021014: 407 |
| Hawaiʻi | Tsunami | 249 / **623** / 1,371 | 15001021608: 99 |
| Hawaiʻi | Inland flooding | 1,310 / **3,276** / 7,207 | 15001021014: 407 |
| Hawaiʻi | Coastal flooding | 1,079 / **2,698** / 5,937 | 15001021300: 369 |

Shelter-seeking rates (`config/planning_factors.json`): hurricane 2 / 3 / 5% (South Carolina EMD Annex G). Wildfire high 11.2%, the observed Lahaina 2023 rate (central and low are team assumptions). Tsunami and flood 2 / 5 / 11% (team assumption). Each scenario also has CMIST counts, resources (cots, floor space, water, meals, toilets, staff, power outlets, pet households) and an extreme-zone number for tsunami. These are in the playbooks.

## 6. The three DHS metrics

The challenge PDF (p. 7) sets three measurable goals.

**(1) Hazard-specific AFN maps covering every county – target 100% of census tracts.**
Result: CMIST coverage **100% (436/436 tracts)**, NRI hazard join **99.8% (435/436)**, for all 5 hazards and 4 counties: 20 maps, one in each playbook (`playbooks/*.pdf`) and in the app.

**(2) Needs estimates validated "within an agreed margin against past events".**
Result: Lahaina wildfire, 2023-08-11. Observed 1,418 people in shelters (Maui Now). Model 254 / 635 / **1,423** (low / central / high). The observed count is **inside the band**, and the high estimate is 0.3% from it (`data/processed/backtest.csv`).
**This is a calibration event, not validation:** the high wildfire rate was set from this same event (1,418 / 12,702 = 0.112), so agreement is expected. The observed count also includes visitors and evacuees from other fires (`data/sources/past_events.csv`).
**For true validation** we need an event the model has not seen: the number of people sheltered per site and day in the **2026 events (Hurricane Lala, Hurricane Lowell, Tropical Storm Nolo)**, from the counties. The repo has which sites opened, but **not** how many people used them.

**(3) Time to produce a coordinated needs-and-resources plan.**
The challenge PDF gives no baseline number ("Teams may propose their own baseline and target time", p. 7).
- **Baseline (team assumption, to be confirmed with DHS):** at least **2 working days per county per event**, about 8 working days statewide. Reasoning: the manual steps DHS describes (p. 3–4): pull program and provider reports, cross-reference lists with hazard zones, recompile shelter lists, and call partners to confirm capacity "for each planning cycle and each event". These steps are done by hand, often "only after an event begins" (p. 4).
- **Target:** same day, under 1 working day statewide.
- **Measured:** a full rebuild from local data (all 9 build steps, 20 scenarios, 20 PDFs, app bundle) takes **62.6 seconds** on an Apple M4 laptop (measured 2026-10-27). The test suite takes 0.15 s. A full data refresh from the internet adds downloads plus the flood-zone queries, which are paced at 1 s per point for 311 points (at least 5.2 minutes). That refresh is not timed end to end.
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
- **Priority outreach:** top 10 tracts per county × hazard by AFN need (tract counts only), in each playbook.

## 8. Low-connectivity operation

The challenge PDF requires usability "during high-stress, low-connectivity conditions" (p. 5). We provide four tiers. **No tier needs AI during an event.**

| Tier | Conditions | What works |
|---|---|---|
| 1. Online | Normal internet | Web app (https://shelters.kahuola.org, not yet deployed) |
| 2. Weak | Slow or intermittent | The app loads from its local cache. The only data is one 365 KB bundle, and every PDF is already cached |
| 3. Offline | No internet (after one earlier visit) | Installed web app (PWA). The service worker pre-caches the app, the data and all 20 PDFs, and the app shows "Offline – data as of <date>". Tested in airplane mode in Chrome. |
| 4. Paper | No power or devices | 20 printed playbooks (`playbooks/*.pdf`): US Letter, black-and-white safe, 9 pages each, with the disclaimer and "Data as of" on every page |

## 9. How AI was used

We used AI to **build** the framework and **draft** content, not to run it. Specifically:

1. **Building the pipeline – Claude Code.** An AI coding assistant wrote and tested most of the Python pipeline, the playbook generator and the web app, under team direction and review. That included checking sources (opening each cited document and comparing values), the DBEDT validation, and the browser tests in airplane mode. The 110 automated tests are in `tests/`.
2. **Data discovery – Datatrove.** The challenge names Datatrove as the primary data source (p. 4). We used Datatrove to find current FEMA NRI v1.20 tract layers and their field names, the HHS emPOWER county fields, and a keyless Census download route when the Census API began to require a key.
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
   - the footprint rule (top 25% of each county's tracts by NRI score);
   - one power outlet per power-dependent person.

   All are marked "team_assumption" and should be replaced with county figures.
5. **Validation:** see §6(2). We need 2026 shelter counts from the counties.
6. **Upper bounds:** county totals assume all at-risk tracts are hit at once. Use the largest-single-community rows for realistic planning.
7. **Data gaps:**
   - one shelter is unlocated (Pukalani);
   - one tract has no NRI record;
   - 22 Honolulu candidate schools are in flood zone D (undetermined);
   - power-dependent counts are an allocation of county totals, not tract data;
   - limited-English counts in shelter (CDC SVI, "less than well") and the language mix (PUMS, "less than very well") use different definitions.
8. **Not yet modeled:** earthquake, sheltering in place (including high-rise power loss), and shelter-in-place support, all named in the challenge PDF (pp. 4, 8).
9. **Messages:** all drafts need native-speaker and county review. **Chuukese and Marshallese need human translators.** Next: request translators through the Hawaiʻi State Office of Language Access (Department of Health; it keeps an interpreter roster and publishes materials in Chuukese and Marshallese: https://health.hawaii.gov/ola/), or through community partners such as We Are Oceania, a Micronesian-led organization whose helpline offers help in Chuukese and Marshallese (Civil Beat resource guide: https://www.civilbeat.org/covid-19-resources/). Confirm availability with each organization; the helpline listing dates from the COVID-19 response.

## 11. Team

- **Tiffanie** – team captain, UI
- **Long Nguyen** – data and AI pipeline
- **Kim Quynh Do** – UI; Vietnamese review

License: MIT (`LICENSE`).
