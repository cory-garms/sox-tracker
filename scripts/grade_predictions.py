#!/usr/bin/env python3
"""
Settle published projections against what actually happened.

Reads data/cache/predictions_history.parquet, joins every ungraded row to the
actual result in the parquet cache, and writes the outcomes back.

Costs nothing: the actuals are already ingested, so this is a join. No MLB call,
no odds credit. Safe to run as often as you like — already-settled rows are left
alone.

Usage:
    python scripts/grade_predictions.py
    python scripts/grade_predictions.py --dry-run
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

import config  # noqa: E402
from analysis.grading import (  # noqa: E402
    MARKET_HR,
    MARKET_K,
    SAME_GAME_TOLERANCE_S,
    grade_frame,
)
from client.mlb_client import MLBClient  # noqa: E402
from data import predictions_history as ph  # noqa: E402
from data.fetcher import Fetcher  # noqa: E402

log = logging.getLogger(__name__)


def _nearest_end(on_date: "pd.DataFrame", commence_time: str | None):
    """
    The one game of a doubleheader that a prediction quoted at `commence_time`
    is about, or None when that cannot be told.

    Same bar as analysis.grading._nearest_by_first_pitch: every game needs a
    known first pitch and exactly one must be nearest. The two ends of
    2026-08-29 are six hours apart.
    """
    if not commence_time or "game_start" not in on_date.columns:
        # No way to tell the ends apart. One game is taken as before; two are
        # refused, which is where this started.
        return on_date if len(on_date) == 1 else None
    target = pd.to_datetime(commence_time, utc=True, errors="coerce")
    if pd.isna(target):
        return on_date if len(on_date) == 1 else None
    starts = pd.to_datetime(on_date["game_start"], utc=True, errors="coerce")
    if starts.isna().any():
        return on_date if len(on_date) == 1 else None

    gaps = (starts - target).abs()
    # The nearest game is only the right game if it is actually near. A
    # prediction about tonight's nightcap must not be settled against this
    # afternoon's opener merely because the opener is the only one cached.
    if gaps.min() > pd.Timedelta(seconds=SAME_GAME_TOLERANCE_S):
        return None
    if (gaps == gaps.min()).sum() != 1:
        return None
    return on_date.loc[[gaps.idxmin()]]


def make_boxscore_lookup(client, games: "pd.DataFrame"):
    """
    Resolve a player from the box score of the game he actually played in.

    The Fetcher caches hold one team, so an opposing starter has no row in them
    and grades as "player did not appear" forever. His line is in the box score
    of the same game -- one call, both teams -- so this looks him up there.

    Returns ``(actual, game_pk)`` or None. Box scores are fetched once per date
    and reused: a night's board is a dozen predictions about one game.

    Doubleheaders resolve by first pitch, exactly as resolve_appearance does.
    A prop is per game, so attributing a result to whichever end happened to be
    checked first would invent a number -- this used to refuse the date for
    want of a first-pitch time, and the games cache now carries one. A date
    with two games and no `game_start` is still refused.

    Keyed by (date, first pitch) rather than by date: on a doubleheader the two
    ends are different games and must not share a cached box score.
    """
    cache: dict[tuple, dict] = {}

    def _boxscore_for(game_date: str, commence_time: str | None = None):
        key = (str(game_date), str(commence_time or ""))
        if key in cache:
            return cache[key]
        on_date = games[games["game_date"].astype(str) == str(game_date)]
        if on_date.empty:                         # not played yet
            cache[key] = None
            return None
        # Checked even when the date holds one game. "One game on this date"
        # does not mean "the game this prediction is about": on 2026-08-29 the
        # opener was final and cached while the nightcap had not started, and an
        # unguarded lookup handed the nightcap's predictions the opener's box
        # score. See analysis.grading._played_in_the_right_game.
        on_date = _nearest_end(on_date, commence_time)
        if on_date is None:
            cache[key] = None
            return None
        pk = int(on_date.iloc[0]["game_pk"])
        try:
            box = client.get_boxscore(pk)
        except Exception as e:
            log.warning("Could not fetch box score %s: %s", pk, e)
            box = None
        cache[key] = (box, pk) if box else None
        return cache[key]

    def lookup(game_date, player_id, player_name, market, commence_time=None):
        if player_id is None or pd.isna(player_id):
            return None
        found = _boxscore_for(game_date, commence_time)
        if not found:
            return None
        box, pk = found
        key = f"ID{int(player_id)}"
        for side in ("home", "away"):
            player = (((box.get("teams", {}) or {}).get(side, {}) or {})
                      .get("players", {}) or {}).get(key)
            if not player:
                continue
            stats = player.get("stats", {}) or {}
            if market == MARKET_K:
                pitch = stats.get("pitching", {}) or {}
                if not pitch:
                    return None
                return float(pitch.get("strikeOuts", 0) or 0), pk
            bat = stats.get("batting", {}) or {}
            if not bat:
                return None
            if market == MARKET_HR:
                return float(bat.get("homeRuns", 0) or 0), pk
            hits = float(bat.get("hits", 0) or 0)
            doubles = float(bat.get("doubles", 0) or 0)
            triples = float(bat.get("triples", 0) or 0)
            hr = float(bat.get("homeRuns", 0) or 0)
            singles = hits - doubles - triples - hr
            return singles + 2 * doubles + 3 * triples + 4 * hr, pk
        return None

    return lookup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be settled without writing.")
    parser.add_argument("--team", default=config.TEAM_ABBR)
    parser.add_argument("--season", type=int, default=config.SEASON)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    team_id = config.TEAMS.get(args.team, {}).get("id", config.TEAM_ID)
    history = ph.load_history()
    if history.empty:
        log.info("No predictions logged yet — nothing to grade.")
        return 0

    fetcher = Fetcher(team_id=team_id, season=args.season)
    try:
        pitching = fetcher.load("pitching")
        batting = fetcher.load("batting")
    except FileNotFoundError as e:
        log.error("Cache not built: %s", e)
        return 1

    try:
        games = fetcher.load("games")
    except FileNotFoundError:
        games = pd.DataFrame(columns=["game_date", "game_pk"])
    lookup = make_boxscore_lookup(MLBClient(), games) if not games.empty else None

    # game_pk -> UTC first pitch, which is what lets a doubleheader date grade
    # instead of being refused. Empty for a cache written before game_start was
    # stored, and grading then behaves exactly as it did before.
    starts: dict = {}
    if not games.empty and "game_start" in games.columns:
        starts = {
            int(pk): str(start)
            for pk, start in zip(games["game_pk"], games["game_start"])
            if str(start)
        }

    graded, stats = grade_frame(
        history, pitching, batting, boxscore_lookup=lookup, starts=starts,
    )

    log.info(
        "%d newly settled (%d via box score), %d did not play, "
        "%d already settled, %d not settleable yet (of %d rows)",
        stats["graded"], stats.get("boxscore", 0), stats.get("dnp", 0),
        stats["already"], stats["skipped"], len(history),
    )

    if stats["graded"] == 0:
        return 0

    settled = ph.graded(graded)
    if not settled.empty:
        by_market = settled.groupby("market")["outcome"].value_counts()
        log.info("\nSettled to date:\n%s", by_market.to_string())

    if args.dry_run:
        log.info("\n--dry-run: nothing written.")
        return 0

    if not ph.write_history(graded):
        return 1
    log.info("Wrote %s", ph.HISTORY_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
