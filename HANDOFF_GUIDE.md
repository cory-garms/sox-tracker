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

## 📋 8. Known Gaps & Observations

1. **`docs/index.html` sync**: `docs/index.html` is the primary stats-first landing page. `scripts/refresh_nav.py` updates the navigation bar across all HTML pages.
2. **CDN vs Local JS**: Pages embed Plotly bundle (`include_plotlyjs=True` on first div) to avoid CDN version drift on standalone offline files.
3. **Doubleheader Scheduling**: Doubleheaders are handled cleanly in `matchup_report.py` and `viz/charts.py` using `(game_date, game_number)` sorting via `analysis.streaks.played_in_order`.
4. **Active Roster Ingestion**: `fetch.py --refresh` fetches active 26-man roster, ensuring trades (e.g. Early, Mayer) are updated in active team charts.

---

## 🔍 9. Instructions for Next Agent: Full Site Audit & Improvement Plan

The next agent should perform a **comprehensive site audit** across design, data integrity, user experience, and backend services, followed by executing planned improvements:

### Phase 1: Full Site Audit Checklist
- [ ] **Audit Page 1: Landing Page (`/` / `docs/index.html`)**
  - Verify stats-first visual hierarchy, hero CTAs, card links, and mobile responsiveness at ~390px.
- [ ] **Audit Page 2: Today's Matchup (`/matchup` / `docs/matchup_BOS_2026.html`)**
  - Inspect probable starting pitcher cards, platoon splits against opposing starter, and 3-day bullpen availability. Verify traded pitchers/hitters are excluded.
- [ ] **Audit Page 3: Season Dashboard (`/dashboard` / `docs/dashboard_BOS_2026.html`)**
  - Verify all rolling charts (Synergy, Win%, Turnaround Momentum, Streak Timeline) use numeric **Game Number (1..162)** on the X-axis.
  - Verify Active Starting Rotation Game Scores and Active Bullpen Workload heatmaps.
- [ ] **Audit Page 4: Team Stat Leaders (`/leaders` / `docs/leaders_BOS_2026.html`)**
  - Verify top-5 leaderboards for hitting and pitching (HR, RBI, OPS, AVG, SB, SO, ERA, WHIP, W, SV) accurately reflect active Red Sox players.
- [ ] **Audit Page 5: Win Streak Records (`/streak_records` / `docs/streak_records_BOS_2026.html`)**
  - Check the 15-game win streak interactive timeline, game scores, and historical comparison charts.
- [ ] **Audit Pages 6-8: Betting & Models (`/tonights_board`, `/models`, `/method`)**
  - Verify line movements, edge calculations, strikeout prop models, First-5 starter cards, and NRFI/YRFI tracking.
- [ ] **Audit Backend & Database API (`backend/main.py`, `backend/api/routes.py`)**
  - Verify all REST endpoints (`/healthz`, `/api/v1/games`, `/api/v1/standings`, `/api/v1/bets`, `/api/v1/analytics/turnaround`, `/api/v1/analytics/matchup/today`).
  - Verify Neon PostgreSQL sync and SQLAlchemy migrations.

### Phase 2: Improvement Planning & Execution
1. **Dynamic HTML Generation**: Auto-generate `docs/index.html` from templates or FastAPI Jinja2 views to prevent static drift.
2. **Automated Cache Refresh & Uptime**: Enhance background scheduler / webhook endpoint in FastAPI for on-demand cache refresh after completed games.
3. **Advanced Statcast & Savant Integrations**: Overlay exit velocity, barrel %, and hard-hit % on active batting/pitching leaderboards.
4. **Enhanced Mobile UX**: Optimize touch tooltips, card spacing, and table scroll indicators across small viewports.
