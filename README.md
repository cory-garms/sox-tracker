# ⚾ Boston Red Sox MLB Analytics Suite (`sox_tracker`)

A Python suite and interactive GitHub Pages web application for tracking MLB team and player performance — season records, pre-game matchups, win streaks, team stat leaderboards, prop projections, and historical trends.

Authored by **Cory Garms** ([@cory-garms](https://github.com/cory-garms)).

Live Web Suite: **[cory-garms.github.io/sox-tracker](https://cory-garms.github.io/sox-tracker/)**

---

## 🌐 GitHub Pages Interactive Web Suite

Five mobile-first, vintage-ballpark HTML pages, rebuilt daily by GitHub Actions and tracked with GoatCounter analytics:

| Page | Description | CLI Exporter | Live Output |
| :--- | :--- | :--- | :--- |
| 🏠 **Suite Landing Index** | Responsive landing page linking to all dashboards | `docs/index.html` | [View Index](https://cory-garms.github.io/sox-tracker/) |
| ⚾ **Today's Matchup Preview** | Probable starter metrics, platoon advantages, bullpen 3-day rest, head-to-head history | `python matchup_report.py` | [View Preview](https://cory-garms.github.io/sox-tracker/matchup_BOS_2026.html) |
| 📊 **Main Season Dashboard** | Season timeline, 7/15-game rolling win%, run differential, rotation game scores, bullpen load | `python viz_report.py` | [View Dashboard](https://cory-garms.github.io/sox-tracker/dashboard_BOS_2026.html) |
| 🏆 **The 15-Game Win Streak** | Tribute to the July 3–22, 2026 run that tied the franchise record, measured against Franchise (15 W), AL (22 W), and MLB (26 W) marks | `python streak_report.py` | [View Streak Report](https://cory-garms.github.io/sox-tracker/streak_records_BOS_2026.html) |
| 🥇 **Team Stat Leaders** | Top-5 leaderboards in HR, RBI, OPS, AVG, SB, SO, ERA, WHIP, W, SV | `python leaders_report.py` | [View Stat Leaders](https://cory-garms.github.io/sox-tracker/leaders_BOS_2026.html) |
| 🎲 **Betting & Prop Intelligence** | Pitcher strikeout projections, batter total-bases and HR/RBI props, First-5 starter cards, NRFI/YRFI tracking | `python betting_report.py` | [View Betting Page](https://cory-garms.github.io/sox-tracker/betting_BOS_2026.html) |

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
python streak_report.py
```

---

## 🎲 Live Sportsbook Lines (optional)

The betting page builds without any API key — it shows model projections and reports the line as unavailable. It never invents a line in order to display an "edge".

To compute real edge and expected value you need actual book prices:

```bash
export ODDS_API_KEY="your_key_here"   # free key: https://the-odds-api.com/
python betting_report.py --team BOS --season 2026
```

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

See **[roadmap.md](roadmap.md)** for planned betting & prop modelling features, and [HANDOFF_GUIDE.md §8](HANDOFF_GUIDE.md#-8-known-gaps--next-up) for known gaps — the largest being that the project currently has **no test coverage**.

---

## 📜 Switching Teams

See [CONFIGURE.md](CONFIGURE.md) — supports any MLB team abbreviation (e.g., `NYY`, `LAD`, `CHC`). Note that `streak_report.py` is still Red Sox–specific.
