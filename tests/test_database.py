"""
Tests for backend database models, repositories, and migration.
Guarantees 100% offline, isolated execution with SQLite in-memory.
"""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import MetaData, Table, create_engine, inspect
from sqlalchemy.orm import sessionmaker

from backend.database import Base, init_db, sync_schema
from backend.models import BetLog, ModelPrediction, OddsSnapshot
from backend.repository import (
    clv_summary,
    get_all_bets,
    get_all_odds_snapshots,
    get_line_movement,
    get_predictions_history,
    grade_bets_from_snapshots,
    insert_bet,
    insert_model_predictions,
    insert_odds_snapshots,
)


@pytest.fixture
def db_session():
    """Create an isolated in-memory SQLite database session for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()


def test_insert_odds_snapshots_idempotent(db_session):
    """Guards against duplicate odds snapshot entries on identical composite keys."""
    rows = [
        {
            "captured_at": "2026-08-23T12:00:00Z",
            "event_id": "event_123",
            "commence_time": "2026-08-23T18:00:00Z",
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "market": "pitcher_strikeouts",
            "player": "Sonny Gray",
            "line": 4.5,
            "over_odds": -130,
            "under_odds": +100,
            "book": "DraftKings",
        },
        # Duplicate row
        {
            "captured_at": "2026-08-23T12:00:00Z",
            "event_id": "event_123",
            "commence_time": "2026-08-23T18:00:00Z",
            "home_team": "Boston Red Sox",
            "away_team": "New York Yankees",
            "market": "pitcher_strikeouts",
            "player": "Sonny Gray",
            "line": 4.5,
            "over_odds": -130,
            "under_odds": +100,
            "book": "DraftKings",
        },
    ]

    inserted = insert_odds_snapshots(db_session, rows)
    assert inserted == 1

    snapshots = get_all_odds_snapshots(db_session)
    assert len(snapshots) == 1
    assert snapshots[0].player == "Sonny Gray"
    assert snapshots[0].line == 4.5


def test_get_line_movement_detection(db_session):
    """Guards against false line movement reports and verifies drift calculation."""
    # First snapshot: 4.5 (-130)
    insert_odds_snapshots(db_session, [{
        "captured_at": "2026-08-23T10:00:00Z",
        "event_id": "event_123",
        "market": "pitcher_strikeouts",
        "player": "Sonny Gray",
        "line": 4.5,
        "over_odds": -130,
        "under_odds": +100,
    }])

    mv_initial = get_line_movement(db_session, "event_123", "pitcher_strikeouts", "Sonny Gray")
    assert not mv_initial["has_moved"]
    assert mv_initial["n_snapshots"] == 1

    # Second snapshot with price move: 4.5 (-155)
    insert_odds_snapshots(db_session, [{
        "captured_at": "2026-08-23T15:00:00Z",
        "event_id": "event_123",
        "market": "pitcher_strikeouts",
        "player": "Sonny Gray",
        "line": 4.5,
        "over_odds": -155,
        "under_odds": +125,
    }])

    mv_after = get_line_movement(db_session, "event_123", "pitcher_strikeouts", "Sonny Gray")
    assert mv_after["has_moved"]
    assert mv_after["n_snapshots"] == 2
    assert mv_after["first_over"] == -130
    assert mv_after["latest_over"] == -155


def test_insert_model_predictions(db_session):
    """Guards against unarchived or missing prediction fields."""
    predictions = [
        {
            "created_at": "2026-08-23T12:00:00Z",
            "event_id": "event_123",
            "game_date": "2026-08-23",
            "market": "pitcher_strikeouts",
            "player": "Sonny Gray",
            "line": 4.5,
            "projection": 5.45,
            "model_over_prob": 0.672,
            "model_under_prob": 0.328,
            "book_over_prob": 0.573,
            "edge": 0.099,
            "model_error": 0.45,
            "recommendation": "OVER 4.5",
            "model_version": "v1.2-regressed-opponent",
            "opponent_name": "Yankees",
            "opponent_factor": 1.05,
            "details_json": '{"pa_regressed": 450}',
        }
    ]

    count = insert_model_predictions(db_session, predictions)
    assert count == 1

    history = get_predictions_history(db_session, game_date="2026-08-23", market="pitcher_strikeouts")
    assert len(history) == 1
    assert history[0].player == "Sonny Gray"
    assert history[0].projection == 5.45
    assert history[0].recommendation == "OVER 4.5"


def test_bet_logging_and_clv_grading(db_session):
    """Guards against incorrect CLV calculation and bet settlement."""
    # Place a bet at +158
    bet = insert_bet(db_session, {
        "placed_at": "2026-08-23T11:00:00Z",
        "event_id": "event_999",
        "game_date": "2026-08-23",
        "market": "h2h",
        "selection": "Athletics",
        "side": "Moneyline",
        "price": 158.0,
        "stake": 1.0,
        "promo": "boost_50",
    })
    assert bet.id is not None
    assert bet.closing_price is None

    # Snapshot pre-game closing price at +140 (market moved in bet's favor)
    insert_odds_snapshots(db_session, [{
        "captured_at": "2026-08-23T17:55:00Z",
        "commence_time": "2026-08-23T18:05:00Z",
        "event_id": "event_999",
        "market": "h2h",
        "player": "Athletics",
        "over_odds": 140,
        "under_odds": -165,
    }])

    # Grade bets
    graded = grade_bets_from_snapshots(db_session)
    assert graded == 1

    updated_bet = get_all_bets(db_session)[0]
    assert updated_bet.closing_price == 140.0
    assert updated_bet.clv_diff is not None
    # +140 closing prob is higher than +158 taken prob -> positive CLV
    assert updated_bet.clv_diff > 0

    summary = clv_summary(db_session)
    assert summary["n_graded"] == 1
    assert summary["positive_clv_count"] == 1
    assert summary["avg_clv_points"] > 0


class TestSchemaDriftBreaksTheDeploy:
    """
    Render's build step ran migrate_parquet_to_db.py against a database whose
    model_predictions table had been created by an earlier deploy. When
    ModelPrediction gained player_id / game_pk / actual / outcome / settled_at,
    create_all() left that existing table alone -- it only creates missing
    *tables* -- and every insert died with "column ... does not exist". The
    build failed on every push, Render kept serving the last build that
    worked, and the site silently went stale for a day.
    """

    def _engine_missing(self, tmp_path, drop: set[str]):
        """A database whose model_predictions predates the new columns."""
        engine = create_engine(f"sqlite:///{tmp_path / 'drift.db'}")
        meta = MetaData()
        for table in Base.metadata.tables.values():
            cols = [
                c._copy() for c in table.columns
                if not (table.name == "model_predictions" and c.name in drop)
            ]
            Table(table.name, meta, *cols)
        meta.create_all(engine)
        return engine

    def test_missing_columns_are_added(self, tmp_path):
        drop = {"player_id", "game_pk", "actual", "outcome", "settled_at"}
        engine = self._engine_missing(tmp_path, drop)

        assert drop.isdisjoint(
            {c["name"] for c in inspect(engine).get_columns("model_predictions")}
        )

        init_db(engine)

        present = {c["name"] for c in inspect(engine).get_columns("model_predictions")}
        assert drop <= present

    def test_insert_succeeds_after_sync(self, tmp_path):
        """The actual failure: the build inserts, and the insert must not raise."""
        engine = self._engine_missing(
            tmp_path, {"player_id", "game_pk", "actual", "outcome", "settled_at"}
        )
        init_db(engine)

        session = sessionmaker(bind=engine)()
        try:
            insert_model_predictions(session, [{
                "created_at": "2026-08-23T12:00:00Z",
                "game_date": "2026-08-23",
                "market": "batter_total_bases",
                "player": "Wilyer Abreu",
                "line": 1.5,
                "projection": 1.68,
                "player_id": 677800,
                "game_pk": 824734,
                "actual": 0.0,
                "outcome": "under",
                "settled_at": "2026-08-23T20:30:18+00:00",
            }])
            session.commit()
            row = session.query(ModelPrediction).one()
            assert row.player_id == 677800
            assert row.outcome == "under"
        finally:
            session.close()

    def test_sync_is_idempotent(self, tmp_path):
        """Deploys run this on every build; the second one must be a no-op."""
        engine = self._engine_missing(tmp_path, {"actual", "outcome"})
        assert set(sync_schema(engine)) == {
            "model_predictions.actual", "model_predictions.outcome",
        }
        assert sync_schema(engine) == []

    def test_up_to_date_database_is_untouched(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path / 'current.db'}")
        Base.metadata.create_all(engine)
        assert sync_schema(engine) == []
