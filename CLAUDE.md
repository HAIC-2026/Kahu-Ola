# CLAUDE.md – Kahu-Ola (HAIC 2026)

Guide for Claude Code and for the team. Read this before changing anything.

## Project

Kahu-Ola is an offline-first planning framework for Hawaiʻi DHS ESF-6 (mass care). It maps
where people with access and functional needs (CMIST) live relative to hurricane, wildfire,
tsunami, inland flood and coastal flood hazards; estimates shelter needs for each
county × hazard; and matches them to proposed partner roles, decision points and multilingual
messages (MAP → MODEL → MATCH). Public, aggregate data only. No login, no tracking, no
location access.

- Plan and findings: [PLAN.md](PLAN.md) (the three DHS metrics are in section 6).
- Pipeline and data sources: [README.md](README.md).
- Web app: `app/` (static HTML/CSS/JS, service worker for offline use).
- Printable playbooks: `playbooks/<county>_<hazard>.pdf` (20 PDFs).

## Run the app

```sh
python scripts/build_app_data.py --copy-only   # once: copies playbooks/*.pdf into app/playbooks/ (gitignored)
cd app && python -m http.server 8000           # then open http://localhost:8000
```

## Run the tests

```sh
python -m unittest discover tests
```

Run the full suite before calling any code change done. Every pull request to `main` also runs
the fast tests on GitHub Actions (`.github/workflows/tests.yml`: no `data/raw/`, no browser;
tests that need either skip) and checks that the `sw.js` `VERSION` is current. Tests that need cached raw data
(`data/raw/`, gitignored) skip or fail on a fresh clone; see "Running on Windows" and ask
Long before treating a data test failure as your own.

## Team and ownership

| Area | Owner | Notes |
|---|---|---|
| UI (`app/`) | Tiffanie Nguyen, Kim Quynh Do | Do not change `scripts/` or `data/` without asking Long first. |
| Data/AI (`scripts/`, `data/`, `config/`) | Long Nguyen | Includes `app/data/bundle.json` and the generated parts of `app/sw.js`. |
| Vietnamese review (`data/sources/messages/vietnamese.csv`) | Kim Quynh Do | |

## Design

- Figma: not yet – will be added once the design is settled (UI stage 5).

## Rules

1. **Scope.** UI work changes only `app/` (plus this file and files the team lead allows).
   Never edit `scripts/`, `data/`, `config/` or `app/data/bundle.json` – they belong to Long.
2. **CSP is `'self'` only.** No CDN, no external fonts, no inline `style=""`, no inline `<script>`.
3. **Design tokens.** Colours, spacing and fonts come only from the variables in `:root` of
   `app/styles.css`. Keep WCAG AA contrast and write the contrast ratio in a comment, like the
   existing variables.
4. **Visible text** never shows `null`, `undefined`, `NaN`, file names (`.json`, `.csv`, `.py`)
   or snake_case identifiers.
5. **Disclaimer** "Planning aid. Supports, does not replace, county emergency plans. Not an
   official shelter list." is always clearly visible, including in print.
6. **Offline and private.** The app works offline; it calls no outside service, has no
   tracking and never asks for location. Hawaiʻi place names keep their ʻokina and kahakō.
7. **After any change in `app/`** (even only `styles.css` or `app.js`, or adding/renaming a
   file), run `python3 scripts/build_app_data.py --copy-only` and commit the updated
   `app/sw.js` in the same pull request. This refreshes the service worker `VERSION` and
   precache list from the committed bundle; it needs no `data/raw/` and never regenerates
   data. Without a new `VERSION`, browsers keep the old version. Never edit `sw.js` by hand.
   - **CI checks `VERSION` on every pull request to `main`:** the Tests check fails when
     `app/sw.js` is stale and shows the fix.
   - **The full build** (`python3 scripts/build_app_data.py` without `--copy-only`) is
     Long's. A missing or empty required input in `data/raw/` stops it with an error; it
     never silently drops a layer. Do not commit `app/data/bundle.json` or
     `app/data/version.json`.
8. **Helper tools stay outside the repo.** Playwright, screenshots and similar go in a temp
   folder outside the repo. Do not commit them and do not add a `package.json`.
9. **Run the tests** (`python -m unittest discover tests`) before reporting a code change done.

## Running on Windows

Set these once (PowerShell), then restart the terminal / app:

```powershell
setx PYTHONUTF8 1
setx CHROME_BIN "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

- `PYTHONUTF8=1`: without it Python uses cp1252 and the tests crash on ʻokina and other
  non-ASCII text (`UnicodeEncodeError`/`UnicodeDecodeError`, empty pages from Chrome).
- `CHROME_BIN`: `find_browser()` in `scripts/build_playbooks.py` does not look in the
  Windows install folders; the browser tests and PDF builds need this variable.
- Use `python` or `py`, not `python3` (on Windows that is the Microsoft Store stub); e.g.
  `py scripts/build_app_data.py --copy-only`.
- Line endings: `.gitattributes` keeps LF in the repo (PDFs and images are binary), and the
  `sw.js` `VERSION` hash ignores CRLF, so Windows gives the same `VERSION` as macOS.

Known Windows-only test failures (environment, not app bugs):

- Browser tests that start six headless Chrome processes in parallel get empty pages on
  Windows (`test_map_detail`, `test_lahaina_note`, `test_rendered_views`). A single Chrome
  renders the same views correctly.
- `test_languages_pums ... test_library_prunes_only_header_only_files` fails with
  `PermissionError: [WinError 32]`: Windows cannot delete a file that is still open.
- PDF text tests (`test_messages_neutral`, `test_plain_language`, `test_rendered_views`) fail
  when `pdftotext` is the xpdf build shipped with Git Bash: it writes Latin-1, not UTF-8.
  Poppler's `pdftotext` writes UTF-8.
