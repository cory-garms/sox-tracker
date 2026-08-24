"""
Central configuration for the MLB team tracker.

To track a different team, change TEAM_ID and TEAM_ABBR below.
See TEAMS for the full 30-team reference.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# .env loading
# ---------------------------------------------------------------------------
# Python does not read .env files on its own, so a key sitting in .env is
# invisible to os.environ without this.
#
# override=False (the default) is the property that matters: a real environment
# variable always wins over the file. CI passes ODDS_API_KEY in the environment,
# and a stale local .env must never shadow it.
load_dotenv(Path(__file__).parent / ".env", override=False)


# ---------------------------------------------------------------------------
# Primary team — change these two values to follow any team
# ---------------------------------------------------------------------------
TEAM_ID: int = 111          # 111 = Boston Red Sox
TEAM_ABBR: str = "BOS"
TEAM_NAME: str = "Boston Red Sox"

# Current season
SEASON: int = 2026

# Rivals to track head-to-head records against (defaults to AL East)
RIVAL_IDS: list[int] = [147, 139, 141, 142]  # NYY, TB, TOR, BAL

# Historical range for multi-season comparisons
HISTORY_START: int = 2000

# ---------------------------------------------------------------------------
# All 30 MLB teams — ID, abbreviation, full name, league, division
# ---------------------------------------------------------------------------
TEAMS: dict[str, dict] = {
    # American League East
    "BAL": {"id": 110, "name": "Baltimore Orioles",      "league": "AL", "division": "East"},
    "BOS": {"id": 111, "name": "Boston Red Sox",         "league": "AL", "division": "East"},
    "NYY": {"id": 147, "name": "New York Yankees",       "league": "AL", "division": "East"},
    "TB":  {"id": 139, "name": "Tampa Bay Rays",         "league": "AL", "division": "East"},
    "TOR": {"id": 141, "name": "Toronto Blue Jays",      "league": "AL", "division": "East"},
    # American League Central
    "CWS": {"id": 145, "name": "Chicago White Sox",      "league": "AL", "division": "Central"},
    "CLE": {"id": 114, "name": "Cleveland Guardians",    "league": "AL", "division": "Central"},
    "DET": {"id": 116, "name": "Detroit Tigers",         "league": "AL", "division": "Central"},
    "KC":  {"id": 118, "name": "Kansas City Royals",     "league": "AL", "division": "Central"},
    "MIN": {"id": 142, "name": "Minnesota Twins",        "league": "AL", "division": "Central"},
    # American League West
    "HOU": {"id": 117, "name": "Houston Astros",         "league": "AL", "division": "West"},
    "LAA": {"id": 108, "name": "Los Angeles Angels",     "league": "AL", "division": "West"},
    "OAK": {"id": 133, "name": "Oakland Athletics",      "league": "AL", "division": "West"},
    "SEA": {"id": 136, "name": "Seattle Mariners",       "league": "AL", "division": "West"},
    "TEX": {"id": 140, "name": "Texas Rangers",          "league": "AL", "division": "West"},
    # National League East
    "ATL": {"id": 144, "name": "Atlanta Braves",         "league": "NL", "division": "East"},
    "MIA": {"id": 146, "name": "Miami Marlins",          "league": "NL", "division": "East"},
    "NYM": {"id": 121, "name": "New York Mets",          "league": "NL", "division": "East"},
    "PHI": {"id": 143, "name": "Philadelphia Phillies",  "league": "NL", "division": "East"},
    "WSH": {"id": 120, "name": "Washington Nationals",   "league": "NL", "division": "East"},
    # National League Central
    "CHC": {"id": 112, "name": "Chicago Cubs",           "league": "NL", "division": "Central"},
    "CIN": {"id": 113, "name": "Cincinnati Reds",        "league": "NL", "division": "Central"},
    "MIL": {"id": 158, "name": "Milwaukee Brewers",      "league": "NL", "division": "Central"},
    "PIT": {"id": 134, "name": "Pittsburgh Pirates",     "league": "NL", "division": "Central"},
    "STL": {"id": 138, "name": "St. Louis Cardinals",    "league": "NL", "division": "Central"},
    # National League West
    "ARI": {"id": 109, "name": "Arizona Diamondbacks",   "league": "NL", "division": "West"},
    "COL": {"id": 115, "name": "Colorado Rockies",       "league": "NL", "division": "West"},
    "LAD": {"id": 119, "name": "Los Angeles Dodgers",    "league": "NL", "division": "West"},
    "SD":  {"id": 135, "name": "San Diego Padres",       "league": "NL", "division": "West"},
    "SF":  {"id": 137, "name": "San Francisco Giants",   "league": "NL", "division": "West"},
}

# ---------------------------------------------------------------------------
# File system paths
# ---------------------------------------------------------------------------
ROOT_DIR   = Path(__file__).parent
CACHE_DIR  = ROOT_DIR / "data" / "cache"
OUTPUT_DIR = ROOT_DIR / "docs"

CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# API settings
# ---------------------------------------------------------------------------
MLB_API_BASE    = "https://statsapi.mlb.com/api/v1"
SAVANT_BASE     = "https://baseballsavant.mlb.com"
REQUEST_TIMEOUT = 30       # seconds
REQUEST_DELAY   = 0.25     # seconds between API calls (be polite)

# ---------------------------------------------------------------------------
# Database & Backend Settings (dirtywater.corygarms.com)
# ---------------------------------------------------------------------------
# Defaults to SQLite in data/cache/ for local development and offline tests.
# In production on Render, Render supplies DATABASE_URL (postgresql://...).
_RAW_DB_URL = os.environ.get(
    "DATABASE_URL", f"sqlite:///{CACHE_DIR / 'dirtywater.db'}"
)
# SQLAlchemy requires postgresql:// instead of legacy postgres://
if _RAW_DB_URL.startswith("postgres://"):
    _RAW_DB_URL = _RAW_DB_URL.replace("postgres://", "postgresql://", 1)

DATABASE_URL: str = _RAW_DB_URL

# ---------------------------------------------------------------------------
# Sportsbook odds (optional)
# ---------------------------------------------------------------------------
# Live betting lines require a free key from https://the-odds-api.com/.
# Export it rather than committing it:  export ODDS_API_KEY="..."
# Without a key the betting report still builds — it shows model projections
# and reports the line as unavailable instead of inventing one.
ODDS_API_KEY: str = os.environ.get("ODDS_API_KEY", "")
ODDS_BOOKMAKER: str = "draftkings"   # which book's prices to pull via the aggregator

# ---------------------------------------------------------------------------
# Refresh webhook (optional)
# ---------------------------------------------------------------------------
# Shared secret for POST /api/v1/refresh, which re-ingests the cache and
# rebuilds the reports after a game goes final.
#
# Unset means the route is *disabled*, not open: an ingest endpoint that
# anybody can POST to is a way to burn the odds quota and hammer the MLB API
# from outside. The route returns 503 until a token is configured.
REFRESH_TOKEN: str = os.environ.get("REFRESH_TOKEN", "")


# ---------------------------------------------------------------------------
# Which build is actually serving (deploy staleness)
# ---------------------------------------------------------------------------
# On 2026-08-23 a build failed and Render kept serving the previous one. The
# site returned 200s the whole time and simply stopped updating; it was found
# by accident a day later. Nothing in the repo could have detected it, because
# every check ran against the repo rather than against the running site.
#
# Render injects RENDER_GIT_COMMIT into the service environment. Empty locally,
# which is why /healthz reports it as unknown rather than pretending.
DEPLOY_COMMIT: str = (
    os.environ.get("RENDER_GIT_COMMIT")
    or os.environ.get("GIT_COMMIT")
    or ""
)

# ---------------------------------------------------------------------------
# Analytics (optional)
# ---------------------------------------------------------------------------
# Unset means no tag is emitted and the pages make no external request at all,
# which is the default and keeps the standalone-offline convention intact for
# local files and the Pages mirror.
#
# Deliberately provider-agnostic and cookieless. GoatCounter and Plausible both
# fit a single script tag with a data attribute; neither needs a consent banner
# because neither sets a cookie or tracks across sites.
#
#   ANALYTICS_SRC="https://gc.zgo.at/count.js"
#   ANALYTICS_SITE="https://dirtywater.goatcounter.com/count"
# Defaults are the account already in use. This was hardcoded into five report
# files, which is the five-way duplication viz/theme.py exists to prevent -- and
# betting_BOS_2026.html was the page that got missed. Set ANALYTICS_SRC="" to
# emit no tag at all and make the pages fully offline again.
ANALYTICS_SRC: str = os.environ.get("ANALYTICS_SRC", "https://gc.zgo.at/count.js")
ANALYTICS_SITE: str = os.environ.get(
    "ANALYTICS_SITE", "https://cory-garms.goatcounter.com/count"
)
