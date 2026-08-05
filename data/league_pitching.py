"""
League-wide starting-pitcher game logs, so the backtest can actually measure.

Why this exists. `MODEL_ERROR_K` was measured over 73 held-out starts, which
gives a standard error of ±0.41 K on an estimate of 1.39 K. The 95% interval is
roughly 0.59 to 2.18: at that sample the error bar cannot distinguish 1.39 from
1.43, and an improvement has to be larger than ~0.8 K before the test can see
it. No realistic modelling change is that big, so every feature added to the
model was destined to measure as "no change" regardless of whether it worked.
That is exactly what happened to the opponent K-rate adjustment.

The fix is not a better model, it is a bigger sample - and it was always
available. `pitcher_strikeout_model` projects a starter from his own game log
and knows nothing about Boston, so it can be backtested on every starter in the
league. That is ~2,950 starts rather than 73, which takes the standard error to
about ±0.08 K and makes a 0.16 K improvement visible.

Cost: one leaderboard call to enumerate starters, then one game log each
(~200 calls, throttled). Cached to parquet; the MLB API is free.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

import config
from client.mlb_client import MLBClient
from data import cache_freshness

log = logging.getLogger(__name__)

COLUMNS = [
    "player_id", "player_name", "game_date", "game_pk", "team_id",
    "opponent_id", "ip_outs", "so", "bf", "is_start",
]

# Below this a pitcher's season is mostly relief work and his "starts" are
# openers. They add noise to a starter model without adding signal.
MIN_GAMES_STARTED = 5


def cache_path(season: int) -> Path:
    return config.CACHE_DIR / f"league_pitching_logs_{season}.parquet"


def _outs(stat: dict) -> int | None:
    """Innings pitched as outs. `ip` is baseball notation and must not be summed."""
    raw = stat.get("inningsPitched")
    if raw is None:
        return None
    try:
        whole, _, frac = str(raw).partition(".")
        return int(whole) * 3 + int(frac or 0)
    except ValueError:
        return None


def starter_ids(client: MLBClient, season: int,
                min_gs: int = MIN_GAMES_STARTED) -> list[tuple[int, str]]:
    """Every pitcher with at least `min_gs` starts. One API call."""
    data = client._get(
        "/stats",
        {"stats": "season", "group": "pitching", "season": season,
         "sportId": 1, "playerPool": "all", "limit": 2000},
    )
    stats = data.get("stats") or []
    splits = stats[0].get("splits", []) if stats else []
    out = []
    for split in splits:
        gs = int(split.get("stat", {}).get("gamesStarted", 0) or 0)
        if gs < min_gs:
            continue
        player = split.get("player") or {}
        if player.get("id"):
            out.append((int(player["id"]), player.get("fullName", "")))
    return out


def fetch_league_logs(client: MLBClient, season: int,
                      min_gs: int = MIN_GAMES_STARTED) -> pd.DataFrame:
    """Game log for every qualifying starter. Slow, cached by the caller."""
    rows: list[dict[str, Any]] = []
    pitchers = starter_ids(client, season, min_gs)
    log.info("Fetching game logs for %d starters (%d)", len(pitchers), season)
    for i, (pid, name) in enumerate(pitchers, 1):
        try:
            data = client._get(
                f"/people/{pid}/stats",
                {"stats": "gameLog", "group": "pitching",
                 "season": season, "sportId": 1},
            )
        except Exception as e:
            log.warning("game log failed for %s (%s): %s", name, pid, e)
            continue
        stats = data.get("stats") or []
        for split in (stats[0].get("splits", []) if stats else []):
            stat = split.get("stat") or {}
            outs = _outs(stat)
            if outs is None:
                continue
            rows.append({
                "player_id": pid,
                "player_name": name,
                "game_date": split.get("date"),
                "game_pk": (split.get("game") or {}).get("gamePk"),
                "team_id": (split.get("team") or {}).get("id"),
                "opponent_id": (split.get("opponent") or {}).get("id"),
                "ip_outs": outs,
                "so": int(stat.get("strikeOuts", 0) or 0),
                "bf": int(stat.get("battersFaced", 0) or 0),
                # gamesStarted is per-game here: 1 when he started it.
                "is_start": bool(int(stat.get("gamesStarted", 0) or 0)),
            })
        if i % 50 == 0:
            log.info("  %d/%d", i, len(pitchers))
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    return (pd.DataFrame(rows).reindex(columns=COLUMNS)
            .sort_values(["player_id", "game_date"]).reset_index(drop=True))


def load_league_logs(
    season: int,
    client: MLBClient | None = None,
    force_refresh: bool = False,
    max_age_hours: float = cache_freshness.DEFAULT_MAX_AGE_HOURS,
) -> pd.DataFrame:
    """
    Cached league-wide starter logs; empty frame rather than raising.

    Refetches when the cache is older than `max_age_hours`, and falls back to
    the stale copy if that fails - this feeds the league rate the live
    projection regresses toward, so a wrong-but-present number is worse than a
    slightly old one only if nobody is told. Pass `max_age_hours=0` to skip the
    check; a backtest of a finished season should not spend ~200 calls proving
    the season is over.
    """
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
        if cached is not None:
            log.info("%s is %.1fh old; refreshing", path.name,
                     cache_freshness.age_hours(path))
    if client is None:
        return cached if cached is not None else pd.DataFrame(columns=COLUMNS)
    try:
        frame = fetch_league_logs(client, season)
    except Exception as e:
        log.warning("Refresh of %s failed (%s); using the cached copy",
                    path.name, e)
        return cached if cached is not None else pd.DataFrame(columns=COLUMNS)
    if frame.empty:
        return cached if cached is not None else frame
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    log.info("Cached %d league pitching rows -> %s", len(frame), path)
    return frame


def league_k_per_9(logs: pd.DataFrame, before: str | None = None) -> float | None:
    """
    League strikeouts per nine innings among starters, from starts before
    `before`. This is the prior a Marcel-style baseline regresses toward, and
    like every other rate here it is bounded by date so a backtest cannot see
    its own future.
    """
    if logs is None or logs.empty:
        return None
    frame = logs[logs["is_start"]] if "is_start" in logs.columns else logs
    if before is not None:
        frame = frame[frame["game_date"] < str(before)]
    outs = float(frame["ip_outs"].sum())
    if outs <= 0:
        return None
    return float(frame["so"].sum()) * 27.0 / outs
