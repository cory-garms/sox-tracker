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

from backend.repository import insert_model_predictions, insert_odds_snapshots
from data import odds_history

log = logging.getLogger(__name__)


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
        name = row.get("player_name") or row.get("name") or "Unknown"
        proj = row.get("proj_k") or row.get("projection") or 0.0
        line = row.get("book_line") or row.get("line")
        edge = row.get("edge_k") or row.get("edge")

        details = {
            "proj_ip": row.get("proj_ip"),
            "season_k9": row.get("season_k9"),
            "opponent_k_factor": opponent_factor or row.get("opponent_k_factor"),
            "starts": row.get("starts"),
        }

        predictions.append({
            "created_at": stamp,
            "event_id": event_id,
            "game_date": game_date,
            "market": "pitcher_strikeouts",
            "player": str(name),
            "line": float(line) if line is not None and not pd.isna(line) else None,
            "projection": float(proj),
            "model_over_prob": float(row["model_over_prob"]) if "model_over_prob" in row and not pd.isna(row["model_over_prob"]) else None,
            "model_under_prob": float(row["model_under_prob"]) if "model_under_prob" in row and not pd.isna(row["model_under_prob"]) else None,
            "book_over_prob": float(row["book_over_prob"]) if "book_over_prob" in row and not pd.isna(row["book_over_prob"]) else None,
            "edge": float(edge) if edge is not None and not pd.isna(edge) else None,
            "model_error": 0.45,  # Backtested league error constant
            "recommendation": str(row.get("recommendation", "NO CALL ⚖️")),
            "model_version": model_version,
            "opponent_name": opponent_name,
            "opponent_factor": opponent_factor,
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
        name = row.get("player_name") or row.get("name") or "Unknown"
        proj = row.get("proj_tb") or row.get("projection") or 0.0
        line = row.get("book_line") or row.get("line")
        edge_prob = row.get("edge_prob") or row.get("edge")

        details = {
            "proj_pa": row.get("proj_pa"),
            "slg": row.get("slg"),
            "iso": row.get("iso"),
        }

        predictions.append({
            "created_at": stamp,
            "event_id": event_id,
            "game_date": game_date,
            "market": "batter_total_bases",
            "player": str(name),
            "line": float(line) if line is not None and not pd.isna(line) else None,
            "projection": float(proj),
            "model_over_prob": float(row["model_over_prob"]) if "model_over_prob" in row and not pd.isna(row["model_over_prob"]) else None,
            "model_under_prob": float(row["model_under_prob"]) if "model_under_prob" in row and not pd.isna(row["model_under_prob"]) else None,
            "book_over_prob": float(row["book_over_prob"]) if "book_over_prob" in row and not pd.isna(row["book_over_prob"]) else None,
            "edge": float(edge_prob) if edge_prob is not None and not pd.isna(edge_prob) else None,
            "model_error": 0.049,  # ±4.9 percentage points error bar
            "recommendation": str(row.get("recommendation", "NO CALL ⚖️")),
            "model_version": model_version,
            "opponent_name": "",
            "opponent_factor": None,
            "details_json": json.dumps(details),
        })

    return insert_model_predictions(session, predictions)
