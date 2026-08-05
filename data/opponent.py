"""
League-wide team hitting logs, for opponent adjustments.

Why a game log and not a season total. The obvious way to ask "how much does
this lineup strike out" is one call for the opponent's season K%. That number
is fine for tonight, where every game in it has already happened, and it is
*leakage* in a backtest: projecting an April start with a rate that includes
August would let the model see its own future and would make the measured error
bar optimistic. Since the error bar is the only thing standing between this
repo and recommendations it cannot support, that is the expensive kind of wrong.

So the season is fetched once per team as a game log and the rate is
recomputed, locally, from only the games before whatever date is being asked
about. Thirty calls, cached to parquet, and every later question is free and
honest.
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

COLUMNS = ["team_id", "team_name", "game_date", "pa", "so"]

# Plate appearances of opponent history before the team's own K rate is trusted
# as much as the league's. Team K% is an aggregate of a whole lineup and settles
# quickly - a few hundred PA is already meaningful - but the first week of a
# season should not swing a projection, and this keeps early-April opponents
# pinned near league average instead of at whatever 60 PA happened to produce.
REGRESSION_PA = 600.0


def cache_path(season: int) -> Path:
    return config.CACHE_DIR / f"team_hitting_logs_{season}.parquet"


def fetch_team_hitting_logs(
    client: MLBClient, season: int, team_ids: list[int] | None = None
) -> pd.DataFrame:
    """One hitting game log per team. Thirty calls; callers should cache."""
    ids = team_ids or [t["id"] for t in config.TEAMS.values()]
    rows: list[dict[str, Any]] = []
    for team_id in ids:
        try:
            data = client._get(
                f"/teams/{team_id}/stats",
                {"stats": "gameLog", "group": "hitting",
                 "season": season, "sportId": 1},
            )
        except Exception as e:                       # one bad team must not kill the set
            log.warning("Could not fetch hitting log for team %s: %s", team_id, e)
            continue
        stats = data.get("stats") or []
        splits = stats[0].get("splits", []) if stats else []
        for split in splits:
            stat = split.get("stat") or {}
            pa = stat.get("plateAppearances")
            so = stat.get("strikeOuts")
            if pa in (None, 0) or so is None:
                continue
            rows.append({
                "team_id": int(split.get("team", {}).get("id", team_id)),
                "team_name": split.get("team", {}).get("name", ""),
                "game_date": split.get("date"),
                "pa": int(pa),
                "so": int(so),
            })
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    return pd.DataFrame(rows).reindex(columns=COLUMNS).sort_values(
        ["team_id", "game_date"]
    ).reset_index(drop=True)


def load_team_hitting_logs(
    season: int,
    client: MLBClient | None = None,
    force_refresh: bool = False,
    max_age_hours: float = cache_freshness.DEFAULT_MAX_AGE_HOURS,
) -> pd.DataFrame:
    """
    Cached league-wide hitting logs. Returns an empty frame rather than raising
    when the data cannot be had, because every consumer degrades to "no
    opponent adjustment" and a page must still build.

    Refetches when the cache is older than `max_age_hours`. It previously
    returned whatever was on disk forever, which had the opponent K factor
    running on six-day-old logs with no signal that anything was wrong. Pass
    `max_age_hours=0` to read the cache regardless of age - what a backtest of a
    finished season wants.
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
        # Stale beats nothing: the caller cannot refetch, and an empty frame
        # would silently drop the adjustment entirely.
        return cached if cached is not None else pd.DataFrame(columns=COLUMNS)
    try:
        frame = fetch_team_hitting_logs(client, season)
    except Exception as e:
        log.warning("Refresh of %s failed (%s); using the cached copy",
                    path.name, e)
        return cached if cached is not None else pd.DataFrame(columns=COLUMNS)
    if frame.empty:
        return cached if cached is not None else frame
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    log.info("Cached %d team-game hitting rows -> %s", len(frame), path)
    return frame


def league_k_rate(logs: pd.DataFrame, before: str | None = None) -> float | None:
    """League K per plate appearance, using only games before `before`."""
    if logs is None or logs.empty:
        return None
    frame = logs if before is None else logs[logs["game_date"] < str(before)]
    pa = float(frame["pa"].sum())
    return float(frame["so"].sum()) / pa if pa > 0 else None


def opponent_k_rate(
    logs: pd.DataFrame, team_id: int, before: str | None = None
) -> tuple[float | None, float]:
    """
    (K per plate appearance, plate appearances behind it) for one team, using
    only games strictly before `before`.

    Strictly before, not up to and including: a team's strikeouts in tonight's
    game are the very thing being projected, so including them would be
    circular in exactly the way the backtest exists to detect.
    """
    if logs is None or logs.empty:
        return None, 0.0
    frame = logs[logs["team_id"] == int(team_id)]
    if before is not None:
        frame = frame[frame["game_date"] < str(before)]
    pa = float(frame["pa"].sum())
    if pa <= 0:
        return None, 0.0
    return float(frame["so"].sum()) / pa, pa


def opponent_k_factor(
    logs: pd.DataFrame,
    team_id: int,
    before: str | None = None,
    regression_pa: float = REGRESSION_PA,
) -> float:
    """
    Multiplier on a pitcher's projected K/9 for who he is facing.

    1.0 means a league-average lineup and changes nothing. Above 1.0 is a
    lineup that strikes out more than average; below is one that strikes out
    less. The opponent's observed rate is regressed toward the league's by
    plate appearances so that a small sample cannot move a projection far:

        weight = pa / (pa + regression_pa)
        rate   = weight * opponent + (1 - weight) * league

    Returns exactly 1.0 whenever the data is missing or the league rate cannot
    be computed, so an outage degrades to the previous pitcher-only behaviour
    rather than to a wrong number.
    """
    league = league_k_rate(logs, before)
    if not league:
        return 1.0
    rate, pa = opponent_k_rate(logs, team_id, before)
    if rate is None or pa <= 0:
        return 1.0
    weight = pa / (pa + regression_pa)
    regressed = weight * rate + (1.0 - weight) * league
    return regressed / league
