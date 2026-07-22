# MLB Team Tracker

A Python suite for tracking MLB team and player performance — season records,
streaks, offensive/defensive/pitching analytics, and historical trends.

Defaults to the **Boston Red Sox**. See [CONFIGURE.md](CONFIGURE.md) to switch teams.

---

## Features

- **Season overview**: W-L, run differential, Pythagorean record, pace projection
- **Standings**: Division standings with games-back and win% trend
- **Offense**: Batting leaderboard, hot/cold tracker, lineup slot analysis, platoon splits
- **Pitching**: Rotation stats + ERA trend, bullpen by role, usage load, FIP
- **Defense**: Fielding%, errors by position, catcher metrics, Statcast OAA
- **Streaks**: Win/loss streaks, hitting streaks, series results, monthly splits
- **History**: Multi-season W-L comparison, pace vs. championship seasons
- **Viz**: Interactive Plotly dashboard (HTML) + PNG exports for embeds

Data sources:
- [MLB Stats API](https://statsapi.mlb.com/api/v1/) — free, no auth required
- [Baseball Savant](https://baseballsavant.mlb.com) — Statcast metrics (exit velo, OAA, framing)

---

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Fetch data (Boston Red Sox, 2026 season)
python fetch.py

# 3. Print terminal dashboard
python report.py

# 4. Print pre-game matchup intelligence preview
python matchup.py

# 5. Print a specific section
python report.py --section offense
python report.py --section pitching
python report.py --section streaks

# 6. Fetch a different team/season
python fetch.py --team NYY --season 2025
python report.py --team NYY --season 2025
```

---

## Project Structure

```
sox_tracker/
├── config.py              # ← team selection lives here
├── fetch.py               # CLI: fetch + cache all data
├── report.py              # CLI: terminal dashboard
├── matchup.py             # CLI: pre-game matchup intelligence preview
├── matchup_report.py      # CLI: standalone interactive HTML matchup preview report
├── viz_report.py          # CLI: main HTML dashboard
├── streak_report.py       # CLI: standalone historical win streak report
├── leaders_report.py      # CLI: standalone team stat leaders report
├── CONFIGURE.md           # instructions for switching teams
├── .agents/
│   └── AGENTS.md          # Agent rules & execution directives
├── client/
│   ├── mlb_client.py      # MLB Stats API wrapper
│   └── savant_client.py   # Baseball Savant / Statcast
├── data/
│   ├── schema.py          # canonical DataFrame schemas
│   ├── roster.py          # roster management
│   ├── fetcher.py         # data orchestrator + cache
│   └── cache/             # auto-generated parquet cache
├── analysis/
│   ├── standings.py       # season record, standings, pace
│   ├── offense.py         # batting leaderboards, hot/cold
│   ├── pitching.py        # rotation + bullpen analytics
│   ├── defense.py         # fielding, OAA, catcher metrics
│   ├── streaks.py         # win/loss/hitting streaks, patterns
│   └── history.py         # multi-season historical trends
├── viz/
│   ├── charts.py          # individual Plotly chart functions
│   ├── dashboard.py       # combined HTML dashboard
│   └── exports.py         # PNG + HTML export helpers
└── notebooks/
    └── demo.ipynb         # interactive walkthrough
```

---

## Switching Teams

See [CONFIGURE.md](CONFIGURE.md) — it takes about 2 minutes.

---

## Requirements

- Python 3.11+
- See `requirements.txt`
- Optional: `kaleido` for PNG chart exports (`pip install kaleido`)
