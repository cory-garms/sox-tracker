# Sox Tracker — Publishing Guide for Agent

> ⚠️ **Superseded 2026-08-24.** This describes publishing to GitHub Pages,
> which has been retired in favour of a single canonical domain
> (`dirtywater.corygarms.com`, served by the FastAPI app on Render).
> Kept because the `docs/` layout and the build commands below are still
> accurate — only the hosting section is out of date. Do not re-enable
> Pages from these instructions without reading §11 of HANDOFF_GUIDE.md.

This document captures the exact steps and known pitfalls for publishing the
sox-tracker HTML dashboard to GitHub Pages with automatic daily updates,
mirroring what was done for spurs-tracker.

---

## What we're building

- Static HTML dashboard committed to `docs/` in the GitHub repo
- GitHub Pages serves `docs/` from the `master` branch
- A GitHub Actions workflow rebuilds the HTML daily
- The user runs `fetch.py --refresh` locally and pushes to update data
  (MLB Stats API may or may not be blocked from GitHub Actions IPs —
  test it; if it times out, add `continue-on-error: true` to the fetch step)

---

## Step 1 — Rename output dir to docs/

GitHub Pages supports two source directories on the default branch: repo root
or `/docs`. Using `/docs` keeps generated files separate from source code.

In `config.py`, change:
```python
OUTPUT_DIR = BASE_DIR / "output"
```
to:
```python
OUTPUT_DIR = BASE_DIR / "docs"
```

In `.gitignore`, replace any `output/` exclusion with `docs/img/` (exclude
PNG exports but keep the HTML files):
```
# PNG exports
docs/img/
output/
```

In the GitHub Actions workflow, update the `git add` line:
```yaml
git add data/cache/ docs/
```

---

## Step 2 — Fix Plotly rendering (critical)

Plotly 6.x uses binary array encoding (`dtype`/`bdata` format) when
serializing chart data. If the dashboard uses `include_plotlyjs="cdn"`,
the browser may load a mismatched Plotly.js version from the CDN that
cannot decode this format — charts silently render as zeros or blanks.

**Fix:** In `viz/dashboard.py` (or wherever charts are assembled into HTML),
use `include_plotlyjs=True` for the first figure and `False` for the rest:

```python
include_js = True if i == 0 else False
chart_div = pio.to_html(fig, full_html=False, include_plotlyjs=include_js, div_id=div_id)
```

This embeds the full Plotly.js bundle (~3 MB) directly in the HTML,
guaranteeing version compatibility. File size increases from ~100 KB to ~5 MB
but renders correctly in all browsers without an internet connection.

---

## Step 3 — Add docs/index.html redirect

So the root URL (`https://username.github.io/sox-tracker/`) works:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="0; url=dashboard_BOS_2026.html">
  <title>Sox Tracker</title>
</head>
<body>
  <p>Redirecting to <a href="dashboard_BOS_2026.html">dashboard</a>…</p>
</body>
</html>
```

Adjust the filename to match the team abbreviation and season used.

---

## Step 4 — Commit parquet cache files

MLB/NBA stats APIs block requests from GitHub Actions datacenter IPs.
The reliable workaround is to commit the parquet cache to the repo so
the workflow only needs to rebuild HTML (no API calls required in CI).

In `.gitignore`, remove any line that excludes parquet files:
```
# Remove this line if present:
data/cache/*.parquet
```

Then stage and commit the current cache:
```bash
git add data/cache/
git commit -m "feat: commit parquet cache for CI"
```

---

## Step 5 — GitHub Actions workflow

Create `.github/workflows/refresh.yml`. **Critical:** write and commit this
file directly on GitHub.com using the web editor (pencil icon), not via
local push. GitHub's workflow parser sometimes rejects locally-created files
due to invisible characters or encoding edge cases even when `file` reports
valid UTF-8. The web editor runs live YAML validation and guarantees the file
is recognized.

Workflow content:
```yaml
name: Daily Data Refresh

on:
  schedule:
    - cron: "0 12 * * *"
  workflow_dispatch:

jobs:
  refresh:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Fetch data
        run: python fetch.py --team BOS --season 2025 --refresh
        continue-on-error: true

      - name: Build dashboard
        run: python viz_report.py --team BOS --season 2025

      - name: Commit updated data
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add docs/
          git diff --cached --quiet || git commit -m "chore: auto-refresh data $(date -u +%Y-%m-%d)"
          git push
```

Notes:
- `continue-on-error: true` on the fetch step means a timeout will not
  block the HTML rebuild — the workflow always publishes whatever data
  is in the cache.
- Avoid non-ASCII characters (em dashes, smart quotes) in the YAML file.
  They cause GitHub's workflow parser to silently reject the file.
- If the workflow does not appear in the Actions sidebar after committing
  via the web editor, navigate directly to:
  `https://github.com/USERNAME/sox-tracker/actions/workflows/refresh.yml`

---

## Step 6 — Enable GitHub Pages

1. Go to repo **Settings → Pages**
2. Source: **Deploy from a branch**
3. Branch: `master` (or `main` — whatever the default branch is), folder: `/docs`
4. Click **Save**

The live URL will be: `https://USERNAME.github.io/sox-tracker/`

---

## Step 7 — Test the workflow

1. **Actions tab → Daily Data Refresh → Run workflow**
2. Watch all steps go green (~3-5 minutes)
3. Reload the Pages URL

If the Fetch data step fails (red X) but Build dashboard succeeds (green),
that is expected and acceptable — it means the API was unreachable from CI
but the HTML was rebuilt from the committed cache and deployed.

---

## Day-to-day update process

Run locally after each game:
```bash
python fetch.py --team BOS --season 2025 --refresh
python viz_report.py --team BOS --season 2025
git add data/cache/ docs/
git commit -m "data: refresh YYYY-MM-DD"
git push
```

GitHub Pages deploys within ~1 minute of the push.

---

## Checklist

- [ ] `OUTPUT_DIR` changed to `docs/` in config.py
- [ ] `include_plotlyjs=True` (not `"cdn"`) in dashboard builder
- [ ] `docs/index.html` redirect created
- [ ] `data/cache/*.parquet` removed from `.gitignore`
- [ ] Parquet cache committed to repo
- [ ] Workflow created via GitHub web editor (not local push)
- [ ] GitHub Pages enabled: master branch, /docs folder
- [ ] Manual workflow run succeeded (fetch may fail; build must succeed)
- [ ] Live URL confirmed working
