"""
Central configuration for the MLB team tracker.

To track a different team, change TEAM_ID and TEAM_ABBR below.
See TEAMS for the full 30-team reference.
"""

from __future__ import annotations
from pathlib import Path

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
OUTPUT_DIR = ROOT_DIR / "output"

CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# API settings
# ---------------------------------------------------------------------------
MLB_API_BASE    = "https://statsapi.mlb.com/api/v1"
SAVANT_BASE     = "https://baseballsavant.mlb.com"
REQUEST_TIMEOUT = 30       # seconds
REQUEST_DELAY   = 0.25     # seconds between API calls (be polite)
