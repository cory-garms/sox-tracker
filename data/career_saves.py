"""
The all-time saves leaderboard, cached.

A post about a reliever closing on a round number needs two things the season
caches cannot give it: his career total, and who else is up there. Neither is in
`pitching_111_2026` -- that file is this team, this season -- and `career_2026`
is hitters only.

Both come off one `/stats/leaders` call. The leaderboard is the whole point
rather than a decoration: "he would be the ninth man to 400" is exactly the kind
of sentence that rots, because the eight above him are not a fixed list. Kenley
Jansen and Craig Kimbrel are still adding to their totals, and a milestone post
that hardcodes the club is wrong the moment one of them moves. So the club is
counted from the same data every time the page builds.

Follows data/league_games.py: refetch when stale, fall back to the cached copy
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

COLUMNS = ["rank", "player_id", "player_name", "saves"]

# Deep enough to hold the 400 club with room under it, so a post can say both
# who is in and who the next man up is. The API caps a leaders call well above
# this; 30 is about two rounds of milestones.
LEADER_LIMIT = 30


def cache_path() -> Path:
    return config.CACHE_DIR / "career_saves_leaders.parquet"


def fetch_leaders(client: MLBClient, limit: int = LEADER_LIMIT) -> pd.DataFrame:
    """Career saves leaders, most first."""
    data = client._get(
        "/stats/leaders",
        {"leaderCategories": "saves", "statType": "career",
         "sportId": 1, "limit": limit},
    )
    rows = []
    for cat in data.get("leagueLeaders", []) or []:
        for entry in cat.get("leaders", []) or []:
            person = entry.get("person", {}) or {}
            try:
                saves = int(entry.get("value"))
            except (TypeError, ValueError):
                continue
            rows.append({
                "rank": int(entry.get("rank") or 0),
                "player_id": int(person.get("id") or 0),
                "player_name": str(person.get("fullName") or ""),
                "saves": saves,
            })
    if not rows:
        return pd.DataFrame(columns=COLUMNS)
    return (pd.DataFrame(rows)[COLUMNS]
            .drop_duplicates(subset="player_id")
            .sort_values("saves", ascending=False)
            .reset_index(drop=True))


def load_leaders(
    client: MLBClient | None = None,
    force_refresh: bool = False,
    max_age_hours: float = cache_freshness.DEFAULT_MAX_AGE_HOURS,
) -> pd.DataFrame:
    """Cached career saves leaders; an empty frame rather than an exception."""
    path = cache_path()
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
        frame = fetch_leaders(client)
    except Exception as e:                                  # noqa: BLE001
        log.warning("Refresh of %s failed (%s); using the cached copy", path.name, e)
        return cached if cached is not None else pd.DataFrame(columns=COLUMNS)
    if frame.empty:
        return cached if cached is not None else frame
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    log.info("Cached %d career saves leaders -> %s", len(frame), path)
    return frame


def club_at(leaders: pd.DataFrame, threshold: int) -> pd.DataFrame:
    """Everyone already past `threshold`, most saves first."""
    if leaders.empty:
        return leaders
    return leaders[leaders["saves"] >= threshold].sort_values(
        "saves", ascending=False
    ).reset_index(drop=True)


def nearest_milestone(saves: int, step: int = 50) -> int:
    """
    The round number this total is *about* -- the one nearest it, either side.

    `next_milestone` answers what a pitcher is chasing, which is the wrong
    question the day he arrives: at 400 saves it returns 450, and a post built
    on it announces a man is fifty away from a number nobody was discussing,
    on the evening he reached the one everybody was. Nearest keeps the
    achievement in view while it is still the story and hands over to the next
    one at the midpoint -- 400 through 424 is about 400, 425 is about 450.
    """
    step = int(step)
    below = (int(saves) // step) * step
    above = below + step
    return below if (saves - below) <= (above - saves) else above


def next_milestone(saves: int, step: int = 50) -> int:
    """
    The next round number above `saves`.

    Round means a multiple of `step`, and a total already sitting exactly on one
    is not "approaching" it -- 400 saves has arrived at 400 and is chasing 450.
    """
    return (int(saves) // step + 1) * step
