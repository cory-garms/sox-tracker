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

import config  # noqa: E402
from analysis.grading import grade_frame  # noqa: E402
from data import predictions_history as ph  # noqa: E402
from data.fetcher import Fetcher  # noqa: E402

log = logging.getLogger(__name__)


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

    graded, stats = grade_frame(history, pitching, batting)

    log.info(
        "%d newly settled, %d already settled, %d not settleable yet (of %d rows)",
        stats["graded"], stats["already"], stats["skipped"], len(history),
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
