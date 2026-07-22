# ⚾ Boston Red Sox MLB Analytics Suite (`sox_tracker`)

A Python suite and interactive GitHub Pages web application for tracking MLB team and player performance — season records, pre-game matchups, win streaks, team stat leaderboards, and historical trends.

Authored by **Cory Garms** ([@cory-garms](https://github.com/cory-garms)).

Live Web Suite: **[cory-garms.github.io/sox-tracker](https://cory-garms.github.io/sox-tracker/)**

---

## 🌐 GitHub Pages Interactive Web Suite

The suite builds four mobile-optimized, dark-themed HTML pages hosted live on GitHub Pages with GoatCounter analytics tracking:

| Page | Description | CLI Exporter | Live Output |
| :--- | :--- | :--- | :--- |
| 🏠 **Suite Landing Index** | Responsive landing page linking to all 4 dashboards | `docs/index.html` | [View Index](https://cory-garms.github.io/sox-tracker/) |
| ⚾ **Today's Matchup Preview** | Probable starter metrics, platoon advantages, bullpen 3-day rest, head-to-head history | `python matchup_report.py` | [View Preview](https://cory-garms.github.io/sox-tracker/matchup_BOS_2026.html) |
| 📊 **Main Season Dashboard** | Season timeline, 7/15-game rolling win%, run differential, rotation game scores, bullpen load | `python viz_report.py` | [View Dashboard](https://cory-garms.github.io/sox-tracker/dashboard_BOS_2026.html) |
| 🏆 **Historical Win Streak Records** | Franchise (15 W), AL (22 W), and MLB win streak milestone benchmark comparison | `python streak_report.py` | [View Streak Report](https://cory-garms.github.io/sox-tracker/streak_records_BOS_2026.html) |
| 🥇 **Team Stat Leaders** | Single-column vertical stack of Top-5 leaderboards in HR, RBI, OPS, AVG, SB, SO, ERA, WHIP, W, SV | `python leaders_report.py` | [View Stat Leaders](https://cory-garms.github.io/sox-tracker/leaders_BOS_2026.html) |

---

## ✨ Features & Design Highlights

- **Retro Red Sox Branding**: Retro Red Sox logo (`images/sox_retro_logo.png`) header across all web pages with Green Monster Green (`#00804c`) and Red Sox Crimson (`#d22d36`) accents.
- **Mobile-First UX**: Responsive containers (`clamp()`), fluid typography, and touch navigation buttons (`← Back to Suite Index`).
- **Horizontal Chart Legends**: Chart legends positioned horizontally below figures to maximize 100% horizontal plot area width and prevent squishing on smartphone displays.
- **Plotly Modebar Clearance**: Top margins (`t=65px`) and section title spacing (`margin-bottom: 24px`) prevent modebar icon overlap.
- **Privacy Analytics**: Integrated GoatCounter analytics tracking tag (`cory-garms.goatcounter.com`).

---

## ⚡ Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Fetch data (Boston Red Sox, 2026 season)
python fetch.py

# 3. Print terminal dashboard
python report.py

# 4. Print terminal pre-game matchup preview
python matchup.py

# 5. Build all HTML web dashboards for GitHub Pages
python matchup_report.py
python viz_report.py
python streak_report.py
python leaders_report.py
```

---

## 🏗️ Repository Structure

```
sox_tracker/
├── config.py              # Team ID, season, and paths
├── fetch.py               # CLI: fetch & cache parquet data
├── report.py              # CLI: rich terminal dashboard
├── matchup.py             # CLI: terminal pre-game matchup preview
├── matchup_report.py      # CLI: builds docs/matchup_BOS_2026.html
├── viz_report.py          # CLI: builds docs/dashboard_BOS_2026.html
├── streak_report.py       # CLI: builds docs/streak_records_BOS_2026.html
├── leaders_report.py      # CLI: builds docs/leaders_BOS_2026.html
├── CONFIGURE.md           # Instructions for switching teams
├── roadmap.md             # Sports betting & prop model feature roadmap
├── images/
│   └── sox_retro_logo.png # Vintage Boston Red Sox logo
├── docs/                  # GitHub Pages output folder
│   ├── index.html         # Suite landing index
│   ├── images/            # Static image assets for web deployment
│   ├── matchup_BOS_2026.html
│   ├── dashboard_BOS_2026.html
│   ├── streak_records_BOS_2026.html
│   └── leaders_BOS_2026.html
├── client/
│   ├── mlb_client.py      # MLB Stats API wrapper
│   └── savant_client.py   # Baseball Savant / Statcast
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
│   ├── streaks.py         # Win/loss streaks & game logs
│   ├── matchup.py         # Pre-game matchup intelligence
│   └── history.py         # Historical team comparisons
└── viz/
    ├── charts.py          # Plotly chart builders & dark theme
    ├── dashboard.py       # HTML dashboard template builder
    └── exports.py         # Static file exporter
```

---

## 🔮 Future Feature Roadmap

See **[roadmap.md](roadmap.md)** for planned sports betting & prop modeling features:
- Pitcher K Over/Under models vs. opposing lineup K-rates
- Batter pitch-type Statcast matchup matrix (e.g. OPS vs fastballs > 95mph)
- First 5 Innings (F5) Moneyline & Over/Under models
- NRFI / YRFI (No Run First Inning) trackers
- +EV (Positive Expected Value) odds edge calculator

---

## 📜 Switching Teams

See [CONFIGURE.md](CONFIGURE.md) — supports any MLB team abbreviation (e.g., `NYY`, `LAD`, `CHC`).
