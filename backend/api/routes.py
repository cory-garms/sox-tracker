"""
FastAPI REST API routes for dirtywater.corygarms.com.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import pandas as pd
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

import config
from analysis.standings import season_record
from analysis.streaks import current_streak, longest_streak, played_in_order
from backend.database import get_db
from backend.models import GameSchedule, ModelPrediction
from backend.repository import (
    clv_summary,
    get_all_bets,
    get_line_movement,
    get_predictions_history,
    insert_bet,
)
from data.fetcher import Fetcher

log = logging.getLogger(__name__)

router = APIRouter()


def _load(table: str) -> pd.DataFrame:
    """
    Read a cached parquet table, or 503 if the cache has not been built.

    The season tables live in parquet, not Postgres — Postgres holds the odds
    and betting history. A missing cache is a deployment state, not a client
    error, so it is 503 rather than 404.
    """
    try:
        return Fetcher(team_id=config.TEAM_ID, season=config.SEASON).load(table)
    except FileNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"The '{table}' cache has not been built yet for {config.TEAM_ABBR} {config.SEASON}.",
        )


def _json_safe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """NaN is not valid JSON; pandas hands it back for every missing cell."""
    return [
        {k: (None if isinstance(v, float) and pd.isna(v) else v) for k, v in row.items()}
        for row in records
    ]


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
    """
    Health check for Render, and the only place that can answer "is the site
    actually current?".

    Reports the commit this process was built from and the newest game the
    cache on *this instance* knows about. Both matter and they fail
    differently: a failed deploy leaves an old commit serving fresh-looking
    pages, and a failed refresh leaves the right commit serving old data.
    scripts/check_deploy.py reads exactly this.

    Never raises. A health check that 500s because it could not read a parquet
    file takes the service down to report that the service is up.
    """
    payload = {
        "status": "ok",
        "app": "dirtywater",
        "version": "2026.1",
        "commit": config.DEPLOY_COMMIT or "unknown",
        "data_through": None,
    }
    try:
        games = _load("games")
        if not games.empty and "game_date" in games.columns:
            payload["data_through"] = str(games["game_date"].max())[:10]
    except Exception:
        pass
    return payload



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
    db.commit()
    db.refresh(new_bet)
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


# ---------------------------------------------------------------------------
# Season Games & Standings
# ---------------------------------------------------------------------------

@router.get("/api/v1/games", tags=["Season"])
def list_games(
    result: Optional[str] = Query(None, description="Filter by result: W, L or T"),
    limit: int = Query(200, ge=1, le=200),
):
    """
    The season game log, in the order the games were actually played.

    Ordered by played_in_order rather than game_pk: MLB assigns gamePk at
    scheduling time, so a rained-out game made up as game 1 of a later
    doubleheader carries a lower pk than the nightcap it precedes.
    """
    games = _load("games")
    finished = played_in_order(games)

    if result:
        finished = finished[finished["result"].str.upper() == result.upper()]

    cols = [
        c for c in (
            "game_pk", "game_date", "game_number", "game_num", "opponent_id",
            "is_home", "runs_scored", "runs_allowed", "result", "innings",
            "day_night", "venue", "status",
        ) if c in finished.columns
    ]
    rows = finished[cols].tail(limit)

    return {
        "team": config.TEAM_ABBR,
        "season": config.SEASON,
        "count": int(len(rows)),
        "games": _json_safe(rows.to_dict("records")),
    }


@router.get("/api/v1/standings", tags=["Season"])
def get_standings():
    """Season record, Pythagorean expectation, splits, and current streak."""
    games = _load("games")
    record = season_record(games)
    if not record:
        return {"team": config.TEAM_ABBR, "season": config.SEASON, "record": {}}

    streak_kind, streak_len = current_streak(games)
    return {
        "team": config.TEAM_ABBR,
        "season": config.SEASON,
        "record": record,
        "streak": {"type": streak_kind, "length": streak_len},
        "longest_win_streak": longest_streak(games, "W"),
        "longest_loss_streak": longest_streak(games, "L"),
    }


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

@router.get("/api/v1/analytics/turnaround", tags=["Analytics"])
def get_turnaround():
    """
    Net games above/below .500 across the season, by game number.

    This is the series behind the dashboard's turnaround curve: the running
    (wins - losses) after each game played.
    """
    finished = played_in_order(_load("games"))
    if finished.empty:
        return {"team": config.TEAM_ABBR, "season": config.SEASON, "points": []}

    wins = (finished["result"] == "W").cumsum()
    losses = (finished["result"] == "L").cumsum()
    net = (wins - losses).tolist()

    points = [
        {
            "game_number": i,
            "game_date": str(date),
            "result": res,
            "net_above_500": int(n),
        }
        for i, (date, res, n) in enumerate(
            zip(finished["game_date"], finished["result"], net), start=1
        )
    ]

    peak = max(points, key=lambda p: p["net_above_500"])
    trough = min(points, key=lambda p: p["net_above_500"])
    return {
        "team": config.TEAM_ABBR,
        "season": config.SEASON,
        "games_played": len(points),
        "current_net": points[-1]["net_above_500"],
        "peak": peak,
        "trough": trough,
        "points": points,
    }


@router.get("/api/v1/analytics/matchup/today", tags=["Analytics"])
def get_today_matchup(db: Session = Depends(get_db)):
    """
    Today's pre-game picture: opponent, probable starters, and bullpen
    availability filtered to the active roster.

    Reads the schedule row the background scheduler syncs, and the bullpen from
    the parquet pitching log. Serves what it has rather than failing whole: a
    missing schedule row still returns the bullpen.
    """
    from datetime import date as _date

    from analysis.matchup import bullpen_availability

    today = _date.today().isoformat()

    scheduled = (
        db.query(GameSchedule)
        .filter(GameSchedule.game_date == today)
        .order_by(GameSchedule.game_number.asc())
        .all()
    )

    pitching = _load("pitching")
    roster = _load("roster")
    active_pitchers = (
        set(roster[roster["position"] == "P"]["player_name"].dropna().unique())
        if not roster.empty else None
    )

    probables = {
        g.probable_home_name for g in scheduled if g.probable_home_name
    } | {
        g.probable_away_name for g in scheduled if g.probable_away_name
    }
    if active_pitchers is not None:
        active_pitchers = active_pitchers - probables

    bullpen = bullpen_availability(
        pitching, ref_date_str=today, days=3, active_pitcher_names=active_pitchers,
    )

    return {
        "team": config.TEAM_ABBR,
        "season": config.SEASON,
        "date": today,
        "games": [g.to_dict() for g in scheduled],
        "bullpen": _json_safe(bullpen.to_dict("records")) if not bullpen.empty else [],
    }


# ---------------------------------------------------------------------------
# Refresh Webhook
# ---------------------------------------------------------------------------

class RefreshResponse(BaseModel):
    status: str
    refreshed: list[str]
    errors: dict[str, str]


def _require_refresh_token(x_refresh_token: str = Header(default="")) -> None:
    """
    Gate the refresh webhook on a shared secret.

    No token configured disables the route outright rather than leaving it
    open — re-ingestion hits the MLB API and can spend odds credits, so an
    unauthenticated caller must never be able to trigger it.
    """
    import hmac

    if not config.REFRESH_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Refresh webhook is disabled: REFRESH_TOKEN is not configured.",
        )
    # Constant-time compare so the response time does not leak the token.
    if not hmac.compare_digest(x_refresh_token, config.REFRESH_TOKEN):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Refresh-Token header.",
        )


@router.post(
    "/api/v1/refresh",
    response_model=RefreshResponse,
    tags=["System"],
    dependencies=[Depends(_require_refresh_token)],
)
def trigger_refresh(
    tables: Optional[str] = Query(
        None,
        description="Comma-separated tables to refresh. Default: games,batting,pitching,roster",
    ),
):
    """
    Re-ingest the parquet cache after a game goes final.

    Runs synchronously and reports per-table outcomes, so a caller (the
    post-game workflow) learns which tables actually refreshed instead of
    getting a 202 and no way to tell. One table failing does not abandon the
    rest.
    """
    from data.roster import fetch_roster

    known = ("roster", "games", "batting", "pitching", "fielding")
    wanted = (
        [t.strip() for t in tables.split(",") if t.strip()]
        if tables else ["roster", "games", "batting", "pitching"]
    )

    refreshed: list[str] = []
    errors: dict[str, str] = {}

    unknown = [t for t in wanted if t not in known]
    for t in unknown:
        errors[t] = "unknown table"
    # Dependency order, not request order: the per-game log tables are built by
    # walking the games table, so games is always refreshed before them.
    ordered = [t for t in known if t in wanted]

    fetcher = Fetcher(team_id=config.TEAM_ID, season=config.SEASON, force_refresh=True)
    games_df: pd.DataFrame | None = None
    needs_games = any(t in ordered for t in ("batting", "pitching", "fielding"))

    if "games" in ordered or needs_games:
        try:
            games_df = fetcher.fetch_games()
            if "games" in ordered:
                refreshed.append("games")
        except Exception as e:  # noqa: BLE001 — report, never 500 the whole webhook
            log.warning("Refresh of games failed: %s", e)
            errors["games"] = str(e)

    for table in ordered:
        if table == "games":
            continue
        try:
            if table == "roster":
                fetch_roster(config.TEAM_ID, config.SEASON, fetcher.client, True)
            else:
                if games_df is None:
                    errors[table] = "skipped: games refresh failed"
                    continue
                getattr(fetcher, f"fetch_{table}_logs")(games_df)
            refreshed.append(table)
        except Exception as e:  # noqa: BLE001
            log.warning("Refresh of %s failed: %s", table, e)
            errors[table] = str(e)

    return RefreshResponse(
        status="ok" if not errors else "partial",
        refreshed=refreshed,
        errors=errors,
    )
