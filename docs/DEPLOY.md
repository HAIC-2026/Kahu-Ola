# Deploy: Cloudflare Pages

**Deployed.** The app is live on the Cloudflare Pages project `haic2026-shelters`:

- https://shelters.kahuola.org
- https://haic2026-shelters.pages.dev

| Setting | Value |
|---|---|
| Pages project | `haic2026-shelters` |
| Deploy command | `python3 scripts/build_app_data.py --copy-only && npx wrangler pages deploy app --project-name haic2026-shelters` |
| Output directory | `app` |
| Environment variables | none |
| Custom domain | `shelters.kahuola.org` |

The build step only copies the 20 committed PDFs from `playbooks/` into `app/playbooks/`. That folder is gitignored, so the PDFs are committed only once. The data bundle, the service worker's precache list and the PDFs are already built and committed, so the build needs no network and no extra packages (the Python standard library is enough). `wrangler` then uploads the `app` folder.

`app/_headers` sets the security headers (CSP, Permissions-Policy, Referrer-Policy) and `no-cache` for `sw.js` and `data/*`, so updates reach users.

## Redeploy after data changes

1. Rebuild locally (see `README.md`), ending with `build_playbooks.py` and `build_app_data.py`.
2. `python3 -m unittest discover tests`
3. Commit `playbooks/`, `app/` and `data/processed/`, then push.
4. Deploy:

```sh
python3 scripts/build_app_data.py --copy-only
npx wrangler pages deploy app --project-name haic2026-shelters
```

The service worker cache name is a hash of every pre-cached file, so any change to data, PDFs or app code replaces the old offline cache on the next online visit.
