"""
SQLAlchemy ORM models for odds snapshots, model predictions, bet logging, and game schedules.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from backend.database import Base


def utc_now_iso() -> str:
    """Return current UTC time formatted as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class OddsSnapshot(Base):
    """
    Historical record of sportsbook odds at a given build/scrape timestamp.
    Mirrors data/odds_history.py parquet structure.
    """
    __tablename__ = "odds_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    captured_at = Column(String(32), nullable=False, index=True)
    event_id = Column(String(64), nullable=False, index=True)
    commence_time = Column(String(32), nullable=True)
    home_team = Column(String(64), nullable=True)
    away_team = Column(String(64), nullable=True)
    market = Column(String(64), nullable=False, index=True)
    player = Column(String(128), nullable=False, index=True)
    line = Column(Float, nullable=True)
    over_odds = Column(Integer, nullable=True)
    under_odds = Column(Integer, nullable=True)
    book = Column(String(64), nullable=True, default="DraftKings")
    last_update = Column(String(32), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "captured_at", "event_id", "market", "player",
            name="uq_odds_snapshot_key",
        ),
        Index("idx_odds_lookup", "event_id", "market", "player"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "captured_at": self.captured_at,
            "event_id": self.event_id,
            "commence_time": self.commence_time,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "market": self.market,
            "player": self.player,
            "line": self.line,
            "over_odds": self.over_odds,
            "under_odds": self.under_odds,
            "book": self.book,
            "last_update": self.last_update,
        }


class ModelPrediction(Base):
    """
    Continuous archival record of model projections and calculated edges.
    Snapshotted alongside odds captures.
    """
    __tablename__ = "model_predictions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(String(32), nullable=False, default=utc_now_iso, index=True)
    event_id = Column(String(64), nullable=True, index=True)
    game_date = Column(String(16), nullable=False, index=True)
    market = Column(String(64), nullable=False, index=True)  # pitcher_strikeouts, batter_total_bases, etc.
    player = Column(String(128), nullable=False, index=True)
    line = Column(Float, nullable=True)
    projection = Column(Float, nullable=False)
    model_over_prob = Column(Float, nullable=True)
    model_under_prob = Column(Float, nullable=True)
    book_over_prob = Column(Float, nullable=True)
    edge = Column(Float, nullable=True)
    model_error = Column(Float, nullable=True)
    recommendation = Column(String(32), nullable=True)  # OVER, UNDER, NO CALL, PASS
    model_version = Column(String(32), nullable=False, default="v1.0")
    opponent_name = Column(String(64), nullable=True)
    opponent_factor = Column(Float, nullable=True)
    details_json = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_pred_lookup", "game_date", "market", "player"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "event_id": self.event_id,
            "game_date": self.game_date,
            "market": self.market,
            "player": self.player,
            "line": self.line,
            "projection": self.projection,
            "model_over_prob": self.model_over_prob,
            "model_under_prob": self.model_under_prob,
            "book_over_prob": self.book_over_prob,
            "edge": self.edge,
            "model_error": self.model_error,
            "recommendation": self.recommendation,
            "model_version": self.model_version,
            "opponent_name": self.opponent_name,
            "opponent_factor": self.opponent_factor,
            "details_json": self.details_json,
        }


class BetLog(Base):
    """
    Record of placed real and paper bets, graded against closing lines and outcomes.
    Mirrors data/bet_log.py parquet structure.
    """
    __tablename__ = "bet_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    placed_at = Column(String(32), nullable=False, default=utc_now_iso, index=True)
    event_id = Column(String(64), nullable=True, index=True)
    game_date = Column(String(16), nullable=True, index=True)
    market = Column(String(64), nullable=False)
    selection = Column(String(128), nullable=False)
    side = Column(String(32), nullable=False)
    line = Column(Float, nullable=True)
    price = Column(Float, nullable=False)
    book = Column(String(64), nullable=False, default="DraftKings")
    stake = Column(Float, nullable=False, default=0.0)
    promo = Column(String(64), nullable=True, default="")
    model_prob = Column(Float, nullable=True)
    consensus_prob = Column(Float, nullable=True)
    closing_price = Column(Float, nullable=True)
    clv_diff = Column(Float, nullable=True)
    result = Column(String(16), nullable=True, default="")  # win, loss, push, void, pending
    notes = Column(Text, nullable=True, default="")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "placed_at": self.placed_at,
            "event_id": self.event_id,
            "game_date": self.game_date,
            "market": self.market,
            "selection": self.selection,
            "side": self.side,
            "line": self.line,
            "price": self.price,
            "book": self.book,
            "stake": self.stake,
            "promo": self.promo,
            "model_prob": self.model_prob,
            "consensus_prob": self.consensus_prob,
            "closing_price": self.closing_price,
            "clv_diff": self.clv_diff,
            "result": self.result,
            "notes": self.notes,
        }


class GameSchedule(Base):
    """
    Tracked MLB games for scheduling ingestion, lineup confirmations, and closing line triggers.
    """
    __tablename__ = "game_schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    game_pk = Column(Integer, nullable=False, unique=True, index=True)
    game_date = Column(String(16), nullable=False, index=True)
    game_number = Column(Integer, nullable=False, default=1)
    season = Column(Integer, nullable=False, default=2026)
    home_team_id = Column(Integer, nullable=False)
    home_team_name = Column(String(64), nullable=True)
    away_team_id = Column(Integer, nullable=False)
    away_team_name = Column(String(64), nullable=True)
    status = Column(String(32), nullable=False, default="Scheduled")
    detailed_state = Column(String(64), nullable=True)
    probable_home_id = Column(Integer, nullable=True)
    probable_home_name = Column(String(128), nullable=True)
    probable_away_id = Column(Integer, nullable=True)
    probable_away_name = Column(String(128), nullable=True)
    first_pitch_utc = Column(String(32), nullable=True)
    home_score = Column(Integer, nullable=True)
    away_score = Column(Integer, nullable=True)
    lineup_home_confirmed = Column(Boolean, nullable=False, default=False)
    lineup_away_confirmed = Column(Boolean, nullable=False, default=False)
    last_synced_at = Column(String(32), nullable=False, default=utc_now_iso)

    __table_args__ = (
        Index("idx_game_date_ordering", "game_date", "game_number"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "game_pk": self.game_pk,
            "game_date": self.game_date,
            "game_number": self.game_number,
            "season": self.season,
            "home_team_id": self.home_team_id,
            "home_team_name": self.home_team_name,
            "away_team_id": self.away_team_id,
            "away_team_name": self.away_team_name,
            "status": self.status,
            "detailed_state": self.detailed_state,
            "probable_home_id": self.probable_home_id,
            "probable_home_name": self.probable_home_name,
            "probable_away_id": self.probable_away_id,
            "probable_away_name": self.probable_away_name,
            "first_pitch_utc": self.first_pitch_utc,
            "home_score": self.home_score,
            "away_score": self.away_score,
            "lineup_home_confirmed": self.lineup_home_confirmed,
            "lineup_away_confirmed": self.lineup_away_confirmed,
            "last_synced_at": self.last_synced_at,
        }
