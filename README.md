# ⚾ Boston Red Sox MLB Analytics Suite (`sox_tracker`)

A full-stack Python analytics platform and interactive web application for tracking MLB team and player performance — season records, pre-game matchups, win streaks, team stat leaderboards, prop projections, and historical trends.

Authored by **Cory Garms** ([@cory-garms](https://github.com/cory-garms)).

- **Live Production App**: **[dirtywater.corygarms.com](https://dirtywater.corygarms.com)** / **[dirtywater-app.onrender.com](https://dirtywater-app.onrender.com)**
- **GitHub Pages Mirror**: **[cory-garms.github.io/sox-tracker](https://cory-garms.github.io/sox-tracker/)**

---

## 🌐 Interactive Web Suite

Mobile-first, vintage-ballpark HTML dashboards powered by FastAPI backend and GitHub Actions automation. The suite is organized with a **Stats-First** philosophy:

| Page | Description | Route / File | Live Link |
| :--- | :--- | :--- | :--- |
| 🏠 **Suite Landing Index** | Stats-first landing page guiding to Matchup & Dashboard | `/` (`docs/index.html`) | [View Landing](https://dirtywater.corygarms.com/) |
| ⚾ **Today's Matchup Preview** | Probable starter metrics, platoon advantages, active bullpen 3-day rest, head-to-head history | `/matchup` | [View Matchup](https://dirtywater.corygarms.com/matchup) |
| 📊 **Main Season Dashboard** | Season turnaround momentum, Game-Number rolling synergy, rolling win%, run differential, active rotation game scores, active bullpen load | `/dashboard` | [View Dashboard](https://dirtywater.corygarms.com/dashboard) |
| 🥇 **Team Stat Leaders** | Top-5 leaderboards in HR, RBI, OPS, AVG, SB, SO, ERA, WHIP, W, SV for active roster | `/leaders` | [View Stat Leaders](https://dirtywater.corygarms.com/leaders) |
| 🏆 **The 15-Game Win Streak** | Tribute to the July 3–22, 2026 run that tied the franchise record, measured against Franchise (15 W), AL (22 W), and MLB (26 W) marks | `/streak_records` | [View Streak Report](https://dirtywater.corygarms.com/streak_records) |
| 🎲 **Tonight's Board** | Biggest line moves, logged positions against the close, market consensus pricing | `/tonights_board` | [View Board](https://dirtywater.corygarms.com/tonights_board) |
| 🔬 **Models & Method** | Strikeout and total-bases models with measured error bars, First-5 starter cards, NRFI/YRFI tracking | `/models` | [View Models](https://dirtywater.corygarms.com/models) |
| 📚 **How This Works** | Every methodological note the board carries — collected automatically at build time | `/method` | [View Method](https://dirtywater.corygarms.com/method) |

---

## ✨ Design

- **Vintage Fenway aesthetic** — Green Monster slat headers, ticket-stub cards with aged-brass dashed borders and corner notches, manual-scoreboard number plates, and `EST. 1912 · FENWAY PARK` stamps. Typography is `Alfa Slab One` (headlines), `Graduate` (stencil labels), and `Share Tech Mono` (scoreboard numerals).
- **One source of truth** — every colour, font, and shared style lives in [`viz/theme.py`](viz/theme.py). Change styling there, not in the individual exporters.
- **Validated chart palette** — the categorical chart colours are checked against OKLCH lightness/chroma bands, Machado colour-vision-deficiency separation, a normal-vision floor, and WCAG contrast on the dark surface. Hues are assigned in fixed order and never cycled; ordered categories use a single-hue ramp instead. See the table in [HANDOFF_GUIDE.md](HANDOFF_GUIDE.md#-3-fenway-redesign--done).
- **Mobile first** — the suite is read mostly on phones. Charts are responsive, wide tables scroll horizontally with a sticky first column, and every change is verified at ~390px width.

---

## ⚡ Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Fetch data (Boston Red Sox, 2026 season)
python fetch.py --team BOS --season 2026 --refresh

# 3. Print terminal dashboard
python report.py

# 4. Print terminal pre-game matchup preview
python matchup.py

# 5. Build all HTML web dashboards for GitHub Pages
python viz_report.py     --team BOS --season 2026
python leaders_report.py --team BOS --season 2026
python matchup_report.py --team BOS --season 2026
python betting_report.py --team BOS --season 2026
python streak_report.py     # betting_report.py emits three pages: board, models, method
```

### Betting workflow

```bash
# log a bet - stake 0 is a paper bet and grades identically
python scripts/log_bet.py --selection "Athletics" --market h2h --side Moneyline \
    --price +158 --stake 1 --promo boost_50

# capture the closing line (free outside the window; ~4 credits inside it)
python scripts/capture_close.py

# grade against the close and report closing line value
python scripts/log_bet.py --grade
python scripts/log_bet.py --summary
```

### Measurement scripts

| Script | What it measures |
| :--- | :--- |
| `scripts/backtest_league_k.py` | Walk-forward strikeout error across every league starter; **sets `MODEL_ERROR_K`** and compares the model against Marcel and simpler baselines |
| `scripts/backtest_pitcher_k.py` | The same test on one team only — a sanity check, far too small (~80 starts) to set a constant from |
| `scripts/backtest_batter_tb.py` | Total-bases error bar |
| `scripts/measure_early_win_lift.py` | Value of an "up 2 runs" early-win token |
| `scripts/merge_odds_history.py` | Lossless union of two odds-history files |
| `scripts/verify_odds.py` | End-to-end odds pipeline check |

> **Constants like `MODEL_ERROR_K` are outputs of these scripts, never settings.**
> Lowering one by hand to make the page recommend something defeats the only
> mechanism keeping it honest.

---

## 🎲 Live Sportsbook Lines (optional)

The betting page builds without any API key — it shows model projections and reports the line as unavailable. It never invents a line in order to display an "edge".

To compute real edge you need actual book prices. Put the key in a `.env` file in
the repo root — it is gitignored, and `config.py` loads it with `python-dotenv`:

```bash
echo 'ODDS_API_KEY=your_key_here' > .env   # free key: https://the-odds-api.com/
python betting_report.py --team BOS --season 2026
```

An exported environment variable works too, and always wins over `.env`, so a
stale local file can never shadow the secret CI passes in.

Check the pipeline end to end at any time with `python scripts/verify_odds.py`,
which reports which markets your key actually returns and your remaining quota.

> DraftKings' public sportsbook endpoints are **not** usable programmatically — they sit behind an Akamai edge returning `403` to non-browser clients on every host and API version. Live lines come from The Odds API, which aggregates DraftKings prices. Full details in [CONFIGURE.md](CONFIGURE.md#optional--live-sportsbook-lines).

---

## 🏗️ Repository Structure

```
sox_tracker/
├── config.py              # Team ID, season, paths, ODDS_API_KEY
├── fetch.py               # CLI: fetch & cache parquet data
├── report.py              # CLI: rich terminal dashboard
├── matchup.py             # CLI: terminal pre-game matchup preview
├── viz_report.py          # CLI: builds docs/dashboard_BOS_2026.html
├── leaders_report.py      # CLI: builds docs/leaders_BOS_2026.html
├── matchup_report.py      # CLI: builds docs/matchup_BOS_2026.html
├── streak_report.py       # CLI: builds docs/streak_records_BOS_2026.html
├── betting_report.py      # CLI: builds docs/betting_BOS_2026.html
├── CONFIGURE.md           # Switching teams; odds API setup
├── HANDOFF_GUIDE.md       # Current state, design rules, known gaps
├── roadmap.md             # Sports betting & prop model feature roadmap
├── docs/                  # GitHub Pages output folder
├── tests/                 # Offline pytest suite (no network, ~0.4s)
├── scripts/
│   └── verify_odds.py     # Diagnoses the live odds pipeline & quota
├── client/
│   ├── mlb_client.py          # MLB Stats API wrapper
│   ├── savant_client.py       # Baseball Savant / Statcast
│   ├── odds_api_client.py     # The Odds API — live sportsbook lines
│   ├── odds_math.py           # Odds conversion & de-vig (pure functions)
│   └── draftkings_client.py   # Dormant — endpoints return 403
├── data/
│   ├── schema.py          # DataFrame schemas
│   ├── roster.py          # Active roster fetcher
│   ├── fetcher.py         # Multi-table parquet cache orchestrator
│   └── cache/             # Auto-generated parquet cache
├── analysis/
│   ├── standings.py       # Season overview & pace
│   ├── offense.py         # Batting leaderboards & platoon splits
│   ├── pitching.py        # Rotation & bullpen metrics
│   ├── defense.py         # Fielding %, OAA, catcher metrics
│   ├── streaks.py         # Win/loss streaks & game ordering
│   ├── matchup.py         # Pre-game matchup intelligence
│   ├── history.py         # Historical team comparisons
│   └── betting.py         # Prop models & +EV calculations
└── viz/
    ├── theme.py           # ★ Palette, fonts, Plotly base, page CSS
    ├── charts.py          # Plotly chart builders
    ├── dashboard.py       # HTML dashboard template builder
    └── exports.py         # Static file exporter
```

---

## ⚠️ Working With Game Data

**Never sort games by `game_pk`.** MLB assigns `gamePk` at scheduling time, so a rained-out game made up as game 1 of a later doubleheader carries a *lower* pk than the nightcap it precedes. Sorting by pk silently mis-orders doubleheaders and corrupts anything order-sensitive — streaks, cumulative curves, rolling averages.

Use `analysis.streaks.played_in_order(games)`, which sorts by `(game_date, game_number)` using MLB's own `gameNumber`.

---

## 🔮 Roadmap

See **[ODDS_PAGE_PLAN.md](ODDS_PAGE_PLAN.md)** for the prioritised plan for the
betting page, **[roadmap.md](roadmap.md)** for longer-term prop modelling ideas, and [HANDOFF_GUIDE.md §8](HANDOFF_GUIDE.md#-8-known-gaps--next-up) for known gaps. The strikeout model began calling sides on 2026-08-04, when re-measuring its error across all 2,347 league starts (rather than 73 of Boston's) put it at **±0.45 K** and the recommendation band opened on its own. It still has **no park or platoon adjustment**, and the total-bases model's error bar remains wider than any edge it has found, so that table still declines to call a side.

---

## 📜 Switching Teams

See [CONFIGURE.md](CONFIGURE.md) — supports any MLB team abbreviation (e.g., `NYY`, `LAD`, `CHC`). Note that `streak_report.py` is still Red Sox–specific.
