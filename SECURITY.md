# Security

## Reporting a vulnerability

Please open a private GitHub security advisory on this repository, or contact the maintainers through GitHub. Do not include personal data in reports.

## Design

| Area | Control | Where |
|---|---|---|
| Hosting | Static files only (Cloudflare Pages). No server code, database or API. | `app/`, `docs/DEPLOY.md` |
| Identity | No accounts, no login, no cookies, no analytics, no location access. | `app/app.js`, `app/_headers` (Permissions-Policy) |
| Data | Aggregate census-tract and county data, plus public facility names and addresses. No PII and no client data. Census microdata stays in gitignored `data/raw/`; outputs are suppressed below 100 weighted people or 10 sample persons. | `data/processed/`, `scripts/build_languages_pums.py`, `tests/test_deliverables.py` |
| Client network | The app makes no upstream calls: no NWS or other APIs. The only fetch is the same-origin `data/bundle.json`. The user chooses the hazard. | `app/app.js`, test `AppCode` |
| Service worker | Same-origin GET requests only; cache name versioned by a hash of every pre-cached file; old caches deleted on activation. | `app/sw.js`, `scripts/build_app_data.py` |
| Headers | CSP `default-src 'self'` and `connect-src 'self'`; no inline script or style; `frame-ancestors 'none'`; `Referrer-Policy: no-referrer`; `X-Content-Type-Options: nosniff`; `no-cache` for `sw.js` and data. | `app/_headers`, CSP meta tag in `app/index.html` |
| Supply chain | No third-party JavaScript, CSS, fonts or CDNs. The pipeline uses the Python standard library only. | `app/`, `scripts/` |
| Integrity | Versioned data bundle (content hash) with a "data as of" stamp shown in the app and on every printed page. | `app/data/version.json` |
| Content | DOM built with `textContent` (no `innerHTML`). Message templates require a named human reviewer before `approved = yes`; a test enforces this. | `app/app.js`, `tests/test_match.py` |
