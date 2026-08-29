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
from typing import Any
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
    commence_time: str | None = None,
    starts: dict | None = None,
) -> tuple[pd.Series | None, str]:
    """
    Find the one appearance a prediction is about.

    Returns (row, reason). A None row with a reason is a deliberate refusal.

    **Doubleheaders are the trap.** A prop is per game, not per date, so summing
    both ends of 2026-07-22 would invent a player who batted nine times. A
    starting pitcher appears once on a doubleheader date, so he resolves
    cleanly; a position player can appear in both.

    This used to refuse that case, because "the cache carries no first-pitch
    time to match the odds event's commence_time against". It does now:
    `starts` maps game_pk to UTC first pitch, and every archived prediction
    carries the commence_time of the event it was quoted on. Given both, the
    right end of a doubleheader is the one starting nearest that time, which is
    a match rather than a guess -- the two ends of 2026-08-29 are six hours
    apart, and no plausible clock error spans that.

    Without both it still refuses and says why, which is the case for every
    caller that has not been given `starts` and for any date whose games were
    cached before first pitch was stored. A smaller honest sample beats a
    larger corrupt one.
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
        # Before concluding he did not play, check that the game this row is
        # about is one we know of at all. The rollover bug files some rows under
        # the following day's date -- their game was played, just not on the
        # date written on them -- and settling those DNP is terminal and wrong.
        if commence_time and starts and not _any_game_near(commence_time, starts):
            return None, "no appearance in the game this prediction is about"
        return None, "player did not appear"

    # Every appearance found here is on the right *date*. That is not the same
    # as the right *game*, and on a doubleheader the difference is the whole
    # problem -- including when only one end has been played, which is the case
    # this originally got wrong. A prediction about the nightcap found the
    # opener's box score sitting alone on the date, matched it because there was
    # nothing to be ambiguous with, and was settled hours before its game began:
    # 36 rows took the opener's totals and 53 more were settled "did not appear"
    # for a game that had not started.
    #
    # So the game is checked before the count is. Both feeds carry a scheduled
    # first pitch and they agree to within a minute, while the two ends of a
    # doubleheader are hours apart, so a wide tolerance still separates them.
    candidates = len(mine)
    mine = _played_in_the_right_game(mine, commence_time, starts)
    if mine.empty:
        # Deliberately not "player did not appear", which is terminal: he may
        # yet appear in the game this row is about, which has not been played.
        return None, "no appearance in the game this prediction is about"

    if len(mine) == 1 and candidates == 1:
        return mine.iloc[0], "ok"
    if len(mine) == 1:
        # Ambiguity resolved by exclusion rather than by choosing. Trust it only
        # when the survivor's own first pitch is known; otherwise this is the
        # nearest-of-what-we-know guess the tie rule below refuses.
        pk = mine.iloc[0].get("game_pk")
        if starts and not pd.isna(pd.to_datetime(
                (starts or {}).get(pk), utc=True, errors="coerce")):
            return mine.iloc[0], "ok"
        return None, f"ambiguous: {candidates} games on a doubleheader date"

    distinct_games = mine["game_pk"].nunique() if "game_pk" in mine.columns else len(mine)
    if distinct_games == 1:
        return mine.iloc[0], "ok"

    nearest = _nearest_by_first_pitch(mine, commence_time, starts)
    if nearest is not None:
        return nearest, "ok"

    return None, f"ambiguous: {distinct_games} games on a doubleheader date"


# How far apart two scheduled first pitches may be and still be the same game.
# Both feeds publish a *scheduled* start, not an actual one, so a rain delay
# does not move either and they agree to within a minute in practice. The
# closest doubleheader this has to separate is a traditional one, whose halves
# are still hours apart.
SAME_GAME_TOLERANCE_S = 2 * 60 * 60


def _any_game_near(commence_time: str, starts: dict) -> bool:
    """Is any game we know about scheduled within tolerance of this quote?"""
    target = pd.to_datetime(commence_time, utc=True, errors="coerce")
    if pd.isna(target):
        return True                       # unparseable cannot convict a row
    for raw in (starts or {}).values():
        start = pd.to_datetime(raw, utc=True, errors="coerce")
        if pd.isna(start):
            continue
        if abs((start - target).total_seconds()) <= SAME_GAME_TOLERANCE_S:
            return True
    return False


def _played_in_the_right_game(
    candidates: pd.DataFrame,
    commence_time: str | None,
    starts: dict | None,
) -> pd.DataFrame | None:
    """
    Narrow appearances to the game this prediction was actually about.

    Returns the surviving rows, or None when the question cannot be answered --
    no commence_time, no start times, or no game_pk to join on -- in which case
    the caller keeps its previous behaviour rather than refusing every date.
    Filtering to an empty frame is a real answer: the player did not appear in
    *this* game, whatever he did in the other one.
    """
    if not commence_time or not starts or "game_pk" not in candidates.columns:
        return candidates

    target = pd.to_datetime(commence_time, utc=True, errors="coerce")
    if pd.isna(target):
        return candidates

    keep = []
    for _, row in candidates.iterrows():
        start = pd.to_datetime(starts.get(row["game_pk"]), utc=True, errors="coerce")
        if pd.isna(start):
            # An unknown start cannot convict a row. Losing a real appearance is
            # worse than keeping a doubtful one, and the nearest-first-pitch
            # check below still has to choose between whatever survives.
            keep.append(True)
            continue
        keep.append(abs((start - target).total_seconds()) <= SAME_GAME_TOLERANCE_S)

    return candidates[pd.Series(keep, index=candidates.index)]


def _nearest_by_first_pitch(
    candidates: pd.DataFrame,
    commence_time: str | None,
    starts: dict | None,
) -> pd.Series | None:
    """
    The appearance whose game started closest to `commence_time`.

    Returns None unless the match is unambiguous, and the bar is deliberately
    high: every candidate must have a known first pitch, and one must be
    strictly nearer than the rest. A tie means two games are equidistant from
    the quoted first pitch, which is not a doubleheader we understand, and
    guessing there is the behaviour this replaced.
    """
    if not commence_time or not starts or "game_pk" not in candidates.columns:
        return None

    target = pd.to_datetime(commence_time, utc=True, errors="coerce")
    if pd.isna(target):
        return None

    gaps: list[float] = []
    for pk in candidates["game_pk"]:
        start = pd.to_datetime(starts.get(pk), utc=True, errors="coerce")
        if pd.isna(start):
            return None                     # one unknown start poisons the match
        gaps.append(abs((start - target).total_seconds()))

    best = min(gaps)
    if gaps.count(best) != 1:
        return None
    return candidates.iloc[gaps.index(best)]


def grade_frame(
    predictions: pd.DataFrame,
    pitching: pd.DataFrame,
    batting: pd.DataFrame,
    now: str | None = None,
    boxscore_lookup: Any = None,
    starts: dict | None = None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """
    Settle every ungraded prediction that can be settled.

    Returns the whole frame with outcomes filled in, plus a tally of what
    happened. A prediction for tonight's game is left exactly as it was and
    simply waits for tonight to finish.

    `boxscore_lookup` is an optional callable
    ``(game_date, player_id, player_name, market, commence_time)
    -> (actual, game_pk) | None``
    consulted only when the team caches cannot resolve a player. It exists for
    the opposing starter: those caches hold Boston and nobody else, so Tyler
    Phillips on 2026-08-25 -- the first opposing-starter projection ever logged
    -- resolved as "player did not appear" and could never settle, while his
    line sat in a box score the whole time. Injected rather than imported so
    the tests never touch a network.

    A player genuinely absent from a game that *was* played is settled as
    OUTCOME_DNP rather than left blank. Blank means "ask again next run", and
    for a bench bat that is every run until the season ends.

    `starts` maps game_pk to UTC first pitch and is what lets a doubleheader
    resolve at all; omit it and those dates go on being refused, which is what
    every caller got before it existed.
    """
    stats = {"graded": 0, "skipped": 0, "already": 0, "dnp": 0, "boxscore": 0}
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
            commence_time=row.get("commence_time"), starts=starts,
        )

        actual = None
        game_pk = None
        if appearance is not None:
            actual = measure(appearance)
            game_pk = appearance.get("game_pk") if "game_pk" in appearance else None
        elif reason == "player did not appear" and boxscore_lookup is not None:
            # Not in our caches, which hold one team. He may still have played.
            try:
                found = boxscore_lookup(
                    row.get("game_date"), row.get("player_id"),
                    row.get("player"), market, row.get("commence_time"),
                )
            except Exception as e:                    # a box score is not worth a crash
                log.warning("Box score lookup failed for %s on %s: %s",
                            row.get("player"), row.get("game_date"), e)
                found = None
            if found is not None:
                actual, game_pk = found
                stats["boxscore"] += 1

        if actual is None:
            # "did not appear" is terminal only once we have also failed to find
            # him anywhere else; every other reason -- no game yet, an
            # unresolvable doubleheader -- means try again another day.
            if reason == "player did not appear":
                frame.loc[idx, "outcome"] = ph.OUTCOME_DNP
                frame.loc[idx, "settled_at"] = stamp
                stats["dnp"] += 1
            else:
                log.debug("Not grading %s %s on %s: %s",
                          market, row.get("player"), row.get("game_date"), reason)
                stats["skipped"] += 1
            continue
        # settle() returns "" when there was no line to classify against. That
        # row is still settled — the actual is known and measures projection
        # error — so it gets an explicit no_line outcome rather than staying
        # blank and returning to the ungraded queue on every future run.
        outcome = ph.settle(actual, row.get("line")) or ph.OUTCOME_NO_LINE

        frame.loc[idx, "actual"] = float(actual)
        frame.loc[idx, "outcome"] = outcome
        frame.loc[idx, "settled_at"] = stamp
        if game_pk is not None and not pd.isna(game_pk):
            frame.loc[idx, "game_pk"] = game_pk
        stats["graded"] += 1

    return frame, stats


def _n(value) -> float:
    if value is None or pd.isna(value):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
