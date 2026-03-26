"""
Roster management.

Fetches the active roster from the MLB Stats API, enriches it with
position group labels, and caches it as a parquet file.

Position groups
---------------
  SP  — starting pitcher
  RP  — relief pitcher
  C   — catcher
  IF  — infielder (1B, 2B, 3B, SS)
  OF  — outfielder (LF, CF, RF)
  DH  — designated hitter / utility
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from client.mlb_client import MLBClient
from data.schema import ROSTER_SCHEMA, enforce_schema
from config import CACHE_DIR

log = logging.getLogger(__name__)

# Position abbreviation → group
_POSITION_GROUP: dict[str, str] = {
    "SP": "SP", "P": "SP",
    "RP": "RP", "MR": "RP", "CL": "RP",
    "C":  "C",
    "1B": "IF", "2B": "IF", "3B": "IF", "SS": "IF",
    "LF": "OF", "CF": "OF", "RF": "OF", "OF": "OF",
    "DH": "DH", "PH": "DH", "PR": "DH",
    "TWP": "SP",  # two-way player
}


def _cache_path(team_id: int, season: int) -> Path:
    return CACHE_DIR / f"roster_{team_id}_{season}.parquet"


def fetch_roster(
    team_id: int,
    season: int,
    client: MLBClient | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Return the active roster as a DataFrame matching ROSTER_SCHEMA.

    Results are cached; pass force_refresh=True to re-fetch from the API.
    """
    cache = _cache_path(team_id, season)
    if cache.exists() and not force_refresh:
        log.info("Loading roster from cache: %s", cache)
        return pd.read_parquet(cache)

    client = client or MLBClient()
    log.info("Fetching roster for team %d season %d", team_id, season)

    raw_roster = client.get_roster(team_id, season)
    rows: list[dict] = []

    for entry in raw_roster:
        person = entry.get("person", {})
        pos    = entry.get("position", {})
        status = entry.get("status", {})

        pid  = person.get("id")
        pname = person.get("fullName", "")

        # Fetch additional bio details
        try:
            info = client.get_player_info(pid)
        except Exception:
            info = {}

        pos_abbr  = pos.get("abbreviation", "")
        pos_group = _POSITION_GROUP.get(pos_abbr, "DH")

        dob = info.get("birthDate", "")
        age = _calc_age(dob) if dob else None

        rows.append({
            "player_id":      pid,
            "player_name":    pname,
            "team_id":        team_id,
            "season":         season,
            "jersey_number":  entry.get("jerseyNumber", ""),
            "position":       pos_abbr,
            "position_group": pos_group,
            "bats":           info.get("batSide", {}).get("code", ""),
            "throws":         info.get("pitchHand", {}).get("code", ""),
            "age":            age,
            "status":         status.get("description", "Active"),
        })

    df = pd.DataFrame(rows)
    df = enforce_schema(df, ROSTER_SCHEMA)
    df.to_parquet(cache, index=False)
    log.info("Cached roster (%d players) → %s", len(df), cache)
    return df


def get_position_group(df_roster: pd.DataFrame, group: str) -> pd.DataFrame:
    """Filter roster to a position group: 'SP', 'RP', 'C', 'IF', 'OF', 'DH'."""
    return df_roster[df_roster["position_group"] == group].copy()


def player_id_map(df_roster: pd.DataFrame) -> dict[int, str]:
    """Return {player_id: player_name} dict for quick lookups."""
    return dict(zip(df_roster["player_id"], df_roster["player_name"]))


def _calc_age(dob_str: str) -> int | None:
    try:
        dob = date.fromisoformat(dob_str)
        today = date.today()
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    except (ValueError, AttributeError):
        return None
