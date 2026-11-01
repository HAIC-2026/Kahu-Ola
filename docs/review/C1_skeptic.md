# C1 – Skeptical review of the Kahu-Ola plan (PLAN.md, README.md)

Reviewer stance: DHS planning lead, did not write the plan. Based only on the text of PLAN.md and README.md. Anything that needs checking outside the text is marked [VERIFY].

## 1. The strongest opposite case

**It solves the part of the problem that was already solvable, and leaves the hard part blank.** The challenge PDF, as quoted in §1, names three pains: data fragmented across programs and partners, partner resources and roles "not consistently mapped", and needs estimated ad hoc. The plan answers the first with *public* Census/SVI/NRI data only, not with DHS program data. It answers the second with 20 partner entries whose "capacity and contact fields are empty" and 405 need lines whose gap reads "unknown – confirm with partner" (§7, §10.1). The MATCH step, the one that would "coordinate help", contains no matched capacity. What is left is a well-built hazard and demographics atlas. That is useful, but it is not the coordination tool the challenge describes.

**The three metrics are met by construction, not by evidence.**
- Metric 1 (100% of Census areas) holds because CDC SVI covers every tract. Coverage of a national dataset says nothing about whether the CMIST proxies (65+, disability, no vehicle, limited English, group quarters) find the people who actually need help in a shelter.
- Metric 2 is circular. The plan admits it: the high wildfire rate was *set* from Lahaina (1,418 / 12,702 = 0.112), and then Lahaina falls "inside the band". No out-of-sample event has been tested. The 2026 events it would need (Lala, Lowell, Nolo) have site lists but no occupancy counts (§6(2)).
- Metric 3 compares a 44-second computer rebuild with an *assumed* human baseline of "at least 2 working days per county" that no one measured. The rebuild does none of the partner calls that make up much of the manual work, as §6(3) concedes ("it does not remove the partner calls").

**Precision theatre.** The headlines carry five- and six-digit precision: 306,869 people pushed past 15 minutes, 43,518 cots, 70,875 people in the sea-level-rise test. Those figures rest on:
- shelter-seeking rates that are team assumptions (tsunami and flood 2/5/11%), borrowed from South Carolina (hurricane), or fitted to one catastrophic event (wildfire);
- 250 people per site, a team assumption;
- normal-traffic drive times from one point per tract;
- a shelter universe made of whichever 30 sites happened to open in 2026 events.

Honolulu has 7 such sites for about 1 million people. "322 areas, 169 beyond 15 minutes" therefore describes the 2026 event sample more than real access. Planners will quote the six-digit numbers without the caveats.

**"Hazard-specific" is weaker than it sounds.** By the plan's own arithmetic the hurricane "at-risk" population is the whole county: Honolulu likely demand 30,303 ÷ 3% ≈ 1.01 million, Kauaʻi 2,205 ÷ 3% ≈ 73,500. The wildfire footprint is a relative rule (top 25% of each county's tracts by NRI score), so every county gets about a quarter of its tracts flagged whatever its absolute risk. The State Fire Risk layer agrees with that footprint on only 13–29% of areas (§5.12). The plan's answer is that "counties should say which one they plan with". That means the wildfire map is not yet a planning answer.

**Built for judges, not for a high-stress shift.** The plan has 25 stress tests with 861 results, 427 automated tests, playbooks of 27–30 pages, and county annexes of 26–34 pages. The challenge asks for use "during high-stress, low-connectivity conditions". Nothing in the text shows a county or DHS planner using any of it under time pressure [VERIFY].

**Right for the wrong reasons.** The privacy model, the offline delivery and the source discipline are strong. That makes the plan *safe to adopt*. It does not make it *effective*: the decision-relevant inputs (capacity, occupancy, county shelter designations, DHS program data) are all outside it.

## 2. Framing and assumptions never tested

- **CMIST proxies = AFN need.** SVI variables are mapped to CMIST categories. The plan never shows that tracts high on these proxies are where AFN shelter demand actually came from in any Hawaiʻi event.
- **One shelter-seeking rate for everyone.** The same rate is applied to every resident. Whether AFN residents seek public shelter at a higher or lower rate is never tested. The "share needing support in shelter" is simply the tract disability share.
- **Mainland and single-event rates transfer to Hawaiʻi.** Hurricane rates come from "South Carolina EMD Annex G", which has no date or version in the text. The wildfire high rate comes from Lahaina 2023, an event in which a town was destroyed. Whether either fits an island setting, where people cannot evacuate off-island by road, is not examined [VERIFY].
- **2026 activation sites are a fair proxy for the shelter network.** Every drive-time, stress-test and "pushes N people" result depends on it. County designated-shelter lists were never compared [VERIFY whether counties hold such lists].
- **Drive time from the tract centre, normal traffic.** People without a car get walking times for tsunami only (test 23a). The vehicle-trip input of 20 people per trip is a team assumption with no source.
- **Kahekili Hwy as a working detour.** The Honoapiʻilani closure result ("no area cut off") depends on Kahekili Hwy being open "in the road network". Whether it is usable in a real event is not tested [VERIFY].
- **Planners will visit the PWA before the event and run a Python pipeline after the competition.** No owner, refresh schedule or hosting plan is stated. Some refresh steps need a paid Esri token (README step 1).
- **The baseline of 2 working days per county.** It is proposed as the comparison, but it remains a team assumption. The proposed tabletop exercise has not happened.
- **Census CDP and tract populations are current enough.** For West Maui the plan concedes they are not (§10.10). Other areas that changed after 2020 are not examined.

## 3. Under-weighted characters

**People and organisations**
- **County emergency management agencies.** The plan says they lead mass care (challenge PDF p. 2), yet no county plan, designated shelter list or county review is cited as an input. Their role in the text is mostly "confirm later".
- **Partners (Red Cross, Salvation Army, VOAD, faith groups).** They appear as roles with blank capacity. The only Red Cross capacity data is the 2009 PDC layer, held through a third-party copy.
- **AFN residents and their trusted messengers.** No resident, community organisation or messenger is reported as consulted. We Are Oceania appears through a COVID-era Civil Beat listing.
- **Chuukese and Marshallese communities** get no translated messages at all (0 of 15). Their counts are also internally strained. The Honolulu limited-English Chuukese count (4,948, PUMS 2019-2023) is about 96% of the statewide count of *all* Chuukese residents (5,153 ±1,589, ACS 2020-2024). In Hawaiʻi County the ACS figure is 114 ±95 against 715 in the 2020 Census [VERIFY].
- **Visitors and unsheltered residents.** They are "county lines", never added to tract demand. For example, 35,640 visitors are on Hawaiʻi Island on an average day, and how many are in tsunami zones "needs county data".
- **Care-facility residents.** There are 107 facilities (dialysis, nursing homes, hospitals), but the plan screens only their location. Their evacuation and sheltering needs are not modelled.
- **Kalawao and Niʻihau.** They are mentioned only as statistical edge cases.

**Object characters**
- **The 30-site CSV.** Claude compiled it from press releases and news (§9.3). It is the foundation of every access and stress-test number. "AI is not used at run time" is true, but AI produced the base list that run time depends on.
- **The AI as builder *and* checker.** Claude "wrote and tested most of the Python pipeline… including checking sources (opening each cited document and comparing values)" (§9.1). The 427 tests come from the same process. Nothing describes a check by anyone independent of that process.
- **`config/planning_factors.json`.** Every demand and resource number passes through it, and its key entries are labelled "team_assumption".
- **CDC SVI 2022 (ACS 2018-2022).** It predates the Lahaina fire, and it drives the AFN layer.
- **NRI v1.20 and the top-25% rule.** These define four of the five footprints.
- **Esri ArcGIS.** It is a paid dependency with a credit budget, and its licence terms keep the raw results out of the repo. Future refreshes depend on someone holding a token.
- **The service worker cache.** The offline strength is also a staleness risk. A device shows whatever data it cached ("Offline – data as of <date>").
- **DHS's own de-identified program data.** It is the central character in the challenge's problem statement, and it is absent from the plan.

## 4. Where the language is generic rather than Hawaiʻi-specific

- **Roles** list partner *types* taken from the challenge PDF ("faith-based organizations, utilities, philanthropy, the business community"). No named Hawaiʻi organisation is assigned per county, apart from OHA and the We Are Oceania suggestion.
- **Decision points** are national NWS/PTWC products (Watch 48 h, Warning 36 h, Red Flag Warning, Flash Flood Warning) plus "pre-season site review". No county EOC activation level, county evacuation-order practice or inter-county trigger appears [VERIFY against county plans].
- **Resource factors** come from Florida DEM 2010 and South Carolina EMD. No Hawaiʻi sheltering standard is cited.
- **The 15 messages** are written once per hazard ("follow county announcements") and translated. They are not tailored per county or per community.
- **Inter-island resupply** for Molokaʻi and Lānaʻi, which is the clearest island-specific constraint, appears only as a "question for counties".
- **Spelling.** The care-facility names drop the ʻokina and kahakō ("Hawaii Kai", "Waianae", "Nanakuli", "Molokai dialysis"). This conflicts with the plan's own place-name rule.
- **Where it is specific.** The road-closure set (Honoapiʻilani Pali/Olowalu, Hāna Hwy at Keʻanae, Kūhiō Hwy at Hanalei bridge, Hwy 11 Kaʻū), the Lahaina population note and the 2013 Maui safe-zone caveat are genuinely local. That specificity is in the *stress tests*. The *operational* sections (roles, triggers, messages) are the generic ones.

## Changes (most important first)

1. **Fill the empty half before claiming coordination.** Get 2026 per-site occupancy for Lala, Lowell and Nolo from the counties, and run the proposed timed tabletop with DHS and one county. Until then, relabel Metric 2 as "calibrated, not validated", drop the "inside the band" framing, and state Metric 3 as "not yet measured".
2. **Replace the 2026-activation shelter universe with county-designated shelter lists** for all access and stress-test results, or show those results only as relative rankings. Take six-digit "people affected" headlines out of summaries until capacity and real site lists exist.
3. **Make the footprints hazard-specific and county-chosen.** Hurricane is currently the whole county, and wildfire disagrees with the State layer on 71–87% of areas. Each county should pick and sign off a footprint, and the plan should show which one it is using.
4. **Get an independent check of the AI-produced foundations.** That means the 30-site CSV, the source-value checks, and the translations, including Hawaiian and Pidgin. A person outside the team (county staff or OLA) should review a sample, and the result should be recorded.
5. **Cut the in-event product to one page per county × hazard,** with the top AFN areas, usable sites, triggers and message languages. Move the 27–30 page playbooks and annexes to reference. Name an owner and a refresh cycle, including Esri cost and hosting, for after the competition.
