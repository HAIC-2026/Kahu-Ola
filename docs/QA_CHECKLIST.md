# QA checklist – Kahu-Ola

What "done" means for the app, what to check before every deploy, and what to check on demo day.
Rules come from [CLAUDE.md](../CLAUDE.md); the metrics from [PLAN.md §6](../PLAN.md#6-the-three-dhs-metrics).
Each item names the problem it prevents when we have already hit it once.

Severity used in QA reports: **Blocks demo** (a judge would see it, or a demo step fails) ·
**High** (wrong number, broken feature, accessibility barrier) · **Medium** (works, but confusing or
fragile) · **Low** (polish).

## 1. Acceptance criteria for the app

### Function
- [ ] All 20 views (4 counties × 5 hazards) open from the County and Hazard menus **and** from a deep
      link `?county=…&hazard=…#plan`; the browser Back button returns to the previous view.
- [ ] Each view shows the KPI cards, the map with its legend, the area list, the tables and the
      Results section. The tsunami zone outline appears **only** for tsunami.
- [ ] Every Census area opens its detail panel by click, by Enter from the area list and by deep
      link `&area=…`. Esc and "Back to county" close it and return focus to where it was (or to the map).
- [ ] "Printable playbook (PDF)" opens the PDF for the **same** county and hazard.
- [ ] In the area panel, the "Messages:" line shows real language names, and each one is a link that
      opens Messages filtered to that language with its group open. (We once shipped `, ,http://…`
      here.)
- [ ] Messages shows all 180 messages, the filters only narrow the list, and each Copy button names
      its language, hazard and phase.

### Data
- [ ] No visible `null`, `undefined`, `NaN`, negative counts, file names (`.json`, `.csv`, `.py`),
      snake_case words or raw URLs, in light or dark mode.
- [ ] Numbers in the app match the PDF playbook for the same scenario: people in the risk area,
      shelter demand low / likely / high, CMIST cards and the "Data as of" date.
- [ ] The "Data as of" date is the same in the header, the footer, the offline banner and every
      PDF page.
- [ ] Wording that the plan depends on stays true: county totals are an **upper bound**; the Lahaina
      backtest is **calibration, not validation**; roles are **proposed**; messages are **drafts**
      until a native speaker and the county have reviewed them.
- [ ] Hawaiʻi place names keep their ʻokina and kahakō.

### Offline (PLAN.md §8)
- [ ] After one online visit and a reload, the app, the data and all 20 PDFs work with the network
      **really** off. Test by stopping the server or using airplane mode: browser-only "offline"
      emulation can let service-worker requests through.
- [ ] Offline shows "Offline – data as of <date>"; the banner hides again when the network returns.
- [ ] No failed requests and no JavaScript errors while offline.
- [ ] A browser that has an older version gets the new one after reloading, without clearing the
      cache. (This needs a new `VERSION` in `app/sw.js`; see the release checklist.)

### Accessibility (WCAG 2.2 AA)
- [ ] axe-core finds no serious or critical issues on Plan, the area panel and Messages, in light
      and dark mode, at 375 px and 1280 px.
- [ ] The whole demo flow works with the keyboard alone, with a visible focus outline.
- [ ] At 320 px wide and at 200% zoom, no content is lost and the page does not scroll sideways.
      (The area panel once scrolled 30 px sideways at 320 px.)
- [ ] Dates, number ranges ("977 – 5,469") and "Census area 314.05" never break across two lines.
      (Dates once broke as `2026-10-` / `28` on phones.)
- [ ] Every translated message has the right `lang` attribute. Status (draft, needs a translator,
      reviewed) is written in words, not shown only by colour.
- [ ] Text contrast is at least 4.5:1 (3:1 for large text and UI parts), and the ratio is written
      next to each colour token in `app/styles.css`.
- [ ] Buttons and links have names that make sense out of context. No motion runs on its own.

### Display
- [ ] Works in current Chrome, Edge, Firefox and Safari (iPhone), at 320, 375, 414, 768, 1280 and
      1920 px, and in landscape on a phone.
- [ ] Light and dark mode both follow the device setting; the map and legend stay on light paper.
- [ ] Print: white background, black text, the disclaimer visible, the kapa band hidden.

### Security and privacy
- [ ] CSP is `'self'` only (in `app/_headers` and the `<meta>` tag): no CDN, no external fonts, no
      inline `style=""` or `<script>`. The browser console shows no CSP errors.
- [ ] No outside requests, no tracking, no location requests, no login. Only aggregate, public
      Census-area counts and public facility names.
- [ ] The disclaimer "Planning aid. Supports, does not replace, county emergency plans. Not an
      official shelter list." is visible on screen and in print.
- [ ] No keys, tokens, passwords or personal data in the repo.

## 2. Release checklist (before every deploy)

1. [ ] **Every change to `app/` goes through a pull request.** Commits pushed straight to `main`
       do not run CI.
2. [ ] The pull request includes the refreshed `app/sw.js`: run
       `python scripts/build_app_data.py --copy-only` after any `app/` change and commit `sw.js`.
       Only the `VERSION` line should change. (PR #3 shipped a stale `VERSION`, and nobody saw the
       new colours.)
3. [ ] CI (`Tests` / `fast-tests`) is green on the pull request. It also checks `VERSION`.
4. [ ] `python -m unittest discover tests` passes locally. On Windows, set `PYTHONUTF8=1` and
       `CHROME_BIN`, and see "Running on Windows" in CLAUDE.md for the known environment failures. A
       failure in the parallel Chrome tests is only "environment" if the same test passes when run
       with one browser at a time.
5. [ ] Quick check on `localhost` at 320 px and 1280 px, light and dark: one view, one area panel,
       Messages, one PDF.
6. [ ] `app/data/bundle.json` and `app/data/version.json` are only committed by Long (full build
       on a machine with `data/raw/`).
7. [ ] After merging, send Long the `main` commit and the `VERSION` from `app/sw.js`
       ([DEPLOY.md](DEPLOY.md), "Who deploys").
8. [ ] **After the deploy, check that `VERSION` matches `main` on BOTH addresses:**
       ```sh
       curl -s https://shelters.kahuola.org/sw.js | grep "const VERSION"
       curl -s https://haic2026-shelters.pages.dev/sw.js | grep "const VERSION"
       ```
9. [ ] On the live site: reload twice, then check that the change is visible, the console is clean,
       and offline mode still works.

## 3. Demo-day checklist

**The day before**
- [ ] The latest `main` is deployed, and `VERSION` matches on both addresses (release step 8).
- [ ] Rehearse the 3-minute script with a timer. It covers the three DHS metrics: 436/436 Census
      areas, the Lahaina backtest (calibration), and the 44-second rebuild.

**Morning of the demo, while online**
- [ ] Chrome in a normal window (not Incognito, which drops the offline cache when it closes).
- [ ] Open https://shelters.kahuola.org and reload **twice**: the first reload installs the new
      service worker, the second shows it.
- [ ] Open the Maui wildfire PDF once, then close the tab.
- [ ] Rehearse airplane mode once: reload and see "Offline – data as of …". Turn airplane mode off
      again.
- [ ] System theme set to light (easier to read on a projector). Browser zoom 125%. Notifications
      off. Laptop charged and plugged in. HDMI adapter tested.
- [ ] Tab ready at `?county=Maui&hazard=wildfire#plan`, scrolled to the top.

**Just before going on**
- [ ] Airplane mode is **off**, and the offline banner is not showing.

**Backup**
- [ ] A second laptop prepared the same way.
- [ ] A USB stick with the 20 PDFs.
- [ ] A printed Maui wildfire playbook.
- [ ] If the venue has no Wi-Fi, start in airplane mode and say "we're already offline".
