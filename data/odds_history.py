"""
A memory for the odds page.

The site rebuilds four times a day and, until now, threw the previous snapshot
away every time. Sonny Gray's strikeout price moved from -137 to -154 inside a
single afternoon and the page had no idea, because nothing was ever written
down. This module keeps every build's lines in one parquet file so the page can
say what the market did, not just where it stands.

Two things become possible once the file has some depth in it:

  * line movement — "opened 4.5 (-137), now 4.5 (-154)" — which needs no model
    at all and is one of the few genuinely informative public betting signals;
  * closing line value, the only honest scoreboard for a projection, since
    results are far noisier than the line's own drift.

Design notes:

  * append-only, one row per (build, event, market, player). Nothing is ever
    rewritten, so a bad build can be identified and excluded rather than having
    silently corrupted history.
  * a re-run of the same build is idempotent: rows identical on
    (captured_at, event_id, market, player) replace nothing and add nothing.
  * failures never propagate. Losing a snapshot is a shame; failing the whole
    page build over it is worse.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

import config

log = logging.getLogger(__name__)

HISTORY_PATH: Path = config.CACHE_DIR / "odds_history.parquet"

# The columns every row carries, in order. `captured_at` is when *we* looked;
# `last_update` is when the *book* says it last moved the price. They answer
# different questions and the file keeps both.
COLUMNS = [
    "captured_at", "event_id", "commence_time", "home_team", "away_team",
    "market", "player", "line", "over_odds", "under_odds", "book", "last_update",
]

KEY = ["captured_at", "event_id", "market", "player"]


def snapshot_rows(
    event: dict[str, Any] | None,
    market: str,
    lines: dict[str, dict[str, Any]],
    captured_at: str | None = None,
) -> list[dict[str, Any]]:
    """
    Flatten one market's parsed lines into history rows.

    Returns [] for an empty market, so a build that got no props logs nothing
    rather than logging that nothing existed.
    """
    if not event or not lines:
        return []

    stamp = captured_at or datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for player, entry in lines.items():
        if entry.get("line") is None:
            continue
        rows.append({
            "captured_at": stamp,
            "event_id": str(event.get("id", "")),
            "commence_time": event.get("commence_time"),
            "home_team": event.get("home_team"),
            "away_team": event.get("away_team"),
            "market": market,
            "player": player,
            "line": float(entry["line"]),
            "over_odds": _as_int(entry.get("over_odds")),
            "under_odds": _as_int(entry.get("under_odds")),
            "book": entry.get("book"),
            "last_update": entry.get("last_update"),
        })
    return rows


def append_snapshot(rows: list[dict[str, Any]], path: Path = HISTORY_PATH) -> int:
    """
    Append rows to the history file, returning how many were actually new.

    Never raises: a page build must not fail because a log file could not be
    written. It logs the problem and returns 0.
    """
    if not rows:
        return 0
    try:
        frame = pd.DataFrame(rows).reindex(columns=COLUMNS)
        existing = load_history(path)
        if not existing.empty:
            combined = pd.concat([existing, frame], ignore_index=True)
        else:
            combined = frame
        before = len(combined)
        combined = combined.drop_duplicates(subset=KEY, keep="first")
        added = len(combined) - len(existing)
        if added <= 0:
            log.info("Odds history unchanged (%d duplicate rows dropped)",
                     before - len(combined))
            return 0
        path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_parquet(path, index=False)
        log.info("Odds history: +%d rows (%d total) -> %s", added, len(combined), path)
        return added
    except Exception as e:                          # disk full, parquet engine, ...
        log.warning("Could not write odds history to %s: %s", path, e)
        return 0


def load_history(path: Path = HISTORY_PATH) -> pd.DataFrame:
    """The whole history, or an empty frame with the right columns if there is none."""
    if not Path(path).exists():
        return pd.DataFrame(columns=COLUMNS)
    try:
        return pd.read_parquet(path).reindex(columns=COLUMNS)
    except Exception as e:
        log.warning("Could not read odds history at %s: %s", path, e)
        return pd.DataFrame(columns=COLUMNS)


def line_movement(
    history: pd.DataFrame,
    event_id: str,
    market: str,
    player: str,
) -> dict[str, Any] | None:
    """
    How this player's line has moved for this event, first snapshot to last.

    Returns None when there is nothing to say — no history, or a single
    snapshot, which is what every player looks like on the day this file is
    created. `moved` distinguishes "we have watched it and it has not moved"
    from "we have not watched it", which are different facts and the page
    phrases them differently.

    Scoped to one event_id on purpose: a line for tomorrow's game is not a later
    observation of today's.
    """
    if history.empty:
        return None
    rows = history[(history["event_id"] == str(event_id))
                   & (history["market"] == market)
                   & (history["player"] == player)]
    if rows.empty:
        return None

    rows = rows.sort_values("captured_at")
    first, last = rows.iloc[0], rows.iloc[-1]
    if len(rows) < 2:
        return None

    return {
        "snapshots": len(rows),
        "opened_at": first["captured_at"],
        "opened_line": _as_float(first["line"]),
        "opened_over_odds": _as_int(first["over_odds"]),
        "current_at": last["captured_at"],
        "current_line": _as_float(last["line"]),
        "current_over_odds": _as_int(last["over_odds"]),
        "moved": bool(first["line"] != last["line"]
                      or first["over_odds"] != last["over_odds"]),
    }


def _as_int(value: Any) -> int | None:
    try:
        if value is None or pd.isna(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
