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
# 2. Export it (never commit it)
export ODDS_API_KEY="your_key_here"

# 3. Build the betting page — it will now show real lines, edge, and EV
python betting_report.py --team BOS --season 2026
```

For the GitHub Action, add the same value as a repository secret named
`ODDS_API_KEY` (Settings → Secrets and variables → Actions).

Note that **player prop markets** (pitcher strikeouts, batter total bases) are
gated to The Odds API's paid tiers. On the free tier, game-level markets work and
prop lines come back empty — the report degrades to projections-only rather than
inventing a line.
