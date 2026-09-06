"""
Season rate leaderboards for pitchers, cached.

A rate is meaningless without the field it sits in. "A 3.97 strikeout-to-walk
ratio" is a number; "seventeenth in baseball" is the sentence a reader wants,
and the only honest way to write it is to fetch the field and count.

The subtlety this module exists to make visible is qualification. MLB's rate
leaderboards require one inning per team game -- 143 by early September -- and
only fifty-odd pitchers clear that. A young starter on an innings limit is not
on the board at all, which reads as "not good enough" and means "has not thrown
enough". `rank_for` therefore answers where a value *would* slot, and the caller
is expected to say plainly that it is a projection onto the qualified field
rather than a standing in it.

Follows data/career_saves.py: refetch when stale, fall back to the cached copy
when that fails, never raise into a page build.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

import config
from client.mlb_client import MLBClient
from data import cache_freshness

log = logging.getLogger(__name__)

COLUMNS = ["rank", "player_id", "player_name", "value"]

KBB = "strikeoutWalkRatio"


def cache_path(season: int, category: str = KBB) -> Path:
    return config.CACHE_DIR / f"pitching_leaders_{category}_{season}.parquet"


def fetch_leaders(client: MLBClient, season: int, category: str = KBB,
                  limit: int = 200) -> pd.DataFrame:
    """Qualified leaders in one pitching rate, best first."""
    data = client._get(
        "/stats/leaders",
        {"leaderCategories": category, "statType": "season", "season": season,
         "sportId": 1, "limit": limit, "statGroup": "pitching"},
    )
    rows = []
    for cat in data.get("leagueLeaders", []) or []:
        for entry in cat.get("leaders", []) or []:
            person = entry.get("person", {}) or {}
            try:
                value = float(entry.get("value"))
            except (TypeError, ValueError):
                continue
            rows.append({
                "rank": int(entry.get("rank") or 0),
                "player_id": int(person.get("id") or 0),
                "player_name": str(person.get("fullName") or ""),
                "value": value,
            })
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    return (pd.DataFrame(rows)[COLUMNS]
            .drop_duplicates(subset="player_id")
            .sort_values("value", ascending=False)
            .reset_index(drop=True))


def load_leaders(season: int = config.SEASON, client: MLBClient | None = None,
                 category: str = KBB, force_refresh: bool = False,
                 max_age_hours: float = cache_freshness.DEFAULT_MAX_AGE_HOURS
                 ) -> pd.DataFrame:
    """Cached qualified leaders; an empty frame rather than an exception."""
    path = cache_path(season, category)
    stale = cache_freshness.is_stale(path, max_age_hours)
    cached = None
    if path.exists() and not force_refresh:
        try:
            cached = pd.read_parquet(path)
        except Exception as e:                              # noqa: BLE001
            log.warning("Could not read %s: %s", path, e)
        if cached is not None and not stale:
            return cached
    if client is None:
        return cached if cached is not None else pd.DataFrame(columns=COLUMNS)
    try:
        frame = fetch_leaders(client, season, category)
    except Exception as e:                                  # noqa: BLE001
        log.warning("Refresh of %s failed (%s); using the cached copy", path.name, e)
        return cached if cached is not None else pd.DataFrame(columns=COLUMNS)
    if frame.empty:
        return cached if cached is not None else frame
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    log.info("Cached %d %s leaders -> %s", len(frame), category, path)
    return frame


def rank_for(leaders: pd.DataFrame, value: float) -> tuple[int, int]:
    """
    Where `value` would sit in this field, and how large the field is.

    Returns (0, 0) on an empty board so a caller drops the claim rather than
    reporting a confident first place computed from nothing.
    """
    if leaders is None or leaders.empty:
        return 0, 0
    better = int((leaders["value"] > value).sum())
    return better + 1, len(leaders)
