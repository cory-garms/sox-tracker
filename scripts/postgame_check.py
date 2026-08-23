#!/usr/bin/env python3
"""
Decide whether a game has just gone final and the pages owe it a rebuild.

Why this exists. refresh.yml rebuilds at four fixed points (07:00 / 12:00 /
15:00 / 17:30 ET). A 19:10 ET game ends around 22:00 ET, so last night's result
does not reach the site until 07:00 the next morning — a nine-hour window in
which the season dashboard, the leaderboards and the streak page all disagree
with the box score. The four builds are aimed at the *pre*-game board; nothing
was aimed at the final out.

The same trick that makes capture_close.py affordable applies here and is even
cheaper: reading the MLB schedule costs nothing at all. So this can be polled
often, and it reports "rebuild" only when a game the site has not yet processed
is genuinely complete.

It deliberately spends **zero odds credits** and asks for no odds rebuild: the
prices on a finished game are of no further use, and betting_report.py is the
one build that costs quota. What goes stale after a final out is the stats
side, so that is all the workflow rebuilds.

Completion uses the same rule as data/fetcher.py: a postponed game keeps
abstractGameState "Final" while never having been played, so detailedState is
what decides. Doubleheaders are tracked per gamePk, so both ends of a date are
processed independently rather than the nightcap masking game one.

Usage:
    python scripts/postgame_check.py                 # report the decision
    python scripts/postgame_check.py --mark          # record games as processed
    python scripts/postgame_check.py --lookback 2    # also re-check earlier days
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from client.mlb_client import MLBClient  # noqa: E402
from data.fetcher import _UNPLAYED_STATES  # noqa: E402

log = logging.getLogger(__name__)

STATE_PATH = config.CACHE_DIR / "postgame_state.json"

# How many days back to look. One covers the ordinary case of a night game that
# finished after UTC midnight; more is only useful after an outage.
DEFAULT_LOOKBACK_DAYS = 1


def load_state(path: Path = STATE_PATH) -> set[int]:
    """gamePks already built into the published pages."""
    if not path.exists():
        return set()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {int(pk) for pk in raw.get("processed_game_pks", [])}
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        log.warning("Could not read %s (%s); treating as empty.", path, e)
        return set()


def save_state(processed: set[int], path: Path = STATE_PATH) -> None:
    """
    Persist processed gamePks, keeping the file bounded.

    A season is at most ~162 entries, but this is committed to the repo on
    every post-game run, so it keeps only a recent tail rather than growing
    without limit. Ordering is by pk, which is stable — it is used here purely
    as an identity, never to order games (see analysis.streaks.played_in_order).
    """
    keep = sorted(processed)[-400:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"processed_game_pks": keep}, indent=2) + "\n",
        encoding="utf-8",
    )


def completed_games(
    client: MLBClient | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    now: datetime | None = None,
) -> list[dict]:
    """
    Every genuinely completed team game across the lookback window.

    Free: the MLB Stats API charges nothing, so this can be polled as often as
    the workflow likes.
    """
    client = client or MLBClient()
    now = now or datetime.now(timezone.utc)

    start = (now - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    end = now.strftime("%Y-%m-%d")

    try:
        games = client.get_schedule(
            team_id=config.TEAM_ID,
            season=config.SEASON,
            start_date=start,
            end_date=end,
            hydrate="linescore",
        )
    except Exception as e:
        log.warning("Could not read the MLB schedule: %s", e)
        return []

    out: list[dict] = []
    for game in games:
        status = game.get("status", {})
        if status.get("abstractGameState") != "Final":
            continue
        if status.get("detailedState") in _UNPLAYED_STATES:
            continue
        out.append({
            "game_pk": int(game.get("gamePk")),
            # officialDate is the date the game counts for, which is what the
            # makeup half of a postponement carries.
            "game_date": game.get("officialDate") or game.get("gameDate", "")[:10],
            "game_number": int(game.get("gameNumber", 1)),
            "detailed_state": status.get("detailedState", "Final"),
        })
    return out


def pending_games(
    client: MLBClient | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    state_path: Path = STATE_PATH,
) -> list[dict]:
    """Completed games the published pages have not been rebuilt for."""
    processed = load_state(state_path)
    return [g for g in completed_games(client, lookback_days) if g["game_pk"] not in processed]


def _emit_github_output(rebuild: bool, games: list[dict]) -> None:
    """Expose the decision to later workflow steps."""
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        return
    summary = ", ".join(
        f"{g['game_date']} g{g['game_number']} (pk {g['game_pk']})" for g in games
    )
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(f"rebuild={'true' if rebuild else 'false'}\n")
        fh.write(f"count={len(games)}\n")
        fh.write(f"summary={summary}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mark", action="store_true",
        help="Record the pending games as processed (run after a successful build).",
    )
    parser.add_argument(
        "--lookback", type=int, default=DEFAULT_LOOKBACK_DAYS,
        help=f"Days back to inspect (default: {DEFAULT_LOOKBACK_DAYS}).",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    pending = pending_games(lookback_days=args.lookback)

    if not pending:
        log.info("No newly completed games. Nothing to rebuild.")
        _emit_github_output(False, [])
        return 0

    for g in pending:
        log.info(
            "Final and unbuilt: %s game %d (pk %d, %s)",
            g["game_date"], g["game_number"], g["game_pk"], g["detailed_state"],
        )

    if args.mark:
        processed = load_state() | {g["game_pk"] for g in pending}
        save_state(processed)
        log.info("Marked %d game(s) as processed.", len(pending))

    _emit_github_output(True, pending)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
