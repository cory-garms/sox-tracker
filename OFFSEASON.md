# 2026 offseason archive

The reports committed on October 27, 2026 are the archive source. Keep their
original timestamps: a recent build is not a claim that every dataset is final.
The export adds an archive notice to every report and preserves the chart
JavaScript, images, HTML filenames, and short page URLs. No Python server,
database, MLB API, or odds API is needed to serve it. Fonts and analytics still
use their existing external providers.

## Build

```sh
python scripts/build_static_archive.py
```

Deploy only `output/offseason/`, never the repository or data directory.
This build uses the Python standard library and makes no network calls.
It replaces its own disposable output; it does not rebuild model predictions.

## GitHub Pages cutover

1. Commit and push these changes to the default branch.
2. In repository Settings → Pages, select **GitHub Actions** as the source.
3. Run **Publish offseason archive** from Actions.
4. Set the Pages custom domain to `dirtywater.corygarms.com` and save it
   **before** changing DNS. The `CNAME` file alone does not configure a domain
   for an Actions deployment.
5. In Vercel, open your team's **Domains** page, select `corygarms.com`, and
   open its DNS records. Replace the Render record for `dirtywater` with:

   | Type | Name | Value | TTL |
   | --- | --- | --- | --- |
   | CNAME | `dirtywater` | `cory-garms.github.io` | Default |

   Enter only `dirtywater` in the Name field and no URL scheme or repository
   path in the Value field. Remove conflicting records for this same hostname.
   No Vercel project or Vercel deployment is needed; Vercel remains the DNS
   provider. Leave all other `corygarms.com` records as they are.
6. Enable **Enforce HTTPS** when GitHub makes it available. Check `/`,
   `/dashboard`, `/track_record`, `/notebook`, and `/images/sox_retro_logo.png`.
   Check navigation from a short URL, mobile layout, and chart interactions.
7. Confirm in Render's billing/service settings that paid compute and any other
   billable resources are stopped. HTTP 503 with `suspend-by-user` confirms the
   service is suspended, but does not establish the account's billing state.
   Retain the deployment configuration and data for next season.

GitHub Pages is free for public repositories on GitHub Free; private repositories
require a qualifying plan. If using another static host, upload the same output
directory and configure the custom domain there instead.

The refresh, closing-line capture, postgame rebuild, and live deploy-check
workflows now have manual triggers only. Push these changes for that pause to
take effect remotely. Already queued runs may need to be canceled in Actions.
The existing deploy check expects a live API and fresh data, so do not run it
against this historical static site.

## Next season

Keep the static site available while restoring the backend. Review
`NEXT_SEASON_PLAN.md`, update the season and data, restore the scheduled triggers
from Git history, and verify the backend before pointing DNS back to it. Restore
the deploy-check schedule only after the live API is back. Do not delete the
historical predictions, odds snapshots, or database as part of this cutover.

References: [Pages workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages),
[custom domains](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site),
[Vercel DNS records](https://vercel.com/docs/domains/managing-dns-records).
