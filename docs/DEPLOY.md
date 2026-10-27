# Deploy: Cloudflare Pages

**Not deployed yet.** These are the settings for the first deploy.

| Setting | Value |
|---|---|
| Production branch | `main` |
| Root directory | repository root |
| Build command | `python3 scripts/build_app_data.py --copy-only` |
| Build output directory | `app` |
| Environment variables | none |
| Custom domain | `shelters.kahuola.org` (placeholder) |

The build step only copies the 20 committed PDFs from `playbooks/` into `app/playbooks/`. That folder is gitignored, so the PDFs are committed only once. The data bundle, the service worker's precache list and the PDFs are already built and committed, so the build needs no network and no extra packages (the Python standard library is enough).

`app/_headers` sets the security headers (CSP, Permissions-Policy, Referrer-Policy) and `no-cache` for `sw.js` and `data/*`, so updates reach users.

## Updating data

1. Rebuild locally (see `README.md`): ending with `build_playbooks.py` and `build_app_data.py`.
2. `python3 -m unittest discover tests`
3. Commit `playbooks/`, `app/` and `data/processed/`, then push. Pages rebuilds automatically.

The service worker cache name is a hash of every pre-cached file, so any change to data, PDFs or app code replaces the old offline cache on the next online visit.
