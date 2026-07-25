# ⚾ `sox_tracker` — Handoff & Current State

> Updated 2026-07-24. Supersedes the earlier migration/redesign blueprint — both
> workstreams in that document have been carried out, with one exception that
> turned out to be blocked for reasons no amount of code can fix (see §2).

---

## 🎯 1. What This Is

`sox_tracker` is a Python MLB analytics suite that publishes five interactive
GitHub Pages dashboards for the **Boston Red Sox** (`TEAM_ID = 111`).

- **Repository path**: `/home/cgarms/Projects/sox-tracker`
- **Virtual environment**: Python 3.11+, `pip install -r requirements.txt`
- **Output**: `docs/` → published at
  [cory-garms.github.io/sox-tracker](https://cory-garms.github.io/sox-tracker/)
- **Refresh**: `.github/workflows/refresh.yml` runs daily at 11:00 UTC and now
  rebuilds **all five** pages (it previously rebuilt only the main dashboard,
  leaving the other four stale).

---

## 💰 2. Sportsbook Odds — DraftKings is blocked; use The Odds API

**The DraftKings plan in the previous handoff cannot be completed.** This is not
a bug, a wrong Event Group ID, or a header problem:

```
403 Access Denied   sportsbook-us-ma.draftkings.com/.../v2/eventgroups/84240
403 Access Denied   sportsbook.draftkings.com/.../v5/eventgroups/84240
```

Every host and API version returns `403` from an Akamai edge that rejects
non-browser clients regardless of User-Agent, Origin, or TLS settings. Getting
past it would require a residential proxy or browser automation, which is
brittle and sits uneasily with DraftKings' terms of service.

`client/draftkings_client.py` is kept but **dormant**, with the status recorded
in its module docstring. Live lines now come from
[`client/odds_api_client.py`](client/odds_api_client.py) — The Odds API, which
aggregates DraftKings prices and is reachable with a free key.

### Setup
See [CONFIGURE.md](CONFIGURE.md). In short: `export ODDS_API_KEY="..."`, or add
a repo secret of the same name for the Action.

### What was wrong with the old betting model
The strikeout model set the prop line **from its own projection**
(`line = round(proj * 2) / 2`), so the edge was mathematically pinned within
±0.25 and could never cross the ±0.3 recommendation threshold. Every pitcher
returned `NEUTRAL`, and the "EV%" was computed against a hardcoded `-115` that
no book had quoted. It looked like a betting model and measured nothing.

Now: edge and EV are produced **only** when a real book line exists. With no key,
the page shows projections and says so. Other corrections in the same pass:
- NRFI no longer falls back to `total game runs <= 7` as a stand-in for
  first-inning runs; without linescores it reports unavailable.
- A failed linescore fetch drops the game instead of silently counting it a NRFI.
- `f5_era` / `f5_whip` renamed — they were full-game rates prorated to five
  innings, not measured first-five splits.
- Minimum 3 starts before a pitcher gets a prop projection (one-start relievers
  were being listed as prop targets).

---

## 🎨 3. Fenway Redesign — done

All styling now lives in **[`viz/theme.py`](viz/theme.py)**, the single source of
truth. Previously each of the five exporters carried its own copy of the palette
and inline CSS.

Delivered: Green Monster slat header, ticket-stub cards (dashed aged-brass
borders with corner notches), scoreboard number plates, `Alfa Slab One` /
`Graduate` / `Share Tech Mono` typography, and `EST. 1912 · FENWAY PARK` stamps.

### ⚠️ The chart palette is validated — don't casually edit it

`theme.CATEGORICAL` is a fixed-order sequence checked against the data-viz
criteria on the dark press-box surface:

| Check | Result |
|---|---|
| Lightness band | all 4 inside OKLCH L 0.48–0.67 |
| Chroma floor | all 4 ≥ 0.10 |
| CVD separation | worst adjacent ΔE **12.6** (deutan) — target ≥ 8 |
| Normal-vision floor | worst adjacent ΔE **21.1** — floor ≥ 15 |
| Contrast vs surface | all 4 ≥ 3.0:1 |

The handoff's originally proposed palette **failed** this: scoreboard yellow
`#F3C010` (L=0.83) and blue `#58A6FF` (L=0.715) sit outside the dark-mode
lightness band. They were snapped to `#b08a02` and `#4391e9`, preserving hue.

Rules: assign hues in fixed order, never cycle (`theme.categorical()` raises
past the validated set). There is deliberately **no 5th hue** — a 5th series
folds into "Other", small multiples, or `theme.SEQUENTIAL_GREEN`. Ordered
categories (the streak milestone ladder) use the sequential ramp, not
categorical hues.

---

## 📱 4. Mobile is the priority

The suite is read mostly on phones. **Verify every UI change at ~390px width,
not desktop.** Patterns already in place:

- `config=theme.PLOTLY_CONFIG` on every `pio.to_html` call — sets
  `responsive: True`. Without it a figure bakes in its initial render width and
  clips on a phone.
- Redundant in-chart titles are stripped in `viz/dashboard.py`; the card `<h2>`
  above already names the chart, and dropping it frees vertical space.
- Short axis category labels; full descriptor in the hover via `customdata`.
- Wide tables sit in `.table-scroll` with a **sticky first column** and a
  "swipe to see all columns" hint.
- Reference-line annotations use `annotation_position="top left"` so they don't
  clip off the right edge.

---

## 🏗️ 5. Data Integrity — the doubleheader trap

**Never order games by `game_pk`.** MLB assigns `gamePk` at scheduling time, so a
rained-out game made up as game 1 of a later doubleheader carries a *lower* pk
than the nightcap it precedes.

This was live: sorting by pk read the 2026 win streak as **14 games ending 7/20**
when it was actually **15 ending with game 1 on 7/22** — the pk sort placed that
day's loss ahead of its win.

Use `analysis.streaks.played_in_order(games)`, which sorts by
`(game_date, game_number)` using MLB's own `gameNumber` (now captured in the
games schema).

Two related fetcher bugs fixed in `data/fetcher.py`:
1. Postponed games return `abstractGameState == "Final"`, so they passed the
   completed-games filter and landed in the cache as phantom losses (a 0–0 game
   scored `result = "L"`). Now filtered on `detailedState`, and ties score `"T"`.
2. The same `gamePk` appears twice — once under its original date, once under
   the makeup date. Now deduped.

---

## 🏗️ 6. Repository Structure

```
sox_tracker/
├── config.py              # Team ID, season, paths, ODDS_API_KEY
├── fetch.py               # Ingestion CLI → parquet cache
├── report.py              # Rich terminal dashboard
├── viz_report.py          # → docs/dashboard_BOS_2026.html
├── leaders_report.py      # → docs/leaders_BOS_2026.html
├── matchup_report.py      # → docs/matchup_BOS_2026.html
├── streak_report.py       # → docs/streak_records_BOS_2026.html
├── betting_report.py      # → docs/betting_BOS_2026.html
├── client/
│   ├── mlb_client.py          # MLB Stats API
│   ├── savant_client.py       # Baseball Savant / Statcast
│   ├── odds_api_client.py     # The Odds API (live lines)
│   ├── odds_math.py           # Odds conversion + de-vig, pure functions
│   └── draftkings_client.py   # DORMANT — 403 blocked, see §2
├── data/                  # schema.py, roster.py, fetcher.py, cache/
├── analysis/              # standings, offense, pitching, defense,
│                          # streaks, matchup, history, betting
└── viz/
    ├── theme.py           # ★ palette, fonts, Plotly base, page CSS
    ├── charts.py          # Plotly chart builders
    ├── dashboard.py       # dashboard HTML assembly
    └── exports.py
```

---

## 🚀 7. Commands

```bash
python fetch.py --team BOS --season 2026 --refresh   # refresh parquet cache
python report.py                                     # terminal dashboard

python viz_report.py     --team BOS --season 2026
python leaders_report.py --team BOS --season 2026
python matchup_report.py --team BOS --season 2026
python betting_report.py --team BOS --season 2026    # needs ODDS_API_KEY for lines
python streak_report.py                              # no --team flag yet
```

---

## 📋 8. Known Gaps / Next Up

1. **No tests.** ~9,000 lines of numeric code with zero test coverage. The pure
   functions in `analysis/` need no network and would have caught the circular
   edge bug immediately. Highest-value next step.
2. **Repo weight.** Pages embed the full ~4.7 MB Plotly bundle
   (`include_plotlyjs=True`), and the daily Action commits them, so history grows
   ~5 MB/page/day. This is deliberate — a code comment notes it avoids CDN
   version-mismatch blanks — but `include_plotlyjs="cdn"` would cut each page to
   ~30 KB. Worth revisiting.
3. **`streak_report.py` is Red Sox only** — hardcoded franchise records, no
   `--team` flag, hardcoded output filename.
4. **`run_differential_chart` is a dual-axis chart** (per-game bars + cumulative
   line on a secondary y). Two scales on one plot is a well-known way to imply
   relationships that aren't there; splitting it into two charts or indexing to a
   common base would be more honest.
5. **Player props need a paid Odds API tier.** Game-level markets (moneyline,
   totals) work on the free tier; strikeout and total-bases props do not.
6. **`docs/dashboard_BOS_2025.html`** (5 MB, last season) is still tracked.
