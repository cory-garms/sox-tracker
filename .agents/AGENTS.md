# Project Rules & Agent Guidelines — MLB Team Tracker (`sox_tracker`)

> [!IMPORTANT]
> **Core Directive — Execution Constraints**:
> - **No Background Execution**: NEVER run terminal commands in the background or launch background tasks.
> - **No Timers / Schedules**: NEVER use background timers or schedule tools (`schedule`, `sleep` loops, etc.).
> - **Synchronous Foreground Execution Only**: Any terminal command must be executed in the foreground with explicit user confirmation/approval where required, waiting synchronously for completion.
> - **No Unrequested Code Runs**: Do not execute scripts or commands unless explicitly requested or approved by the user.

---

## 🚀 1. Project Overview & Environment

- **Repository**: `sox_tracker` (MLB Team Performance & Analytics Suite)
- **Primary Target**: Boston Red Sox (`TEAM_ID = 111`, `TEAM_ABBR = "BOS"`)
- **Virtual Environment**: `.soxEnv` (Python 3.11+)
- **Key Dependencies**: `pandas`, `pyarrow`, `rich`, `plotly`, `requests`, `tenacity`, `beautifulsoup4`

---

## 🏗️ 2. Repository Architecture & Component Responsibilities

```
sox_tracker/
├── config.py              # Configuration defaults (Team ID, season, paths, API bases)
├── fetch.py               # Data ingestion CLI (fetches from MLB API & Baseball Savant into cache)
├── report.py              # Rich terminal dashboard CLI
├── viz_report.py          # Interactive Plotly HTML dashboard & PNG export CLI
├── .agents/
│   └── AGENTS.md          # Agent rules, constraints, and repository guidance
├── client/
│   ├── mlb_client.py      # Rate-limited wrapper around statsapi.mlb.com/api/v1
│   └── savant_client.py   # Baseball Savant Statcast exit velocity & advanced metrics
├── data/
│   ├── schema.py          # PyArrow/Pandas DataFrame schemas & type casting
│   ├── roster.py          # Roster management & active 26-man/40-man fetching
│   ├── fetcher.py         # Multi-table parquet cache orchestrator
│   └── cache/             # Auto-generated parquet cache files
├── analysis/
│   ├── standings.py       # Season overview, win%, run diff, Pythagorean record, 162-game pace
│   ├── offense.py         # Leaderboards, lineup slots 1–9, platoon splits, hot/cold tracker
│   ├── pitching.py        # Rotation vs. bullpen, ERA, WHIP, FIP, K/9, BB/9, QS%
│   ├── defense.py         # Fielding %, error rates, Statcast OAA, catcher framing
│   ├── streaks.py         # Win/loss streaks, series outcomes, hitting streaks, monthly splits
│   └── history.py         # Multi-season historical records (2000–present) & pace comparisons
└── viz/
    ├── charts.py          # Plotly figure builders
    ├── dashboard.py       # Responsive HTML dashboard generator
    └── exports.py         # Static file exporter (HTML / PNG via Kaleido)
```

---

## 💾 3. Data Ingestion & Caching Conventions

1. **Parquet Caching Strategy**:
   - Data stored in `data/cache/` using Parquet format for fast loading and low disk footprint.
   - Cache keys strictly follow the naming scheme: `{table}_{team_id}_{season}.parquet` (e.g., `games_111_2026.parquet`).
2. **API Interaction & Throttling**:
   - All MLB Stats API calls must pass through `MLBClient` in `client/mlb_client.py`.
   - Maintain `REQUEST_DELAY` throttling (0.25s) and `tenacity` exponential backoff retries.
3. **Data Integrity & Safe Calculations**:
   - Standardize statistical formulas (e.g., OPS = OBP + SLG, BABIP = (H - HR) / (AB - SO - HR + SF)).
   - Prevent division-by-zero errors across all rate calculations by returning `0.0` or `NaN` appropriately.

---

## 📊 4. Analytical Standards & Metrics

- **Pythagorean Record**: Standard exponent is \(1.83\) for MLB.
- **Lineup Slot Analysis**: Group batting logs by `batting_order` (1–9).
- **Hot / Cold Classification**:
  - `🔥 HOT`: Last-7-game OPS is \(\ge +0.100\) above season OPS.
  - `🧊 COLD`: Last-7-game OPS is \(\le -0.100\) below season OPS.
- **Series Outcomes**: Group consecutive games against the same opponent into `Sweep`, `Split`, or `Series Loss`.

---

## 🎨 5. User Interface & Reporting Guidelines

- **Terminal Output**: Use `rich` Console, Tables, and Panels for clean presentation in `report.py`.
- **HTML Visualizations**: Plotly interactive charts built in `viz/charts.py` and styled cleanly in `viz/dashboard.py`.
- **Links & Markdown**: Always use GitHub-style Markdown links for file references (e.g., `[report.py](file:///path/to/report.py)`).
