# ⚾ `sox_tracker` — Handoff & Current State

> Updated **2026-07-27**. Supersedes the earlier migration/redesign blueprint —
> both workstreams in that document have been carried out, with one exception
> that turned out to be blocked for reasons no amount of code can fix (see §2).
>
> **The betting side has outgrown this document.** It is now its own interface
> with its own measurement loop, and everything specific to it —  the consensus
> engine, promotions, the bet log, closing-line capture, and the traps that will
> bite you — lives in [ODDS_SPRINT_HANDOFF.md](ODDS_SPRINT_HANDOFF.md). Read that
> before touching anything under "Gambling Takes".

---

## 🎯 1. What This Is

`sox_tracker` is a Python MLB analytics suite that publishes interactive GitHub
Pages dashboards for the **Boston Red Sox** (`TEAM_ID = 111`).

Since 2026-07-27 the suite is divided by a switch at the top of every page:

| Mode | Pages | Character |
| :--- | :--- | :--- |
| 🎲 **Gambling Takes** | Tonight's Board, Models & Method, How This Works, Today's Matchup | Stale within the hour; every page states when it was read |
| 📊 **Season Stats** | Season Dashboard, Stat Leaders, Win Streaks | The settled record; reads the same at noon and at midnight |

**Navigation is generated from `viz/theme.PAGES` and `theme.nav_bar()`** — one
definition, not one per exporter. Register a new page there; the tests enforce
that the registry, the generators and `docs/index.html` agree. The mode shown is
*derived* from the current page rather than stored, so the control cannot
disagree with what is on screen.

- **Repository path**: `/home/cgarms/Projects/sox-tracker`
- **Virtual environment**: Python 3.11+, `pip install -r requirements.txt`
- **Output**: `docs/` → published at
  [cory-garms.github.io/sox-tracker](https://cory-garms.github.io/sox-tracker/)
- **Refresh**: `.github/workflows/refresh.yml` rebuilds every page four times a
  day (07:00 / 12:00 / 15:00 / 17:30 ET), so the board is never many hours stale
  by first pitch.
- **Closing capture**: `.github/workflows/close.yml` runs every 20 minutes across
  MLB's start window and spends credits *only* when first pitch is imminent —
  the schedule read that gates it costs zero quota. See
  [ODDS_SPRINT_HANDOFF.md](ODDS_SPRINT_HANDOFF.md) §3.
- **Odds budget**: ~480 credits/month against a 500 quota. Count before adding a
  market.

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
│   └── odds_history.py    # append-only log of every build's lines
├── analysis/              # standings, offense, pitching, defense,
│                          # streaks, matchup, history, betting
├── scripts/               # verify_odds.py, backtest_league_k.py, backtest_batter_tb.py
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

pytest                                               # 230 tests, offline, ~0.7s
python scripts/verify_odds.py                        # live odds pipeline + quota
python scripts/backtest_batter_tb.py                 # re-measure the total-bases error bar
python scripts/backtest_league_k.py                  # re-measure MODEL_ERROR_K (all league starters)
```

**Run `pytest` before every commit.** The suite is fully offline — no network, no
API key, no cached parquet required — so there is no excuse to skip it. Fakes for
the MLB and odds clients live in `tests/conftest.py` and `tests/test_betting_models.py`.

Tests here exist to pin down *behaviour that was once wrong*: each class
docstring names the bug it guards against. Keep that convention — a test whose
name explains only what it does, rather than what it prevents, tends to get
deleted by the next person who finds it inconvenient.

---

## 📋 8. Known Gaps / Next Up

> Betting-specific gaps live in [ODDS_SPRINT_HANDOFF.md](ODDS_SPRINT_HANDOFF.md)
> §9. What follows is everything else.

**Live traps, in priority order:**

1. **No lineup cross-check.** On 2026-07-27 a hitter carried a live total-bases
   prop while not in the posted lineup and nothing flagged it. One free MLB call.
2. **`docs/index.html` is hand-maintained** while `viz/theme.PAGES` is generated.
   A test asserts they agree, but the index is edited by hand and will drift.
   Generating it is the real fix.
3. **`data/cache/bet_log.parquet` is committed to a public repo.** Cory is aware
   and has chosen to keep it public (2026-07-27); stakes are in units, not
   dollars. Do not "helpfully" redact it without asking.
4. **The `bottleneck` package is compiled against NumPy 1.x** in this
   environment, so every script prints an `_ARRAY_API not found` traceback. It is
   noise — every report still generates. `pip install --upgrade bottleneck` fixes
   it; it is environmental, not a repo problem.


1. **The strikeout model now calls sides; the total-bases model still does not.**
   Resolved for strikeouts on 2026-08-04 — `MODEL_ERROR_K` fell from 1.39 to
   **0.45 K** and the recommendation band opened on its own. What actually
   changed was the *measurement*: the old number came from 73 starts of one
   rotation (SE ±0.41 K), which could not resolve any modelling change and had
   wrongly recorded the opponent adjustment as useless. Re-run over all 2,347
   league starts, regression toward the league mean and the opponent factor both
   measure as real, and the season/last-5 blend measures as worthless.

   **Still open:** no park or platoon adjustment, and the total-bases model's
   **±4.9 probability points** remains larger than any edge it has found, so that
   table still publishes the line, both probabilities and the gap without calling
   a side. See [ODDS_SPRINT_HANDOFF.md §6](ODDS_SPRINT_HANDOFF.md) for the
   measurement and the two statistical traps it exposed.

   **Watch this.** The page recommends real bets for the first time and the CLV
   record is 10 graded bets long. Log new ones as paper (`--stake 0`) until the
   sign means something.
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
5. **Game-level markets are fetched but never shown.** `get_game_odds()` pulls
   moneyline and totals, and nothing on the page uses them. `roadmap.md` item 2.
   (Player props *are* available on the free tier — an earlier note here
   claiming otherwise was wrong; see [CONFIGURE.md](CONFIGURE.md).)
