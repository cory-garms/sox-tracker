"""
Append-only log of every projection the models have published, and how it
turned out.

Why this exists. The site publishes projections with error bars and declines to
call a side when the edge sits inside the error. Nothing measured whether that
discipline was well-founded, because nothing recorded what actually happened: a
reader could not tell an appropriately humble model from a useless one, since
both render as NO CALL.

The database had a `model_predictions` table, but it recorded only what was
*said* — never the outcome — and the archiver populating it read column names
the models do not emit, so every row's `line` was NULL. A prediction without its
line cannot be graded at all: there is no over/under to score it against.

This file is the durable record, and it is the one artefact here that grows
strictly more valuable with time. It follows data/odds_history.py exactly:
append-only, deduped on a composite key, never raises, and written by GitHub
Actions (the reliable scheduler) rather than by the Render process, which the
free plan spins down when idle. scripts/migrate_parquet_to_db.py mirrors it into
Postgres on deploy.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

import config

log = logging.getLogger(__name__)

HISTORY_PATH: Path = config.CACHE_DIR / "predictions_history.parquet"

# `captured_at` is when the projection was made; `game_date` is the day it is
# about. They differ whenever a build runs the morning of a night game, and the
# gap between them is itself worth keeping — a projection made before the lineup
# was posted is a different animal from one made after.
COLUMNS = [
    # identity
    "captured_at", "game_date", "commence_time", "event_id", "game_pk",
    "market", "player_id", "player", "lineup_slot",
    # what the model said
    "line", "projection", "model_over_prob", "book_over_prob", "edge",
    "model_error", "recommendation", "model_version",
    "opponent_name", "opponent_factor",
    # what happened — filled in by scripts/grade_predictions.py
    "actual", "outcome", "settled_at",
]

KEY = ["captured_at", "market", "player", "game_date"]

# Outcome vocabulary.
#
# "no_line" is the one that needs explaining: most logged projections never had
# a book line matched to them, and those rows are still worth settling. The
# actual is known, so they measure projection error (how far off was 5.1 K?),
# but there is no over/under to classify, so they must stay out of any
# calibration or Brier figure. Leaving them blank instead would put them back in
# the ungraded queue on every run, forever.
#
# "void" covers a prediction whose game was never played.
OUTCOME_OVER = "over"
OUTCOME_UNDER = "under"
OUTCOME_PUSH = "push"
OUTCOME_NO_LINE = "no_line"
OUTCOME_VOID = "void"
# The player was not in a game that was played -- benched, rested, or optioned.
# Books void a prop on someone who never appears, and so does this.
#
# It needs its own terminal state rather than being left blank. These tables
# rank the top ten hitters by projection across the roster, so four or five
# every night are bench bats who never bat; left ungraded they returned to the
# queue on every future run for the rest of the season, which is the same leak
# no_line exists to prevent one market over.
OUTCOME_DNP = "dnp"

# Outcomes that carry a direction, and so can be scored against a probability.
DIRECTIONAL = {OUTCOME_OVER, OUTCOME_UNDER, OUTCOME_PUSH}


def snapshot_rows(
    frame: pd.DataFrame,
    market: str,
    game_date: str,
    *,
    model_version: str,
    model_error: float,
    line_col: str,
    projection_col: str,
    edge_col: str,
    event_id: str = "",
    commence_time: str | None = None,
    opponent_name: str = "",
    opponent_factor: float | None = None,
    captured_at: str | None = None,
) -> list[dict[str, Any]]:
    """
    Flatten one model's output frame into history rows.

    The column names differ between the two models — the strikeout model emits
    `prop_line`/`proj_k`/`edge`, total bases emits `prop_line`/`proj_tb`/
    `prob_edge` — so the caller names them rather than this guessing. Guessing
    is precisely how the database archiver came to read `book_line`, a column
    that has never existed.

    Rows the model could not price (no matched book line) are still logged: the
    projection can be graded against the actual even when there was no line to
    take a side on, and those rows are most of the sample.
    """
    if frame is None or frame.empty:
        return []

    stamp = captured_at or datetime.now(timezone.utc).isoformat(timespec="seconds")

    missing = [c for c in (line_col, projection_col, edge_col) if c not in frame.columns]
    if missing:
        log.warning("Model frame for %s is missing %s; logging nothing.", market, missing)
        return []

    rows = []
    for _, row in frame.iterrows():
        rows.append({
            "captured_at": stamp,
            "game_date": game_date,
            "commence_time": commence_time,
            "event_id": str(event_id or ""),
            "game_pk": pd.NA,           # resolved at grading time
            "market": market,
            "player_id": _int_or_na(row.get("player_id")),
            "player": str(row.get("player_name") or "Unknown"),
            # Pre-game expected batting slot. Recoverable from the boxscore
            # afterwards, but joined here it is usable directly and costs a
            # lookup against a lineup the build has already fetched.
            "lineup_slot": _int_or_na(row.get("lineup_slot")),
            "line": _float_or_nan(row.get(line_col)),
            "projection": _float_or_nan(row.get(projection_col)),
            "model_over_prob": _float_or_nan(row.get("model_over_prob")),
            "book_over_prob": _float_or_nan(row.get("book_over_prob")),
            "edge": _float_or_nan(row.get(edge_col)),
            "model_error": float(model_error),
            "recommendation": str(row.get("recommendation", "")),
            "model_version": str(model_version),
            "opponent_name": opponent_name or "",
            "opponent_factor": _float_or_nan(
                opponent_factor if opponent_factor is not None else row.get("opp_k_factor")
            ),
            "actual": float("nan"),
            "outcome": "",
            "settled_at": "",
        })
    return rows


def append_snapshot(rows: list[dict[str, Any]], path: Path = HISTORY_PATH) -> int:
    """
    Append rows, returning how many were actually new.

    Never raises: a page build must not fail because a log could not be written.
    """
    if not rows:
        return 0
    try:
        frame = pd.DataFrame(rows).reindex(columns=COLUMNS)
        existing = load_history(path)
        combined = pd.concat([existing, frame], ignore_index=True) if not existing.empty else frame
        # keep="first" preserves an already-graded row against a re-run of the
        # same build, so grading is never undone by a later append.
        combined = combined.drop_duplicates(subset=KEY, keep="first")
        added = len(combined) - len(existing)
        if added <= 0:
            log.info("Predictions history unchanged.")
            return 0
        path.parent.mkdir(parents=True, exist_ok=True)
        combined.to_parquet(path, index=False)
        log.info("Predictions history: +%d rows (%d total) -> %s", added, len(combined), path)
        return added
    except Exception as e:                      # disk full, parquet engine, ...
        log.warning("Could not write predictions history to %s: %s", path, e)
        return 0


def load_history(path: Path = HISTORY_PATH) -> pd.DataFrame:
    """The whole log, or an empty frame with the right columns if there is none."""
    if not Path(path).exists():
        return pd.DataFrame(columns=COLUMNS)
    try:
        return pd.read_parquet(path).reindex(columns=COLUMNS)
    except Exception as e:
        log.warning("Could not read predictions history at %s: %s", path, e)
        return pd.DataFrame(columns=COLUMNS)


def write_history(frame: pd.DataFrame, path: Path = HISTORY_PATH) -> bool:
    """Overwrite the log wholesale. Used by grading to write settled rows back."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.reindex(columns=COLUMNS).to_parquet(path, index=False)
        return True
    except Exception as e:
        log.warning("Could not write predictions history to %s: %s", path, e)
        return False


def ungraded(frame: pd.DataFrame) -> pd.DataFrame:
    """Rows with no outcome recorded yet."""
    if frame is None or frame.empty:
        return frame
    outcome = frame["outcome"].fillna("").astype(str).str.strip()
    return frame[outcome == ""]


def graded(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Rows that can be scored against a probability — over, under or push.

    Excludes voids (the game was never played, so it says nothing about the
    model) and no_line rows (no over/under to be right or wrong about). Both are
    kept in the log so they are not reconsidered every run, but neither may
    reach a calibration curve or a Brier score.
    """
    if frame is None or frame.empty:
        return frame
    outcome = frame["outcome"].fillna("").astype(str).str.strip()
    return frame[outcome.isin(DIRECTIONAL)]


def latest_per_game(frame: pd.DataFrame) -> pd.DataFrame:
    """
    One row per player per game — the last projection made before first pitch.

    **Scoring must go through this.** Every build logs a snapshot, so the same
    player-game appears once per build: in the real log 882 directional rows
    collapse to 164 distinct player-games, and one pitcher-game was captured 23
    times. Scoring the raw rows would claim a sample five times larger than it
    is, and would weight each game by how many times it happened to be captured
    — a rained-on afternoon with many builds outvoting a clean night with one.

    The last pre-game capture is the one kept: it is the most informed version
    of the projection and the one comparable against a closing line.
    """
    if frame is None or frame.empty:
        return frame
    ordered = frame.sort_values("captured_at")

    # "Before first pitch" was the stated contract and was never enforced: this
    # took the last capture full stop. A build that runs while a game is on
    # therefore replaced that game's pre-game projection with an in-play one,
    # scored afterwards as though it had been made in advance.
    #
    # It had already happened. The only 22 live rows in the archive -- every
    # other row is a replay -- were captured at 21:28Z on 2026-08-23 against a
    # 19:16Z first pitch, two hours into the game, and were being scored as
    # predictions. All 22 also have a pre-game capture, so enforcing this
    # corrects them and loses nothing.
    #
    # Parsed rather than string-compared: captured_at ends "+00:00" and
    # commence_time ends "Z", and "+" sorts before "Z", so a capture at exactly
    # first pitch would compare as earlier than it.
    if "commence_time" in ordered.columns:
        captured = pd.to_datetime(ordered["captured_at"], utc=True, errors="coerce")
        commence = pd.to_datetime(ordered["commence_time"], utc=True, errors="coerce")
        # An unparseable or absent first pitch cannot convict a row, so those
        # are kept: losing a real projection is worse than keeping a doubtful one.
        in_play = commence.notna() & captured.notna() & (captured >= commence)
        ordered = ordered[~in_play]
        if ordered.empty:
            return ordered

    # tail(1) on the ordering, not groupby().last(): the latter takes the last
    # non-null value of each column independently and can stitch together a row
    # that never existed.
    keep = ordered.groupby(["game_date", "market", "player"], sort=False).tail(1)
    return keep


def with_actuals(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Rows whose actual result is known, line or not.

    Wider than `graded`: a projection with no book line still measures
    projection error, and those rows are most of the sample.
    """
    if frame is None or frame.empty:
        return frame
    outcome = frame["outcome"].fillna("").astype(str).str.strip()
    return frame[outcome.isin(DIRECTIONAL | {OUTCOME_NO_LINE})]


def settle(actual: float, line: float | None) -> str:
    """
    Classify an outcome against its line.

    A whole-number line that the actual lands exactly on is a **push**, not a
    loss — books refund it, and scoring it as a miss would understate the model.
    Half-point lines cannot push, which is why books use them.
    """
    if actual is None or pd.isna(actual):
        return ""
    if line is None or pd.isna(line):
        # No line to beat, but the projection is still gradeable against the
        # actual. Left unclassified rather than guessed at.
        return ""
    if float(actual) > float(line):
        return OUTCOME_OVER
    if float(actual) < float(line):
        return OUTCOME_UNDER
    return OUTCOME_PUSH


def _float_or_nan(value: Any) -> float:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return float("nan")
    try:
        if pd.isna(value):
            return float("nan")
    except (TypeError, ValueError):
        pass
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _int_or_na(value: Any):
    try:
        if value is None or pd.isna(value):
            return pd.NA
        return int(value)
    except (TypeError, ValueError):
        return pd.NA
