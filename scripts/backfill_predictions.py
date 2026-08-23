#!/usr/bin/env python3
"""
Reconstruct the projections the models *would* have published, from the odds
already on record.

Why this is possible. Both models are pure functions of their input frames —
verified: no datetime.now, no network, and `batting`/`games`/`client` are dead
parameters on the strikeout model. Given stats truncated to before a date, plus
`league_k9` and `as_of_date` for that date, they reproduce the projection they
would have made then. odds_history.parquet holds every line ever fetched, so
the missing half of each historical prediction is already on disk.

That turns the track record from "check back in three months" into ~30 days of
gradeable history on day one.

**Lookahead is the whole risk here.** A backfill that leaks future information
produces a model that looks brilliant and is worthless. Three guards:

  1. Stats are truncated to `game_date < D`.
  2. `league_k9` is recomputed as of D — betting_report.py passes the
     full-season rate, which is right live and would be a leak here.
  3. `as_of_date=D` bounds the opponent factor (data/opponent.py:184).

Cached logs are read with max_age_hours=0, so this spends no odds credits and
makes no MLB call.

Replayed rows are tagged with a `-replay` model_version suffix. They are
reconstructions, not what was actually published, and must never be silently
mixed with live predictions.

Usage:
    python scripts/backfill_predictions.py --dry-run
    python scripts/backfill_predictions.py
    python scripts/backfill_predictions.py --since 2026-08-01
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

import config  # noqa: E402
from analysis.betting import (  # noqa: E402
    MODEL_ERROR_K,
    MODEL_ERROR_TB_PROB,
    batter_total_bases_model,
    pitcher_strikeout_model,
)
from data import league_pitching as lp  # noqa: E402
from data import odds_history  # noqa: E402
from data import opponent as opp  # noqa: E402
from data import predictions_history as ph  # noqa: E402
from data.fetcher import Fetcher  # noqa: E402

log = logging.getLogger(__name__)

# MLB's "official date" is the local date at the park. A 23:10 UTC first pitch
# is a 19:10 ET game on the previous UTC day for half the season, so converting
# through Eastern is what matches the games cache.
ET = ZoneInfo("America/New_York")

MARKET_K = "pitcher_strikeouts"
MARKET_TB = "batter_total_bases"

_NAME_TO_ID = {info["name"]: info["id"] for info in config.TEAMS.values()}


def game_date_of(commence_time: str | None) -> str | None:
    """The official (Eastern) date a UTC first pitch belongs to."""
    if not commence_time:
        return None
    ts = pd.to_datetime(commence_time, utc=True, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.tz_convert(ET).strftime("%Y-%m-%d")


def opponent_id_of(row: pd.Series, team_id: int) -> int | None:
    """Which team the prediction is against, from the odds event's team names."""
    for side in ("home_team", "away_team"):
        other = _NAME_TO_ID.get(str(row.get(side) or ""))
        if other is not None and other != team_id:
            return other
    return None


def _lines_from(group: pd.DataFrame) -> dict[str, dict]:
    """The {player: line/odds} map the models consume, from history rows."""
    out: dict[str, dict] = {}
    for _, r in group.iterrows():
        if pd.isna(r.get("line")):
            continue
        out[str(r["player"])] = {
            "line": float(r["line"]),
            "over_odds": None if pd.isna(r.get("over_odds")) else int(r["over_odds"]),
            "under_odds": None if pd.isna(r.get("under_odds")) else int(r["under_odds"]),
        }
    return out


def replay(
    history: pd.DataFrame,
    pitching: pd.DataFrame,
    batting: pd.DataFrame,
    league_logs: pd.DataFrame,
    hitting_logs: pd.DataFrame,
    team_id: int,
    since: str | None = None,
) -> list[dict]:
    """Walk every pre-game capture and rebuild what the models would have said."""
    pre_game = odds_history.pre_game_only(history)
    if pre_game is None or pre_game.empty:
        return []

    wanted = pre_game[pre_game["market"].isin({MARKET_K, MARKET_TB})].copy()
    wanted["game_date"] = wanted["commence_time"].map(game_date_of)
    wanted = wanted.dropna(subset=["game_date"])
    if since:
        wanted = wanted[wanted["game_date"] >= since]
    if wanted.empty:
        return []

    def _dates(frame: pd.DataFrame) -> pd.Series:
        """Date column as strings, tolerating a frame with no rows or no columns."""
        if frame is None or frame.empty or "game_date" not in frame.columns:
            return pd.Series(dtype=str)
        return frame["game_date"].astype(str)

    def _before(frame: pd.DataFrame, dates: pd.Series, cutoff: str) -> pd.DataFrame:
        if dates.empty:
            return frame if frame is not None else pd.DataFrame()
        return frame[dates < cutoff]

    pit_dates = _dates(pitching)
    bat_dates = _dates(batting)

    rows: list[dict] = []
    grouped = wanted.groupby(["captured_at", "market", "game_date"], sort=True)

    for (captured_at, market, game_date), group in grouped:
        lines = _lines_from(group)
        if not lines:
            continue

        # --- guard 1: the model may only see games played before this date ---
        prior_pitching = _before(pitching, pit_dates, game_date)
        prior_batting = _before(batting, bat_dates, game_date)
        needed = prior_pitching if market == MARKET_K else prior_batting
        if needed is None or needed.empty:
            continue

        event_id = str(group["event_id"].iloc[0])
        commence = group["commence_time"].iloc[0]

        if market == MARKET_K:
            # --- guard 2: league rate as of this date, never its own future ---
            lk9 = lp.league_k_per_9(league_logs, before=game_date) if not league_logs.empty else None
            opponent_id = opponent_id_of(group.iloc[0], team_id)

            frame = pitcher_strikeout_model(
                prior_pitching, None, None,
                book_lines=lines,
                opponent_logs=hitting_logs if not hitting_logs.empty else None,
                opponent_team_id=opponent_id,
                # --- guard 3: opponent factor bounded to before this date ---
                as_of_date=game_date,
                league_k9=lk9,
            )
            rows.extend(ph.snapshot_rows(
                frame, MARKET_K, game_date,
                model_version="v1.2-regressed-opponent-replay",
                model_error=MODEL_ERROR_K,
                line_col="prop_line", projection_col="proj_k", edge_col="edge",
                event_id=event_id, commence_time=commence,
                captured_at=str(captured_at),
            ))
        else:
            frame = batter_total_bases_model(prior_batting, book_lines=lines)
            rows.extend(ph.snapshot_rows(
                frame, MARKET_TB, game_date,
                model_version="v1.1-convolved-pa-replay",
                model_error=MODEL_ERROR_TB_PROB,
                line_col="prop_line", projection_col="proj_tb", edge_col="prob_edge",
                event_id=event_id, commence_time=commence,
                captured_at=str(captured_at),
            ))

    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--since", help="Only replay captures on/after this game date.")
    parser.add_argument("--team", default=config.TEAM_ABBR)
    parser.add_argument("--season", type=int, default=config.SEASON)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    team_id = config.TEAMS.get(args.team, {}).get("id", config.TEAM_ID)

    history = odds_history.load_history()
    if history.empty:
        log.error("No odds history on disk — nothing to replay.")
        return 1

    fetcher = Fetcher(team_id=team_id, season=args.season)
    try:
        pitching = fetcher.load("pitching")
        batting = fetcher.load("batting")
    except FileNotFoundError as e:
        log.error("Cache not built: %s", e)
        return 1

    # max_age_hours=0 reads whatever is cached: no network, no quota, and a
    # historical sample that does not change between runs.
    league_logs = lp.load_league_logs(args.season, max_age_hours=0)
    hitting_logs = opp.load_team_hitting_logs(args.season, max_age_hours=0)

    log.info("Replaying %d odds snapshots (%d captures)...",
             len(history), history["captured_at"].nunique())

    rows = replay(history, pitching, batting, league_logs, hitting_logs,
                  team_id, since=args.since)

    if not rows:
        log.info("Nothing to replay.")
        return 0

    frame = pd.DataFrame(rows)
    with_line = frame["line"].notna().sum()
    log.info(
        "Rebuilt %d predictions across %d game dates (%d carry a book line).",
        len(frame), frame["game_date"].nunique(), with_line,
    )
    log.info("By market:\n%s", frame["market"].value_counts().to_string())

    if args.dry_run:
        log.info("\n--dry-run: nothing written.")
        log.info("\nSample:\n%s", frame[
            ["game_date", "market", "player", "line", "projection", "edge", "recommendation"]
        ].head(8).to_string(index=False))
        return 0

    added = ph.append_snapshot(rows)
    log.info("Appended %d new rows to %s", added, ph.HISTORY_PATH)
    log.info("Now run: python scripts/grade_predictions.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
