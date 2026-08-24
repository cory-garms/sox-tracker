"""
Every book's price is kept, not just the one we bet at.

The Odds API bills per market x region and never per bookmaker: a one-book and
a six-book request for the same market each cost exactly one credit. The whole
US market therefore arrived in every response this project has ever paid for,
and fetch_book_lines already parsed it into `by_book` -- and then the write
kept DraftKings and dropped the rest.

That is the one loss in this repo that cannot be undone. A projection can be
replayed from stored odds; a price nobody stored is gone when the game starts.
"""

from __future__ import annotations

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base, _reconcile_odds_unique_key
from backend.models import OddsSnapshot
from backend.repository import insert_odds_snapshots
from data import odds_history

EVENT = {"id": "evt-1", "commence_time": "2026-08-24T22:41:00Z",
         "home_team": "Miami Marlins", "away_team": "Boston Red Sox"}

# Same player, same instant, three books, three different prices.
BY_BOOK = {
    "Wilyer Abreu": {
        "DraftKings": {"line": 1.5, "over_odds": 128, "under_odds": -171,
                       "book": "DraftKings", "last_update": "2026-08-24T19:30:00Z"},
        "FanDuel":    {"line": 1.5, "over_odds": 134, "under_odds": -178,
                       "book": "FanDuel", "last_update": "2026-08-24T19:29:00Z"},
        "BetMGM":     {"line": 1.5, "over_odds": 120, "under_odds": -160,
                       "book": "BetMGM", "last_update": "2026-08-24T19:28:00Z"},
    },
    "Ceddanne Rafaela": {
        "DraftKings": {"line": 1.5, "over_odds": 143, "under_odds": -192,
                       "book": "DraftKings", "last_update": "2026-08-24T19:30:00Z"},
    },
}


class TestEveryBookReachesTheLog:
    def test_a_row_per_player_per_book(self):
        rows = odds_history.snapshot_rows_by_book(EVENT, "batter_total_bases", BY_BOOK)
        assert len(rows) == 4
        assert {r["book"] for r in rows} == {"DraftKings", "FanDuel", "BetMGM"}

    def test_the_prices_are_not_blended(self):
        """Collapsing books would invent a quote that exists nowhere."""
        rows = odds_history.snapshot_rows_by_book(EVENT, "batter_total_bases", BY_BOOK)
        abreu = {r["book"]: r["over_odds"] for r in rows if r["player"] == "Wilyer Abreu"}
        assert abreu == {"DraftKings": 128, "FanDuel": 134, "BetMGM": 120}

    def test_one_timestamp_for_the_whole_capture(self):
        """
        Books must be comparable within a snapshot. Stamping each row as it is
        written would spread one capture across however long the loop took.
        """
        rows = odds_history.snapshot_rows_by_book(EVENT, "batter_total_bases", BY_BOOK)
        assert len({r["captured_at"] for r in rows}) == 1

    def test_empty_market_logs_nothing(self):
        assert odds_history.snapshot_rows_by_book(EVENT, "batter_total_bases", {}) == []
        assert odds_history.snapshot_rows_by_book(None, "batter_total_bases", BY_BOOK) == []


class TestDedupeKeepsDistinctBooks:
    def test_book_is_part_of_the_identity(self):
        assert "book" in odds_history.KEY

    def test_three_books_survive_a_dedupe(self, tmp_path):
        path = tmp_path / "odds.parquet"
        rows = odds_history.snapshot_rows_by_book(EVENT, "batter_total_bases", BY_BOOK)
        assert odds_history.append_snapshot(rows, path) == 4
        # Re-writing the identical capture adds nothing.
        assert odds_history.append_snapshot(rows, path) == 0
        assert len(pd.read_parquet(path)) == 4


class TestTheDatabaseAcceptsThem:
    @pytest.fixture
    def session(self, tmp_path):
        engine = create_engine(f"sqlite:///{tmp_path/'o.db'}")
        Base.metadata.create_all(engine)
        s = sessionmaker(bind=engine)()
        try:
            yield s
        finally:
            s.close()

    def test_multiple_books_are_stored_not_deduped(self, session):
        rows = odds_history.snapshot_rows_by_book(EVENT, "batter_total_bases", BY_BOOK)
        assert insert_odds_snapshots(session, rows) == 4
        session.commit()
        abreu = session.query(OddsSnapshot).filter_by(player="Wilyer Abreu").all()
        assert {o.book for o in abreu} == {"DraftKings", "FanDuel", "BetMGM"}

    def test_reinserting_the_same_capture_is_a_no_op(self, session):
        """The deploy migrates the whole parquet on every build."""
        rows = odds_history.snapshot_rows_by_book(EVENT, "batter_total_bases", BY_BOOK)
        insert_odds_snapshots(session, rows)
        session.commit()
        assert insert_odds_snapshots(session, rows) == 0

    def test_a_row_without_a_book_still_round_trips(self, session):
        """
        The guard and the insert must agree on the default, or the row is
        stored under one key and searched for under another and re-inserted
        on every deploy forever.
        """
        row = dict(captured_at="2026-08-24T19:30:00Z", event_id="evt-1",
                   market="h2h", player="Boston Red Sox", line=None,
                   over_odds=-124, under_odds=115, book=None, last_update=None)
        assert insert_odds_snapshots(session, [row]) == 1
        session.commit()
        assert insert_odds_snapshots(session, [row]) == 0


class TestConstraintReconciliation:
    def test_sqlite_is_left_alone(self, tmp_path):
        """
        SQLite cannot drop an inline table constraint and does not need to:
        test and dev databases are created fresh from the current model.
        """
        engine = create_engine(f"sqlite:///{tmp_path/'o.db'}")
        Base.metadata.create_all(engine)
        assert _reconcile_odds_unique_key(engine) is False

    def test_the_model_key_includes_book(self):
        cons = {
            tuple(c.name for c in con.columns)
            for con in OddsSnapshot.__table__.constraints
            if con.__class__.__name__ == "UniqueConstraint"
        }
        assert ("captured_at", "event_id", "market", "player", "book") in cons
