#!/usr/bin/env python3
"""
Capture the closing line, by watching the clock instead of guessing at it.

Why this exists. Closing line value is the only rigorous way to measure a model
before risking anything on results, because results are far noisier than the
line's own drift. But CLV is only as good as the "close" it is measured against,
and the page's four daily builds are fixed points in UTC while first pitch is
not: the last scheduled build lands ~90 minutes before a 19:10 ET start and more
than four hours before a 21:40 ET one. A close observed four hours early is not
a close.

The fix rests on one fact about the provider: `get_events()` costs zero quota.
So this script can run as often as we like, read the real first-pitch time for
free, and spend credits *only* when the game is genuinely about to start. A
static cron cannot follow a start time that swings from 13:35 to 21:40 ET; a
free gate polled every twenty minutes can.

Cost: 0 credits on a tick outside the window, 3 on a tick inside it — so roughly
3 per game day rather than 3 per tick.

Usage:
    python scripts/capture_close.py                 # capture if inside the window
    python scripts/capture_close.py --window 40     # widen the window
    python scripts/capture_close.py --force         # ignore the clock (costs credits)
    python scripts/capture_close.py --dry-run       # report the decision only
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from analysis.betting import fetch_book_lines  # noqa: E402
from client.odds_api_client import (  # noqa: E402
    MARKET_H2H,
    MARKET_BATTER_TB,
    MARKET_PITCHER_KS,
    MARKET_TOTALS,
    OddsAPIClient,
    _parse_player_lines,
    parse_player_lines_by_book,
    parse_two_way_by_book,
)
from data import odds_history  # noqa: E402

log = logging.getLogger(__name__)

# Default window before first pitch, in minutes. The upper bound is how early a
# snapshot still counts as a "close"; the lower bound keeps the job from firing
# so late that a delayed runner captures in-play prices, which are a different
# market and would silently corrupt the record.
DEFAULT_WINDOW_MIN = 35
DEFAULT_FLOOR_MIN = 2

# Priced at the close only, so bets placed in them can be graded. Each costs one
# credit per capture (~1/day), against the 4 x 3 the page builds already spend.
EXTRA_CLOSING_MARKETS = ("batter_home_runs",)

# Game-level markets, captured at the close for the same reason and parsed
# differently: their two outcomes are Over/Under or team names rather than a
# player, so they go through parse_two_way_by_book.
#
# Totals are here rather than on every build because of the budget, and the
# choice is a real one. Four builds a day would cost ~124 credits a cycle,
# which does not fit against a 500 quota already spending ~454; the only way to
# fund it would be dropping the moneyline, and the moneyline is the sole market
# benchmark the win-probability model has. One capture per game at the close is
# ~30 a cycle and fits inside the slack.
#
# What that trades away is intraday movement on totals. What it keeps is the
# close -- the number that cannot be reconstructed once the game starts, and
# the one every closing-line comparison is measured against. Of the two halves,
# only one of them expires.
EXTRA_CLOSING_TWO_WAY = (MARKET_TOTALS,)


def minutes_to_first_pitch(event: dict, now: datetime | None = None) -> float | None:
    """Minutes from now until this event starts. Negative once it has begun."""
    raw = (event or {}).get("commence_time")
    if not raw:
        return None
    try:
        start = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    now = now or datetime.now(timezone.utc)
    return (start - now).total_seconds() / 60.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--team", default=config.TEAM_ABBR)
    ap.add_argument("--window", type=float, default=DEFAULT_WINDOW_MIN,
                    help="capture when first pitch is this many minutes away or less")
    ap.add_argument("--floor", type=float, default=DEFAULT_FLOOR_MIN,
                    help="do not capture inside this many minutes of first pitch")
    ap.add_argument("--force", action="store_true", help="capture regardless of the clock")
    ap.add_argument("--dry-run", action="store_true", help="decide, but spend nothing")
    args = ap.parse_args()

    team_id = config.TEAMS.get(args.team, {}).get("id", config.TEAM_ID)
    team_name = config.TEAMS.get(args.team, {}).get("name", config.TEAM_NAME)

    client = OddsAPIClient()
    if not client.configured:
        print("ODDS_API_KEY is not set - nothing to capture.")
        return 0

    # Free call. This is the whole reason the gate can be cheap.
    try:
        event = client.find_event(team_name)
    except Exception as e:
        print(f"Could not reach the odds provider: {e}")
        return 0
    if not event:
        print(f"No upcoming event found for {team_name}.")
        return 0

    mins = minutes_to_first_pitch(event)
    label = f"{event.get('away_team')} at {event.get('home_team')}"
    if mins is None:
        print(f"{label}: no commence_time on the event; not capturing.")
        return 0

    if not args.force:
        if mins > args.window:
            print(f"{label}: first pitch in {mins:.0f} min, outside the "
                  f"{args.window:.0f} min window. No credits spent.")
            return 0
        if mins < args.floor:
            # Past this point the book may be pricing the game in play, which is
            # a different market and must not be recorded as a close.
            print(f"{label}: first pitch in {mins:.0f} min, inside the "
                  f"{args.floor:.0f} min floor. Not capturing - risks in-play prices.")
            return 0

    if args.dry_run:
        print(f"{label}: would capture now ({mins:.0f} min to first pitch).")
        return 0

    book = fetch_book_lines(client, team_id)
    # Every book, not just the one we price against. This is the capture that
    # matters most -- it is the benchmark every closing-line number is measured
    # against -- and it was storing one book's price out of a response that had
    # already been paid for in full. The provider bills per market x region and
    # never per bookmaker.
    by_book = book.get("by_book", {}) or {}
    total = 0
    for market in (MARKET_PITCHER_KS, MARKET_BATTER_TB, MARKET_H2H):
        rows = odds_history.snapshot_rows_by_book(
            event, market, by_book.get(market, {})
        ) or odds_history.snapshot_rows(event, market, book.get(market, {}))
        total += odds_history.append_snapshot(rows)

    # Markets the page does not model but that get bet anyway. Captured only at
    # the close, not on every page build: a bet nobody can grade is a bet that
    # teaches nothing, and one credit a day is a cheap fix for that.
    #
    # Caveat worth knowing when reading the resulting CLV: The Odds API does not
    # carry DraftKings' home-run market, so the closing reference here is
    # whichever books it does carry. That measures whether the *market* moved,
    # not whether the book bet at did, and is weaker evidence accordingly.
    for market in EXTRA_CLOSING_MARKETS:
        try:
            payload = client.get_event_props(event["id"], markets=market)
            # All books, keyed by book. This previously took
            # next(iter(b.values())) whenever our own book did not quote the
            # market -- an arbitrary book, whichever the provider happened to
            # list first, recorded as *the* closing price. Which book that was
            # could differ from night to night, so a close was not reliably
            # comparable to the open it is differenced against.
            extra_by_book = parse_player_lines_by_book(payload, market)
            rows = odds_history.snapshot_rows_by_book(event, market, extra_by_book)
            if not rows:
                rows = odds_history.snapshot_rows(
                    event, market,
                    _parse_player_lines(payload, market, book=client.bookmaker),
                )
            total += odds_history.append_snapshot(rows)
        except Exception as e:
            log.warning("Could not capture %s: %s", market, e)

    for market in EXTRA_CLOSING_TWO_WAY:
        try:
            payload = client.get_event_props(event["id"], markets=market)
            by_book = parse_two_way_by_book(payload, market)
            total += odds_history.append_snapshot(
                odds_history.snapshot_rows_by_book(event, market, by_book)
            )
        except Exception as e:
            log.warning("Could not capture %s: %s", market, e)

    print(f"{label}: captured {total} rows at {mins:.0f} min to first pitch "
          f"(quota remaining: {client.requests_remaining}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
