# ⚾ `sox_tracker` — Next Agent Handoff & Redesign Blueprint

> **Notice for Incoming Agent**: This document provides a complete overview of the `sox_tracker` repository state, machine migration context for the DraftKings API, and a detailed UI redesign blueprint to transition the site from a generic tech theme to a **vintage Fenway Park & Boston Red Sox aesthetic**.

---

## 🎯 1. Mission Overview & Current State

`sox_tracker` is a Python-based MLB analytics suite, interactive Plotly web dashboard generator, and sports betting intelligence model focusing on the **Boston Red Sox** (`TEAM_ID = 111`).

- **Repository**: `sox_tracker`
- **Primary Target**: Boston Red Sox (`BOS`)
- **Virtual Environment**: `.soxEnv` (Python 3.11+)
- **Key Output**: Interactive HTML reports generated in `docs/` and published to GitHub Pages.

---

## 💰 2. Machine Migration & DraftKings API Setup

The project is moving to a machine with uninhibited access to the **DraftKings Sportsbook REST API**.

### Relevant Code & Files
- [`client/draftkings_client.py`](file:///home/cgarms/Sandbox/sox_tracker/client/draftkings_client.py): Public DraftKings API client with odds conversion math (`american_to_implied_prob`, `american_to_decimal`, `calculate_ev`).
- [`betting_report.py`](file:///home/cgarms/Sandbox/sox_tracker/betting_report.py): Generates [`docs/betting_BOS_2026.html`](file:///home/cgarms/Sandbox/sox_tracker/docs/betting_BOS_2026.html).
- [`analysis/betting.py`](file:///home/cgarms/Sandbox/sox_tracker/analysis/betting.py): Strikeout O/U model, First 5 Innings (F5) starter analysis, NRFI/YRFI tracker, and Batter Total Bases props.

### Next Steps for DraftKings Integration
1. Verify API connectivity to `https://sportsbook-us-ma.draftkings.com/sites/US-MA-SB/api/v2`.
2. Ensure live line scraping matches MLB Event Group ID (`84240`).
3. Update `betting_report.py` to auto-fetch live DraftKings market lines and compute real-time +EV edges.

---

## 🎨 3. UI Redesign Blueprint: Vintage Fenway Park Aesthetic

### The Problem
The current UI ([`docs/index.html`](file:///home/cgarms/Sandbox/sox_tracker/docs/index.html)) uses default developer dark-mode variables (`#0e1117` GitHub dark background, `#161b22` cards, `#30363d` grid lines, `#58a6ff` neon blue, `-apple-system` sans-serif fonts). This gives it a generic, "AI-generated" tech template appearance.

### The Goal
Transform the design into a **vintage, historic broadsheet & ballpark experience** celebrating Fenway Park (Est. 1912) and the City of Boston.

### 🏛️ Ballpark Color Palette
Replace dark tech colors with this Fenway palette:

| Element | Hex Code | Visual Context |
| :--- | :--- | :--- |
| **Green Monster Dark** | `#00483A` | Primary card headers & Green Monster scoreboard slats |
| **Red Sox Midnight Navy** | `#0C2340` | Deep classic Red Sox navy |
| **Fenway Crimson Red** | `#BD3039` | Official Red Sox crimson red accents |
| **Scoreboard Yellow** | `#F3C010` | Manual scoreboard innings digits & gold highlights |
| **Parchment / Ticket Cream**| `#F6F1E3` | Aged ticket stock / scorecard panel background |
| **Press Box Dark Mode** | `#0E1714` | Deep night-game background tone |
| **Aged Brass Border** | `#C5A059` | Dashed card borders & dividers |

### 🔤 Typography Specs
Import Google Fonts into HTML files (`docs/*.html`) and Plotly exports (`viz/charts.py`):
1. **Headlines & Headers**: `'Alfa Slab One'` or `'Graduate'` / `'Playfair Display'` (bold slab-serif matching historic ballpark signage and classic Red Sox programs).
2. **Scoreboard Numbers & Odds**: `'Share Tech Mono'` or `'Courier Prime'` (monospace digits styled like manual wooden scoreboard number plates and vintage press typewriters).
3. **Body Text**: `'Georgia'` or serif font for classic broadsheet readability.

### 🎟️ Ballpark UI Components
1. **Green Monster Manual Scoreboard Header**:
   - Header styled like Fenway's iconic Green Monster wall: green wooden slats with subtle vertical divider lines, score numbers in manual yellow plates, and team abbreviations in white stencil font.
2. **Ticket Stub Cards**:
   - Card containers formatted as retro game ticket stubs: dashed aged-brass borders (`border: 2px dashed #C5A059`), subtle corner notch cutouts, and vintage serial stamps (e.g., `EST. 1912 • FENWAY PARK`).
3. **Scorecard & Broadside Layout**:
   - Replace modern neon badges with stamped leather/wax seal badges or stitched red seam borders.

### 📊 Plotly Theme Customization (`viz/charts.py`)
Update `_LAYOUT_BASE` in [`viz/charts.py`](file:///home/cgarms/Sandbox/sox_tracker/viz/charts.py):
```python
_BG       = "#0E1714"  # Deep Press Box Night
_PAPER_BG = "#152620"  # Green Monster Card
_GRID     = "#244035"  # Faint Turf Grid Line
_TEXT     = "#F6F1E3"  # Vintage Ticket Cream
_GREEN    = "#4E9F3D"  # Ballpark Outfield Green
_RED      = "#BD3039"  # Fenway Crimson
_YELLOW   = "#F3C010"  # Manual Scoreboard Yellow
_BLUE     = "#58A6FF"  # Secondary Accent
```

---

## 🏗️ 4. Repository Code Structure & Workflows

```
sox_tracker/
├── config.py              # Team ID (111), Season (2026), API URLs, path definitions
├── fetch.py               # Ingestion CLI (fetches MLB API & Savant into Parquet cache)
├── report.py              # Rich terminal dashboard CLI
├── viz_report.py          # Builds docs/dashboard_BOS_2026.html
├── betting_report.py      # Builds docs/betting_BOS_2026.html
├── client/
│   ├── mlb_client.py      # Rate-limited MLB Stats API wrapper
│   ├── savant_client.py   # Baseball Savant exit velocity & Statcast metrics
│   └── draftkings_client.py # DraftKings Sportsbook API wrapper & EV math
├── data/
│   ├── schema.py          # PyArrow schemas & type casting
│   ├── roster.py          # Active 26-man/40-man roster fetching
│   ├── fetcher.py         # Multi-table parquet cache orchestrator
│   └── cache/             # Parquet cache files (games_111_2026.parquet, etc.)
├── analysis/
│   ├── standings.py       # Win%, Pythagorean record, pace
│   ├── offense.py         # Leaderboards, lineups 1-9, platoon splits, hot/cold
│   ├── pitching.py        # Starter vs reliever splits, ERA, WHIP, K/9, Game Score
│   ├── defense.py         # Fielding %, errors, Statcast OAA
│   ├── streaks.py         # Win/loss streaks, series outcomes
│   ├── history.py         # Multi-season historical records (2000-present)
│   └── betting.py         # Prop models (+EV calculations, K's, TB, NRFI)
└── viz/
    ├── charts.py          # Plotly chart builders & styling constants
    ├── dashboard.py       # Main dashboard HTML layout builder
    └── exports.py         # Static export helpers
```

---

## 🚀 5. Useful CLI Execution Commands

```bash
# 1. Fetch latest data into parquet cache
python fetch.py --team BOS --season 2026

# 2. View terminal reports
python report.py
python leaders_report.py
python matchup_report.py
python streak_report.py

# 3. Generate HTML dashboards for GitHub Pages (docs/)
python viz_report.py --team BOS --season 2026
python betting_report.py --team BOS --season 2026
```

---

*Handoff document generated for `sox_tracker` migration.*
