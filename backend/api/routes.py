"""
FastAPI REST API routes for dirtywater.corygarms.com.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import GameSchedule, ModelPrediction
from backend.repository import (
    clv_summary,
    get_all_bets,
    get_line_movement,
    get_predictions_history,
    insert_bet,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic Schemas
# ---------------------------------------------------------------------------

class BetCreateRequest(BaseModel):
    selection: str = Field(..., description="Player or team name")
    market: str = Field(..., description="pitcher_strikeouts | batter_total_bases | h2h")
    side: str = Field(..., description="Over | Under | Moneyline")
    price: float = Field(..., description="American odds taken (e.g. +158 or -130)")
    line: Optional[float] = Field(None, description="Prop line number (e.g. 4.5 or 1.5)")
    stake: float = Field(0.0, description="Stake in units (0.0 for paper bets)")
    promo: str = Field("", description="e.g. boost_50, early_win_2run")
    book: str = Field("DraftKings", description="Sportsbook")
    event_id: str = Field("", description="The Odds API event ID")
    game_date: str = Field("", description="YYYY-MM-DD")
    model_prob: Optional[float] = Field(None, description="Model implied probability")
    consensus_prob: Optional[float] = Field(None, description="Consensus implied probability")
    notes: str = Field("", description="Notes or rationale")


class BetResponse(BaseModel):
    id: int
    placed_at: str
    event_id: Optional[str]
    game_date: Optional[str]
    market: str
    selection: str
    side: str
    line: Optional[float]
    price: float
    book: str
    stake: float
    promo: Optional[str]
    model_prob: Optional[float]
    consensus_prob: Optional[float]
    closing_price: Optional[float]
    clv_diff: Optional[float]
    result: Optional[str]
    notes: Optional[str]

    class Config:
        from_attributes = True


class CLVSummaryResponse(BaseModel):
    n_graded: int
    avg_clv_points: float
    positive_clv_count: int
    positive_clv_pct: float


class PredictionResponse(BaseModel):
    id: int
    created_at: str
    event_id: Optional[str]
    game_date: str
    market: str
    player: str
    line: Optional[float]
    projection: float
    model_over_prob: Optional[float]
    model_under_prob: Optional[float]
    book_over_prob: Optional[float]
    edge: Optional[float]
    model_error: Optional[float]
    recommendation: Optional[str]
    model_version: str
    opponent_name: Optional[str]
    opponent_factor: Optional[float]

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Health & Status
# ---------------------------------------------------------------------------

@router.api_route("/healthz", methods=["GET", "HEAD"], tags=["System"])
def health_check():
    """Health check endpoint for Render, Vercel, and Cloudflare."""
    return {"status": "ok", "app": "dirtywater", "version": "2026.1"}



# ---------------------------------------------------------------------------
# Bet Management & CLV
# ---------------------------------------------------------------------------

@router.get("/api/v1/bets", response_model=list[BetResponse], tags=["Bets"])
def list_bets(db: Session = Depends(get_db)):
    """Retrieve all logged bets (real and paper)."""
    bets = get_all_bets(db)
    return bets


@router.post("/api/v1/bets", response_model=BetResponse, status_code=status.HTTP_201_CREATED, tags=["Bets"])
def create_bet(bet: BetCreateRequest, db: Session = Depends(get_db)):
    """Record a new bet in the bet log."""
    new_bet = insert_bet(db, bet.dict())
    return new_bet


@router.get("/api/v1/bets/clv", response_model=CLVSummaryResponse, tags=["Bets"])
def get_clv_summary(db: Session = Depends(get_db)):
    """Calculate aggregate Closing Line Value metrics."""
    return clv_summary(db)


# ---------------------------------------------------------------------------
# Predictions History
# ---------------------------------------------------------------------------

@router.get("/api/v1/predictions", response_model=list[PredictionResponse], tags=["Predictions"])
def list_predictions(
    game_date: Optional[str] = Query(None, description="Filter by YYYY-MM-DD"),
    market: Optional[str] = Query(None, description="Filter by market (e.g. pitcher_strikeouts)"),
    player: Optional[str] = Query(None, description="Filter by player name"),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """Retrieve historical model predictions and calculated edges."""
    return get_predictions_history(db, game_date=game_date, market=market, player=player, limit=limit)


# ---------------------------------------------------------------------------
# Odds Movement
# ---------------------------------------------------------------------------

@router.get("/api/v1/odds/movement", tags=["Odds"])
def check_line_movement(
    event_id: str = Query(..., description="The Odds API event ID"),
    market: str = Query(..., description="Market identifier"),
    player: str = Query(..., description="Player or team name"),
    db: Session = Depends(get_db),
):
    """Inspect line trajectory from opening to latest snapshot."""
    return get_line_movement(db, event_id=event_id, market=market, player=player)


# ---------------------------------------------------------------------------
# Schedule & Lineup Status
# ---------------------------------------------------------------------------

@router.get("/api/v1/schedule/today", tags=["Schedule"])
def get_today_schedule(db: Session = Depends(get_db)):
    """Get today's scheduled games and lineup confirmation status."""
    games = db.query(GameSchedule).order_by(GameSchedule.game_date.desc(), GameSchedule.game_number.asc()).limit(10).all()
    return [g.to_dict() for g in games]
