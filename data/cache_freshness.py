"""
Whether a parquet cache is still worth reading.

Why this exists. Both league-wide caches were written as

    if path.exists() and not force_refresh:
        return pd.read_parquet(path)

which never looks at the file's age. That is fine for a season-long archive and
wrong for anything that feeds a live projection: on 2026-08-02 the opponent K
factor was found to have been running on team hitting logs last written
2026-07-27, six days and ~90 games stale, with nothing anywhere reporting it.
The page still built, the number still looked reasonable, and it was quietly
computed from the wrong denominator.

The rule here is that staleness must degrade loudly but never fatally: refetch
when the file is old, and if the refetch fails, return what is on disk with a
warning rather than raising. A stale opponent factor is much better than a page
that cannot build - but neither is acceptable *silently*.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

# Hours before a league-wide cache is considered stale. Twelve puts a rebuild
# inside every scheduled refresh window (07:00/12:00/15:00/17:30 ET) without
# refetching on every local run during an afternoon of work.
DEFAULT_MAX_AGE_HOURS = 12.0


def age_hours(path: Path) -> float:
    """Hours since `path` was last written; inf when it does not exist."""
    try:
        return (time.time() - path.stat().st_mtime) / 3600.0
    except OSError:
        return float("inf")


def is_stale(path: Path, max_age_hours: float = DEFAULT_MAX_AGE_HOURS) -> bool:
    """
    True when the cache should be refetched.

    `max_age_hours <= 0` disables the check, which is what a backtest wants: it
    reads a historical season that is not going to change, and should not spend
    ~200 API calls re-fetching it to prove that.
    """
    if max_age_hours <= 0:
        return False
    return age_hours(path) > max_age_hours
