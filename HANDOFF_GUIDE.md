# ⚾ `sox_tracker` — Handoff & Current State

> Updated **2026-08-23**. Supersedes the earlier 2026-07-27 handoff guide.
>
> **Core Architecture & Philosophy Updates**:
> 1. **Stats-First Pivot**: The web suite has pivoted to a **Stats-First** architecture. The default primary mode across the navigation and landing page is `📊 Season & Matchup` (`MODE_SEASON`), while `🎲 Odds & Models` (`MODE_BETTING`) is secondary.
> 2. **Production Backend & Database**: Live FastAPI backend deployed on **Render** (`https://dirtywater-app.onrender.com` / `https://dirtywater.corygarms.com`), connected to a serverless PostgreSQL database (Neon.tech).
> 3. **Active Roster Filtering**: All player-level charts (rotation heatmap, bullpen load, batting leaderboards, hot/cold tracker, platoon matchup) strictly filter by the active 26-man roster so traded players (e.g. Connelly Early, Marcelo Mayer) do not appear in active team views.
> 4. **Continuous Game Number X-Axis**: Trajectory and rolling charts use continuous **Game Number (1..162)** on the X-axis with rich date/opponent tooltips on hover.

---

## 🎯 1. What This Is

`sox_tracker` (branded as **Dirty Water**) is an MLB team analytics & performance suite focused on the **Boston Red Sox** (`TEAM_ID = 111`).

### Site Modes & Hierarchy
| Mode | Pages | Character |
| :--- | :--- | :--- |
| 📊 **Season & Matchup** (Default) | Today's Matchup, Season Dashboard, Stat Leaders, Win Streaks | Clean, analytical team record, player leaderboards, rotation/bullpen load, and pre-game advantages |
| 🎲 **Odds & Models** (Secondary) | Tonight's Board, Models & Method, How This Works | Live line comparison against model projections, CLV tracking, and methodology notes |

- **Live URL**: [`https://dirtywater.corygarms.com`](https://dirtywater.corygarms.com) / [`https://dirtywater-app.onrender.com`](https://dirtywater-app.onrender.com)
- **Static GitHub Pages Mirror**: [`https://cory-garms.github.io/sox-tracker/`](https://cory-garms.github.io/sox-tracker/)
- **Repository path**: `/home/cgarms/Projects/sox-tracker`
- **Virtual environment**: Python 3.11+, `pip install -r requirements.txt`
- **Refresh**: `.github/workflows/refresh.yml` rebuilds every page four times a
  day (07:00 / 12:00 / 15:00 / 17:30 ET), so the board is never many hours stale
  by first pitch.
- **Post-game**: `.github/workflows/postgame.yml` rebuilds the *stats* pages
  within ~30 minutes of a final out. The four scheduled builds are aimed at the
  pre-game board; none was aimed at the end of the game, so a 19:10 ET result
  did not reach the site until 07:00 the next morning. Gated by
  `scripts/postgame_check.py` on a free MLB schedule read, and it skips
  `betting_report.py` — a finished game has no line worth pricing, and that is
  the build that spends quota. **Cost: zero credits.** This is also the caller
  for `POST /api/v1/refresh`.
- **Closing capture**: `.github/workflows/close.yml` runs every 20 minutes across
  MLB's start window and spends credits *only* when first pitch is imminent —
  the schedule read that gates it costs zero quota. See
  [ODDS_SPRINT_HANDOFF.md](ODDS_SPRINT_HANDOFF.md) §3.
- **Odds budget**: ~450 credits/month against a 500 quota. Count before adding a
  market.

### ⚠️ GitHub Actions is the *only* thing that may buy odds

There are two schedulers in this project and they used to both fetch prices:

| System | Reliable? | Fetches odds |
|---|---|---|
| GitHub Actions (`refresh.yml`, `close.yml`) | Yes | **Yes — the only owner** |
| Render `backend/services/scheduler.py` | No — free plan spins the process down when idle | **No** |

The Render job ran at 08:30/12:30/15:30/17:30 ET against the Action's
07:00/12:00/15:00/17:30, so at 17:30 they fired simultaneously and bought the
same board twice — about 240 credits/month of pure duplication on top of the
Actions' ~450, against a 500 quota.

`archive_predictions_job` now reads prices back out of Postgres
(`repository.latest_lines_by_market`) instead of re-purchasing them, so it
costs nothing. **Before adding any odds fetch, check which system you are
adding it to.** If it is not a GitHub Action, it is the wrong one.

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

## 🔌 8. REST API surface

Everything below is live in [`backend/api/routes.py`](backend/api/routes.py) and
covered by `tests/test_api.py`. The season tables are read from the **parquet
cache**, not Postgres — Postgres holds odds, predictions and the bet log. A
route whose cache has not been built returns **503**, not 404: that is a
deployment state, not a bad request.

| Method | Route | Notes |
|---|---|---|
| GET | `/healthz` | Render health check |
| GET | `/api/v1/games` | Season log, `?result=W&limit=n`. Ordered by `played_in_order`, never by `game_pk` |
| GET | `/api/v1/standings` | Record, Pythagorean, splits, current + longest streaks |
| GET | `/api/v1/analytics/turnaround` | Net games above .500 per game, with peak and trough |
| GET | `/api/v1/analytics/matchup/today` | Opponent, probables, active-roster bullpen availability |
| GET | `/api/v1/schedule/today` | Scheduler-synced rows, lineup confirmation |
| GET/POST | `/api/v1/bets` | Bet log |
| GET | `/api/v1/bets/clv` | Closing-line-value summary |
| GET | `/api/v1/predictions` | Archived projections and edges |
| GET | `/api/v1/odds/movement` | Line trajectory for one event/market/player |
| POST | `/api/v1/refresh` | **Authenticated.** Re-ingests the parquet cache |

### The refresh webhook

```bash
curl -X POST https://dirtywater.corygarms.com/api/v1/refresh \
     -H "X-Refresh-Token: $REFRESH_TOKEN"
# optional: ?tables=games,pitching
```

Auth is a shared secret in `REFRESH_TOKEN`, compared with `hmac.compare_digest`.
**An unset token disables the route (503) rather than leaving it open** —
refresh hits the MLB API and can spend odds credits, so it must never be
triggerable by an anonymous caller.

It runs synchronously and reports per-table outcomes (`status: ok | partial`),
so the caller learns which tables actually refreshed instead of getting a bare
202. Tables are refreshed in dependency order regardless of request order,
because the per-game log tables are built by walking the games table.

---

## 📋 9. Known Gaps & Observations

1. **`docs/index.html` sync**: `docs/index.html` is the primary stats-first landing page. `scripts/refresh_nav.py` updates the navigation bar across all HTML pages.
2. **CDN vs Local JS**: Pages embed Plotly bundle (`include_plotlyjs=True` on first div) to avoid CDN version drift on standalone offline files.
3. **Doubleheader Scheduling**: Doubleheaders are handled cleanly in `matchup_report.py` and `viz/charts.py` using `(game_date, game_number)` sorting via `analysis.streaks.played_in_order`.
4. **Active Roster Ingestion**: `fetch.py --refresh` fetches active 26-man roster, ensuring trades (e.g. Early, Mayer) are updated in active team charts.

---

## 🔍 10. Site audit — 2026-08-23

All eight pages, the chart layer and the backend were audited. Pages, roster
filtering, doubleheader ordering, the model error bars and the NO CALL
discipline all held up. Four things did not.

### Fixed in this pass

**1. The bullpen table listed the starting rotation as available relief.**
The bug that mattered. `bullpen_availability` took its row list straight from
the caller's roster-derived name set, and the roster is no help here — MLB tags
every pitcher on the 26-man with `position_group == "SP"`. Only *today's*
starter was subtracted, so Gray, Suárez, Tolle and Sandoval all got rows.

Pitch counts were summed from relief appearances only, so a start contributed
nothing: **Patrick Sandoval started on 8/22 and the 8/23 page showed him as
`0 pitches — 🟢 FRESH`**, the least available arm on the staff rendered as the
most.

Role is now read from *recent usage* over a trailing `role_window_days=30`
window, and pitch counts include starts. Recency matters in both directions:
Brayan Bello opened 2026 in the rotation and has relieved exclusively since
July, so he belongs in the table; a season-long "has he ever relieved?" rule
would have kept him but equally kept a reliever *promoted* into the rotation.
A pitcher with no appearances in the window falls back to his season split
rather than vanishing. Guarded by `tests/test_bullpen_availability.py`.

**2. Half the documented API did not exist.** This guide and the API docs
listed `/api/v1/games`, `/api/v1/standings` and the analytics routes as live.
The router stopped at `/schedule/today`. All are now implemented — see §8.

**3. `POST /api/v1/refresh`** added, token-authenticated, disabled when
unset. See §8.

**4. Touch tooltips.** `hovermode` was never set anywhere in `viz/`, leaving
Plotly's default `"closest"` — a fine mouse target and a poor thumb one, since
a 162-point trajectory line is mostly gaps at 390px. Continuous-X and
dual-axis charts now spread `theme.TIME_SERIES_HOVER` (`x unified` + a spike
line), which widens the target to the whole column and reads every series at
that game in one label. Deliberately opt-in: on a horizontal bar leaderboard
`x unified` groups by value rather than by player, and on a heatmap it means
nothing.

Also: `httpx` was missing from `requirements-dev.txt`, so `tests/test_api.py`
could not be collected from a clean checkout — `fastapi.testclient` re-exports
starlette's, which raises at import time without it.

### Open — not addressed in this pass

1. **`docs/index.html` is hand-maintained.** 325 lines duplicating the theme
   palette and the `theme.PAGES` registry. `test_navigation.py` checks every
   registered page is linked, but nothing holds the labels, ordering or mode
   grouping to the registry. Generating it from `theme.PAGES` is the fix.
2. **Statcast overlay is wired but unused.** `analysis.offense.enrich_with_statcast`
   exists and is called from nowhere; `leaders_report.py` never invokes it.
   Note `get_batter_statcast` passes `min="q"` (qualified PA only), so bench
   bats come back blank — the leaderboard needs a lower threshold or an
   explicit "not qualified" state before this is worth surfacing.
3. **Rotation/bullpen dashboard cards are roster-filtered but not labelled so.**
   The card headings read "Rotation Game Scores" and "Bullpen Workload"; a
   reader cannot tell traded players are excluded.
4. **Small-sample starter lines are shown unqualified.** The matchup page
   rendered the opposing starter at "ERA 0.00, WHIP 0.50" off 2.0 IP.
