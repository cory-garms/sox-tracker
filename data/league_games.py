"""
League-wide game results, cached — every team's runs, game by game.

The win-probability baseline needs both sides' runs scored and allowed. Those
are on the standings endpoint for today, and today is the one date a backtest
must not use: scoring an April game with August's standings leaks four months
of results into the projection. It is the same failure
`scripts/backfill_predictions.py` guards against by truncating its inputs, and
it fails the same way — silently, with numbers that still compute and a model
that looks far better than it is.

So results are stored per game and totalled *as of* a date instead. One
league-wide schedule call covers the season — around 2,000 games — because
`/schedule` drops the team filter when no teamId is sent.

Follows data/league_pitching.py: refetch when stale, fall back to the cached
copy when that fails, never raise into a page build.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

import config
from client.mlb_client import MLBClient
from data import cache_freshness

log = logging.getLogger(__name__)

COLUMNS = [
    "game_pk", "game_date", "home_team_id", "away_team_id",
    "home_score", "away_score",
]

# A game is only a result once it is genuinely over. detailedState is the field
# to trust: a postponed game keeps abstractGameState "Final", which is why
# data/fetcher.py and scripts/postgame_check.py both key on the detailed one.
FINAL_STATES = {"Final", "Completed Early", "Game Over"}


def cache_path(season: int) -> Path:
    return config.CACHE_DIR / f"league_games_{season}.parquet"


def fetch_league_games(client: MLBClient, season: int = config.SEASON) -> pd.DataFrame:
    """Every completed regular-season game in the league, with its score."""
    games = client.get_schedule(
        team_id=None, season=season,
        start_date=f"{season}-01-01", end_date=f"{season}-12-31",
        hydrate="linescore",
    )
    rows = []
    for g in games:
        if (g.get("status", {}) or {}).get("detailedState") not in FINAL_STATES:
            continue
        teams = g.get("teams", {}) or {}
        home, away = teams.get("home", {}) or {}, teams.get("away", {}) or {}
        hid = (home.get("team", {}) or {}).get("id")
        aid = (away.get("team", {}) or {}).get("id")
        hs, as_ = home.get("score"), away.get("score")
        if hid is None or aid is None or hs is None or as_ is None:
            continue
        rows.append({
            "game_pk": g.get("gamePk"),
            "game_date": g.get("officialDate") or g.get("gameDate", "")[:10],
            "home_team_id": int(hid), "away_team_id": int(aid),
            "home_score": int(hs), "away_score": int(as_),
        })
    return pd.DataFrame(rows, columns=COLUMNS)


def load_league_games(
    season: int = config.SEASON,
    client: MLBClient | None = None,
    force_refresh: bool = False,
    max_age_hours: float = cache_freshness.DEFAULT_MAX_AGE_HOURS,
) -> pd.DataFrame:
    """Cached league results; an empty frame rather than an exception."""
    path = cache_path(season)
    stale = cache_freshness.is_stale(path, max_age_hours)
    cached = None
    if path.exists() and not force_refresh:
        try:
            cached = pd.read_parquet(path)
        except Exception as e:
            log.warning("Could not read %s: %s", path, e)
        if cached is not None and not stale:
            return cached
    if client is None:
        return cached if cached is not None else pd.DataFrame(columns=COLUMNS)
    try:
        frame = fetch_league_games(client, season)
    except Exception as e:
        log.warning("Refresh of %s failed (%s); using the cached copy", path.name, e)
        return cached if cached is not None else pd.DataFrame(columns=COLUMNS)
    if frame.empty:
        return cached if cached is not None else frame
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    log.info("Cached %d league games -> %s", len(frame), path)
    return frame


def team_runs_before(
    games: pd.DataFrame, team_id: int, before: str | None = None
) -> tuple[float, float, int]:
    """
    (runs scored, runs allowed, games played) for one team, before a date.

    `before` is exclusive, and that is the entire point: a projection for a
    given day may use the games played up to it and not the day itself. Passing
    None totals the whole frame, which is right for a live projection and wrong
    for every replayed one.
    """
    if games is None or games.empty:
        return 0.0, 0.0, 0
    df = games
    if before:
        df = df[df["game_date"].astype(str) < str(before)]
    if df.empty:
        return 0.0, 0.0, 0

    home = df[df["home_team_id"] == int(team_id)]
    away = df[df["away_team_id"] == int(team_id)]
    scored = float(home["home_score"].sum() + away["away_score"].sum())
    allowed = float(home["away_score"].sum() + away["home_score"].sum())
    return scored, allowed, int(len(home) + len(away))
