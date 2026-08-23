"""
Prediction & Odds Archiver Service.
Atomically archives sportsbook odds alongside generated model projections.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from analysis.betting import MODEL_ERROR_K, MODEL_ERROR_TB_PROB
from backend.repository import insert_model_predictions, insert_odds_snapshots
from data import odds_history

log = logging.getLogger(__name__)


# The exact column names the two models emit. Archiving read a different set of
# names for months — `book_line` where the model says `prop_line`, `edge_prob`
# where it says `prob_edge` — and since row.get() returns None for a missing
# key rather than raising, every archived prediction carried line=None. A
# prediction without its line cannot be graded at all: there is no over/under
# to score it against. tests/test_archiver_keys.py drives a real model call and
# fails if any name here stops existing.
_K_FIELDS = {
    "projection": "proj_k",
    "line": "prop_line",
    "edge": "edge",
}
_TB_FIELDS = {
    "projection": "proj_tb",
    "line": "prop_line",
    "edge": "prob_edge",
}


def _num(row: pd.Series, column: str) -> float | None:
    """
    Read a numeric cell, or None if absent or NaN.

    Deliberately not `row.get(a) or row.get(b)`: that chain treats a legitimate
    0.0 as missing and falls through to the next candidate.
    """
    if column not in row:
        return None
    value = row[column]
    if value is None or pd.isna(value):
        return None
    return float(value)


def archive_market_odds(
    session: Session,
    event: dict[str, Any] | None,
    market: str,
    lines: dict[str, dict[str, Any]],
    captured_at: str | None = None,
) -> int:
    """
    Convert raw market lines dict to odds snapshot rows and persist into database.
    """
    rows = odds_history.snapshot_rows(event, market, lines, captured_at=captured_at)
    return insert_odds_snapshots(session, rows)


def archive_strikeout_projections(
    session: Session,
    k_df: pd.DataFrame,
    event_id: str = "",
    game_date: str = "",
    opponent_name: str = "",
    opponent_factor: float | None = None,
    model_version: str = "v1.2-regressed-opponent",
) -> int:
    """
    Archive pitcher strikeout model projections.
    """
    if k_df.empty:
        return 0

    predictions = []
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for _, row in k_df.iterrows():
        name = row.get("player_name") or "Unknown"
        over_prob = _num(row, "model_over_prob")
        row_factor = _num(row, "opp_k_factor")

        details = {
            "proj_ip": _num(row, "avg_ip_start"),
            "season_k9": _num(row, "season_k9"),
            "l5_k9": _num(row, "l5_k9"),
            "blended_k9": _num(row, "blended_k9"),
            "opponent_k_factor": opponent_factor if opponent_factor is not None else row_factor,
            "starts": _num(row, "starts"),
        }

        predictions.append({
            "created_at": stamp,
            "event_id": event_id,
            "game_date": game_date,
            "market": "pitcher_strikeouts",
            "player": str(name),
            "line": _num(row, _K_FIELDS["line"]),
            "projection": _num(row, _K_FIELDS["projection"]) or 0.0,
            "model_over_prob": over_prob,
            # The models report the over side only; the complement is the under.
            "model_under_prob": (1.0 - over_prob) if over_prob is not None else None,
            "book_over_prob": _num(row, "book_over_prob"),
            "edge": _num(row, _K_FIELDS["edge"]),
            "model_error": MODEL_ERROR_K,
            "recommendation": str(row.get("recommendation", "NO CALL ⚖️")),
            "model_version": model_version,
            "opponent_name": opponent_name,
            "opponent_factor": opponent_factor if opponent_factor is not None else row_factor,
            "details_json": json.dumps(details),
        })

    return insert_model_predictions(session, predictions)


def archive_total_bases_projections(
    session: Session,
    tb_df: pd.DataFrame,
    event_id: str = "",
    game_date: str = "",
    model_version: str = "v1.1-convolved-pa",
) -> int:
    """
    Archive batter total-bases model projections.
    """
    if tb_df.empty:
        return 0

    predictions = []
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for _, row in tb_df.iterrows():
        name = row.get("player_name") or "Unknown"
        over_prob = _num(row, "model_over_prob")

        details = {
            "pa": _num(row, "pa"),
            "starts": _num(row, "starts"),
            "season_slg": _num(row, "season_slg"),
            "season_avg": _num(row, "season_avg"),
            "tb_per_start": _num(row, "tb_per_start"),
            "l10_tb_start": _num(row, "l10_tb_start"),
        }

        predictions.append({
            "created_at": stamp,
            "event_id": event_id,
            "game_date": game_date,
            "market": "batter_total_bases",
            "player": str(name),
            "line": _num(row, _TB_FIELDS["line"]),
            "projection": _num(row, _TB_FIELDS["projection"]) or 0.0,
            "model_over_prob": over_prob,
            "model_under_prob": (1.0 - over_prob) if over_prob is not None else None,
            "book_over_prob": _num(row, "book_over_prob"),
            "edge": _num(row, _TB_FIELDS["edge"]),
            "model_error": MODEL_ERROR_TB_PROB,
            "recommendation": str(row.get("recommendation", "NO CALL ⚖️")),
            "model_version": model_version,
            "opponent_name": "",
            "opponent_factor": None,
            "details_json": json.dumps(details),
        })

    return insert_model_predictions(session, predictions)
