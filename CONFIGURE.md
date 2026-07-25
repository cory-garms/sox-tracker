# Configuring for Your Team

This tracker defaults to the **Boston Red Sox**, but works for any MLB team.
Two lines in `config.py` control everything.

## Step 1 — Find your team

Run:
```bash
python fetch.py --list-teams
```

Or look up your team below:

| Abbr | ID  | Name                    | Lg | Div     |
|------|-----|-------------------------|----|---------|
| BAL  | 110 | Baltimore Orioles       | AL | East    |
| BOS  | 111 | Boston Red Sox          | AL | East    |
| NYY  | 147 | New York Yankees        | AL | East    |
| TB   | 139 | Tampa Bay Rays          | AL | East    |
| TOR  | 141 | Toronto Blue Jays       | AL | East    |
| CWS  | 145 | Chicago White Sox       | AL | Central |
| CLE  | 114 | Cleveland Guardians     | AL | Central |
| DET  | 116 | Detroit Tigers          | AL | Central |
| KC   | 118 | Kansas City Royals      | AL | Central |
| MIN  | 142 | Minnesota Twins         | AL | Central |
| HOU  | 117 | Houston Astros          | AL | West    |
| LAA  | 108 | Los Angeles Angels      | AL | West    |
| OAK  | 133 | Oakland Athletics       | AL | West    |
| SEA  | 136 | Seattle Mariners        | AL | West    |
| TEX  | 140 | Texas Rangers           | AL | West    |
| ATL  | 144 | Atlanta Braves          | NL | East    |
| MIA  | 146 | Miami Marlins           | NL | East    |
| NYM  | 121 | New York Mets           | NL | East    |
| PHI  | 143 | Philadelphia Phillies   | NL | East    |
| WSH  | 120 | Washington Nationals    | NL | East    |
| CHC  | 112 | Chicago Cubs            | NL | Central |
| CIN  | 113 | Cincinnati Reds         | NL | Central |
| MIL  | 158 | Milwaukee Brewers       | NL | Central |
| PIT  | 134 | Pittsburgh Pirates      | NL | Central |
| STL  | 138 | St. Louis Cardinals     | NL | Central |
| ARI  | 109 | Arizona Diamondbacks    | NL | West    |
| COL  | 115 | Colorado Rockies        | NL | West    |
| LAD  | 119 | Los Angeles Dodgers     | NL | West    |
| SD   | 135 | San Diego Padres        | NL | West    |
| SF   | 137 | San Francisco Giants    | NL | West    |

## Step 2 — Edit config.py

Open `config.py` and change these three lines:

```python
TEAM_ID:   int = 147        # ← your team's ID
TEAM_ABBR: str = "NYY"      # ← your team's abbreviation
TEAM_NAME: str = "New York Yankees"
```

Also update `RIVAL_IDS` to your division rivals if desired.

## Step 3 — Fetch data

```bash
python fetch.py              # uses config.py defaults
# or pass flags directly without editing config:
python fetch.py --team NYY --season 2026
```

## Step 4 — Run the dashboard

```bash
python report.py
```

That's it.  All analysis, charts, and reports will reflect your chosen team.

> **Note:** `streak_report.py` still hardcodes Red Sox franchise records and has
> no `--team` flag. Every other report is team-agnostic.

---

## Optional — live sportsbook lines

The betting report works without any key: it shows model projections and
reports the line as unavailable. To compute a real edge and EV it needs actual
book prices.

DraftKings' public endpoints are **not** usable — they sit behind an Akamai edge
that returns `403` to non-browser clients on every host and API version. Live
lines therefore come from [The Odds API](https://the-odds-api.com/), which
aggregates DraftKings prices and has a free tier (~500 requests/month).

```bash
# 1. Get a free key at https://the-odds-api.com/
# 2. Put it in .env (gitignored — never commit it)
echo 'ODDS_API_KEY=your_key_here' > .env

# 3. Build the betting page — it will now show real lines
python betting_report.py --team BOS --season 2026

# 4. Confirm the pipeline works and check your quota
python scripts/verify_odds.py
```

`config.py` loads `.env` with `python-dotenv` using `override=False`, so a real
environment variable always beats the file. That ordering matters: CI passes the
key in the environment, and a stale local `.env` must never shadow it.

For the GitHub Action, add the same value as a repository secret named
`ODDS_API_KEY` (Settings → Secrets and variables → Actions).

### Which markets the free tier returns

**Player props are available on the free tier** — an earlier version of this
document claimed they were paid-only, which is wrong. Verified against a live
event on 2026-07-25:

| Market | Status |
| :--- | :--- |
| `pitcher_strikeouts`, `pitcher_outs`, `pitcher_hits_allowed` | ✅ |
| `pitcher_walks`, `pitcher_earned_runs`, `pitcher_strikeouts_alternate` | ✅ |
| `batter_total_bases` | ✅ |
| `pitcher_record_a_win` | supported; no lines posted when probed |
| `pitcher_saves` | ❌ not a market on The Odds API |

Quota is ~500 requests/month. `get_events()` is free; each build costs one
credit per prop market requested. The betting page prices two markets —
`pitcher_strikeouts` and `batter_total_bases` — so a build costs 2 credits, and
the four scheduled builds a day come to ~240/month. Count the cost before adding
a third market. Without a key, or if the quota runs out, the report degrades to
projections-only and says so rather than inventing a line.

Every build's lines are appended to `data/cache/odds_history.parquet`
(`data/odds_history.py`), which is what lets the page report line movement. The
workflow commits that file; if you build locally with a key, expect it to change.
