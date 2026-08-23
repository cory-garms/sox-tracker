"""
Database repository / data access layer for dirtywater backend.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Sequence

import pandas as pd
from sqlalchemy import desc, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from backend.models import BetLog, GameSchedule, ModelPrediction, OddsSnapshot
from client.odds_math import american_to_implied_prob

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Odds Snapshots
# ---------------------------------------------------------------------------

def insert_odds_snapshots(session: Session, rows: list[dict[str, Any]]) -> int:
    """
    Insert odds snapshot rows into the database, ignoring duplicates on the composite key.
    Returns the number of rows inserted.
    """
    if not rows:
        return 0

    inserted_count = 0
    for r in rows:
        captured_at = r.get("captured_at") or datetime.now(timezone.utc).isoformat(timespec="seconds")
        event_id = str(r.get("event_id", ""))
        market = str(r.get("market", ""))
        player = str(r.get("player", ""))

        if not event_id or not market or not player:
            continue

        # Check existing to ensure idempotency across SQLite & Postgres
        existing = session.execute(
            select(OddsSnapshot).where(
                OddsSnapshot.captured_at == captured_at,
                OddsSnapshot.event_id == event_id,
                OddsSnapshot.market == market,
                OddsSnapshot.player == player,
            )
        ).scalar_one_or_none()

        if existing is None:
            obj = OddsSnapshot(
                captured_at=captured_at,
                event_id=event_id,
                commence_time=r.get("commence_time"),
                home_team=r.get("home_team"),
                away_team=r.get("away_team"),
                market=market,
                player=player,
                line=float(r["line"]) if r.get("line") is not None and not pd.isna(r["line"]) else None,
                over_odds=int(r["over_odds"]) if r.get("over_odds") is not None and not pd.isna(r["over_odds"]) else None,
                under_odds=int(r["under_odds"]) if r.get("under_odds") is not None and not pd.isna(r["under_odds"]) else None,
                book=r.get("book", "DraftKings"),
                last_update=r.get("last_update"),
            )
            session.add(obj)
            inserted_count += 1

    session.flush()
    log.info("Inserted %d new odds snapshot rows", inserted_count)
    return inserted_count


def latest_lines_by_market(
    session: Session,
    market: str,
    event_id: str | None = None,
) -> dict[str, dict[str, Any]]:
    """
    Rebuild a book-line map from the odds already stored, spending no quota.

    Returns the same shape the models take from ``fetch_book_lines`` —
    ``{player: {"line": float, "over_odds": int, "under_odds": int}}`` — using
    each player's most recently captured snapshot.

    This exists so prediction archival does not have to buy prices a second
    time. The GitHub Actions build already fetches every market four times a
    day and commits the result; anything running afterwards can read that
    record instead of re-purchasing it.
    """
    stmt = select(OddsSnapshot).where(OddsSnapshot.market == market)
    if event_id:
        stmt = stmt.where(OddsSnapshot.event_id == event_id)
    stmt = stmt.order_by(OddsSnapshot.captured_at.asc())

    lines: dict[str, dict[str, Any]] = {}
    for snap in session.execute(stmt).scalars():
        if snap.line is None:
            continue
        # Ascending order means the last write per player wins, which is the
        # most recent capture.
        lines[snap.player] = {
            "line": float(snap.line),
            "over_odds": snap.over_odds,
            "under_odds": snap.under_odds,
        }
    return lines


def latest_event_id(session: Session) -> str:
    """The event id of the most recent odds snapshot, or "" if none stored."""
    row = session.execute(
        select(OddsSnapshot.event_id).order_by(desc(OddsSnapshot.captured_at)).limit(1)
    ).scalar_one_or_none()
    return row or ""


def get_all_odds_snapshots(session: Session) -> list[OddsSnapshot]:
    """Retrieve all odds snapshots ordered by captured_at."""
    return list(session.execute(select(OddsSnapshot).order_by(OddsSnapshot.captured_at.asc())).scalars().all())


def get_line_movement(
    session: Session,
    event_id: str,
    market: str,
    player: str,
) -> dict[str, Any]:
    """
    Compute line movement from the historical snapshots of a given player / market.
    Returns: {"has_moved": bool, "first_captured": ..., "first_line": ..., "first_price": ...,
              "latest_captured": ..., "latest_line": ..., "latest_price": ..., "n_snapshots": ...}
    """
    stmt = (
        select(OddsSnapshot)
        .where(
            OddsSnapshot.event_id == event_id,
            OddsSnapshot.market == market,
            OddsSnapshot.player == player,
        )
        .order_by(OddsSnapshot.captured_at.asc())
    )
    rows = list(session.execute(stmt).scalars().all())
    if not rows:
        return {"has_moved": False, "n_snapshots": 0}

    first = rows[0]
    latest = rows[-1]

    has_moved = (
        len(rows) > 1
        and (
            first.line != latest.line
            or first.over_odds != latest.over_odds
            or first.under_odds != latest.under_odds
        )
    )

    return {
        "has_moved": has_moved,
        "n_snapshots": len(rows),
        "first_captured": first.captured_at,
        "first_line": first.line,
        "first_over": first.over_odds,
        "first_under": first.under_odds,
        "latest_captured": latest.captured_at,
        "latest_line": latest.line,
        "latest_over": latest.over_odds,
        "latest_under": latest.under_odds,
    }


# ---------------------------------------------------------------------------
# Model Predictions Archival
# ---------------------------------------------------------------------------

def _opt_int(value: Any) -> int | None:
    """Nullable integer column from a value that may be NA, NaN or a string."""
    try:
        if value is None or pd.isna(value):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def insert_model_predictions(session: Session, predictions: list[dict[str, Any]]) -> int:
    """
    Archive a batch of model predictions (e.g. pitcher K, batter TB, F5, ML win%).
    """
    if not predictions:
        return 0

    count = 0
    for p in predictions:
        obj = ModelPrediction(
            created_at=p.get("created_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            event_id=p.get("event_id"),
            game_date=str(p.get("game_date", "")),
            market=str(p.get("market", "")),
            player=str(p.get("player", "")),
            line=float(p["line"]) if p.get("line") is not None and not pd.isna(p["line"]) else None,
            projection=float(p["projection"]),
            model_over_prob=float(p["model_over_prob"]) if p.get("model_over_prob") is not None and not pd.isna(p["model_over_prob"]) else None,
            model_under_prob=float(p["model_under_prob"]) if p.get("model_under_prob") is not None and not pd.isna(p["model_under_prob"]) else None,
            book_over_prob=float(p["book_over_prob"]) if p.get("book_over_prob") is not None and not pd.isna(p["book_over_prob"]) else None,
            edge=float(p["edge"]) if p.get("edge") is not None and not pd.isna(p["edge"]) else None,
            model_error=float(p["model_error"]) if p.get("model_error") is not None and not pd.isna(p["model_error"]) else None,
            recommendation=p.get("recommendation"),
            model_version=p.get("model_version", "v1.0"),
            opponent_name=p.get("opponent_name"),
            opponent_factor=float(p["opponent_factor"]) if p.get("opponent_factor") is not None and not pd.isna(p["opponent_factor"]) else None,
            details_json=p.get("details_json"),
            player_id=_opt_int(p.get("player_id")),
            game_pk=_opt_int(p.get("game_pk")),
            actual=float(p["actual"]) if p.get("actual") is not None and not pd.isna(p["actual"]) else None,
            outcome=p.get("outcome") or "",
            settled_at=p.get("settled_at") or None,
        )
        session.add(obj)
        count += 1

    session.flush()
    log.info("Archived %d model predictions", count)
    return count


def get_predictions_history(
    session: Session,
    game_date: str | None = None,
    market: str | None = None,
    player: str | None = None,
    limit: int = 100,
) -> list[ModelPrediction]:
    """Retrieve historical model predictions matching filters."""
    stmt = select(ModelPrediction)
    if game_date:
        stmt = stmt.where(ModelPrediction.game_date == game_date)
    if market:
        stmt = stmt.where(ModelPrediction.market == market)
    if player:
        stmt = stmt.where(ModelPrediction.player == player)
    stmt = stmt.order_by(desc(ModelPrediction.created_at)).limit(limit)
    return list(session.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------
# Bet Log & CLV Grading
# ---------------------------------------------------------------------------

def insert_bet(session: Session, bet_data: dict[str, Any]) -> BetLog:
    """Record a real or paper bet into the bet log."""
    obj = BetLog(
        placed_at=bet_data.get("placed_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        event_id=bet_data.get("event_id"),
        game_date=bet_data.get("game_date"),
        market=str(bet_data.get("market", "")),
        selection=str(bet_data.get("selection", "")),
        side=str(bet_data.get("side", "")),
        line=float(bet_data["line"]) if bet_data.get("line") is not None and not pd.isna(bet_data["line"]) else None,
        price=float(bet_data["price"]),
        book=bet_data.get("book", "DraftKings"),
        stake=float(bet_data.get("stake", 0.0)),
        promo=bet_data.get("promo", ""),
        model_prob=float(bet_data["model_prob"]) if bet_data.get("model_prob") is not None and not pd.isna(bet_data["model_prob"]) else None,
        consensus_prob=float(bet_data["consensus_prob"]) if bet_data.get("consensus_prob") is not None and not pd.isna(bet_data["consensus_prob"]) else None,
        closing_price=float(bet_data["closing_price"]) if bet_data.get("closing_price") is not None and not pd.isna(bet_data["closing_price"]) else None,
        clv_diff=float(bet_data["clv_diff"]) if bet_data.get("clv_diff") is not None and not pd.isna(bet_data["clv_diff"]) else None,
        result=bet_data.get("result", ""),
        notes=bet_data.get("notes", ""),
    )
    session.add(obj)
    session.flush()
    return obj


def get_all_bets(session: Session) -> list[BetLog]:
    """Retrieve all logged bets."""
    return list(session.execute(select(BetLog).order_by(desc(BetLog.placed_at))).scalars().all())


def grade_bets_from_snapshots(session: Session) -> int:
    """
    Grade pending bets with their closing prices from OddsSnapshot and compute CLV.
    Returns the number of bets updated.
    """
    bets = list(session.execute(select(BetLog)).scalars().all())
    updated_count = 0

    for bet in bets:
        if not bet.event_id:
            continue

        # Look for the last pre-game snapshot for this market & selection
        stmt = (
            select(OddsSnapshot)
            .where(
                OddsSnapshot.event_id == bet.event_id,
                OddsSnapshot.market == bet.market,
                OddsSnapshot.player == bet.selection,
            )
            .order_by(OddsSnapshot.captured_at.desc())
        )
        snapshots = list(session.execute(stmt).scalars().all())
        if not snapshots:
            continue

        # Filter pre-game only (captured_at <= commence_time)
        closing_snapshot = None
        for s in snapshots:
            if s.commence_time and s.captured_at <= s.commence_time:
                closing_snapshot = s
                break
            elif not s.commence_time:
                closing_snapshot = s
                break

        if not closing_snapshot:
            continue

        # Determine closing price for the bet's side
        closing_price = None
        if bet.side.lower() == "over":
            closing_price = closing_snapshot.over_odds
        elif bet.side.lower() == "under":
            closing_price = closing_snapshot.under_odds
        elif bet.side.lower() in ("moneyline", "h2h"):
            closing_price = closing_snapshot.over_odds or closing_snapshot.under_odds

        if closing_price is not None:
            bet.closing_price = float(closing_price)
            # Calculate CLV difference in implied probability points
            taken_implied = american_to_implied_prob(bet.price)
            closing_implied = american_to_implied_prob(closing_price)
            # Positive CLV = book moved toward our bet (higher closing implied prob vs price taken)
            bet.clv_diff = float((closing_implied - taken_implied) * 100.0)
            updated_count += 1

    session.flush()
    return updated_count


def clv_summary(session: Session) -> dict[str, Any]:
    """
    Compute CLV aggregate metrics across all graded bets in the database.
    """
    bets = list(session.execute(select(BetLog).where(BetLog.closing_price.isnot(None))).scalars().all())
    if not bets:
        return {
            "n_graded": 0,
            "avg_clv_points": 0.0,
            "positive_clv_count": 0,
            "positive_clv_pct": 0.0,
        }

    clv_values = [b.clv_diff for b in bets if b.clv_diff is not None]
    if not clv_values:
        return {"n_graded": len(bets), "avg_clv_points": 0.0, "positive_clv_count": 0, "positive_clv_pct": 0.0}

    pos_count = sum(1 for c in clv_values if c > 0)
    return {
        "n_graded": len(clv_values),
        "avg_clv_points": float(sum(clv_values) / len(clv_values)),
        "positive_clv_count": pos_count,
        "positive_clv_pct": float((pos_count / len(clv_values)) * 100.0),
    }


# ---------------------------------------------------------------------------
# Game Schedules & Lineups
# ---------------------------------------------------------------------------

def upsert_game_schedule(session: Session, game_data: dict[str, Any]) -> GameSchedule:
    """Upsert a game schedule row."""
    game_pk = int(game_data["game_pk"])
    existing = session.execute(
        select(GameSchedule).where(GameSchedule.game_pk == game_pk)
    ).scalar_one_or_none()

    if existing is None:
        existing = GameSchedule(game_pk=game_pk)
        session.add(existing)

    for k, v in game_data.items():
        if hasattr(existing, k):
            setattr(existing, k, v)

    existing.last_synced_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    session.flush()
    return existing
