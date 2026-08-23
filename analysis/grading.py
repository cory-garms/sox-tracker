"""
Join published projections to what actually happened.

This is the half of the loop that was missing. `grade_bets_from_snapshots`
scores *bets* against *closing lines* — that is CLV, and it answers "did I get a
good price?". It cannot answer "is the model right?", which needs the outcome.

Every actual is already in the parquet cache, so this is a join rather than an
ingest: strikeouts come from the pitching log, total bases are computed from the
batting log. No network, no odds quota.

Kept as a module rather than living inside the script so the page builder and
the tests can call it directly.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from data import predictions_history as ph

log = logging.getLogger(__name__)

MARKET_K = "pitcher_strikeouts"
MARKET_TB = "batter_total_bases"
MARKET_HR = "batter_home_runs"


def total_bases(row: pd.Series) -> float:
    """
    Total bases from a batting line.

    TB = 1B + 2·2B + 3·3B + 4·HR, and 1B = H − 2B − 3B − HR, which reduces to
    H + 2B + 2·3B + 3·HR. The cache carries `doubles` and `triples`, so this is
    exact rather than estimated from SLG.
    """
    h = _n(row.get("h"))
    doubles = _n(row.get("doubles"))
    triples = _n(row.get("triples"))
    hr = _n(row.get("hr"))
    return h + doubles + 2 * triples + 3 * hr


def resolve_appearance(
    logs: pd.DataFrame,
    player_id,
    player_name: str,
    game_date: str,
) -> tuple[pd.Series | None, str]:
    """
    Find the one appearance a prediction is about.

    Returns (row, reason). A None row with a reason is a deliberate refusal.

    **Doubleheaders are the trap.** A prop is per game, not per date, so summing
    both ends of 2026-07-22 would invent a player who batted nine times. A
    starting pitcher appears once on a doubleheader date, so he resolves
    cleanly; a position player can appear in both, and the cache carries no
    first-pitch time to match the odds event's commence_time against. Rather
    than attribute the result to a guessed game, this leaves the prediction
    ungraded and says why — a smaller honest sample beats a larger corrupt one.
    """
    if logs is None or logs.empty:
        return None, "no logs"

    on_date = logs[logs["game_date"].astype(str) == str(game_date)]
    if on_date.empty:
        return None, "no game on that date yet"

    if player_id is not None and not pd.isna(player_id) and "player_id" in on_date.columns:
        mine = on_date[on_date["player_id"] == int(player_id)]
    else:
        mine = on_date[on_date["player_name"].astype(str) == str(player_name)]

    if mine.empty:
        return None, "player did not appear"
    if len(mine) == 1:
        return mine.iloc[0], "ok"

    distinct_games = mine["game_pk"].nunique() if "game_pk" in mine.columns else len(mine)
    if distinct_games == 1:
        return mine.iloc[0], "ok"

    return None, f"ambiguous: {distinct_games} games on a doubleheader date"


def grade_frame(
    predictions: pd.DataFrame,
    pitching: pd.DataFrame,
    batting: pd.DataFrame,
    now: str | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """
    Settle every ungraded prediction that can be settled.

    Returns the whole frame with outcomes filled in, plus a tally of what
    happened. Rows that cannot be settled are left exactly as they were, so a
    prediction for tonight's game simply waits for tonight to finish.
    """
    stats = {"graded": 0, "skipped": 0, "already": 0}
    if predictions is None or predictions.empty:
        return predictions, stats

    frame = predictions.copy()
    stamp = now or datetime.now(timezone.utc).isoformat(timespec="seconds")

    pending = ph.ungraded(frame)
    stats["already"] = len(frame) - len(pending)

    for idx in pending.index:
        row = frame.loc[idx]
        market = str(row.get("market", ""))

        if market == MARKET_K:
            logs, measure = pitching, lambda r: _n(r.get("so"))
        elif market == MARKET_TB:
            logs, measure = batting, total_bases
        elif market == MARKET_HR:
            logs, measure = batting, lambda r: _n(r.get("hr"))
        else:
            stats["skipped"] += 1
            continue

        appearance, reason = resolve_appearance(
            logs, row.get("player_id"), row.get("player"), row.get("game_date"),
        )
        if appearance is None:
            log.debug("Not grading %s %s on %s: %s",
                      market, row.get("player"), row.get("game_date"), reason)
            stats["skipped"] += 1
            continue

        actual = measure(appearance)
        # settle() returns "" when there was no line to classify against. That
        # row is still settled — the actual is known and measures projection
        # error — so it gets an explicit no_line outcome rather than staying
        # blank and returning to the ungraded queue on every future run.
        outcome = ph.settle(actual, row.get("line")) or ph.OUTCOME_NO_LINE

        frame.loc[idx, "actual"] = float(actual)
        frame.loc[idx, "outcome"] = outcome
        frame.loc[idx, "settled_at"] = stamp
        if "game_pk" in appearance:
            frame.loc[idx, "game_pk"] = appearance["game_pk"]
        stats["graded"] += 1

    return frame, stats


def _n(value) -> float:
    if value is None or pd.isna(value):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
