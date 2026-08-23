"""
Tests for FastAPI REST API endpoints.
Runs 100% offline using FastAPI TestClient with an isolated in-memory SQLite database.
"""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sqlalchemy.pool import StaticPool

import config
from backend.database import Base, get_db
from backend.main import app
from backend.repository import insert_odds_snapshots


@pytest.fixture
def client_with_db():
    """Create a TestClient with an isolated in-memory SQLite database."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    # Seed initial test data
    with TestingSessionLocal() as session:
        insert_odds_snapshots(session, [{
            "captured_at": "2026-08-23T12:00:00Z",
            "event_id": "test_event_1",
            "market": "pitcher_strikeouts",
            "player": "Sonny Gray",
            "line": 4.5,
            "over_odds": -130,
            "under_odds": +100,
        }])
        session.commit()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_healthz_endpoint(client_with_db):
    """Guards that the health check endpoint returns 200 OK."""
    response = client_with_db.get("/healthz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app"] == "dirtywater"


def test_create_and_list_bets(client_with_db):
    """Guards bet logging via REST API and list query."""
    payload = {
        "selection": "Athletics",
        "market": "h2h",
        "side": "Moneyline",
        "price": 158.0,
        "stake": 1.0,
        "promo": "boost_50",
        "book": "DraftKings",
        "event_id": "test_event_1",
        "game_date": "2026-08-23",
        "notes": "Testing API creation",
    }

    create_resp = client_with_db.post("/api/v1/bets", json=payload)
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["id"] is not None
    assert created["selection"] == "Athletics"
    assert created["price"] == 158.0

    list_resp = client_with_db.get("/api/v1/bets")
    assert list_resp.status_code == 200
    bets = list_resp.json()
    assert len(bets) >= 1
    assert any(b["selection"] == "Athletics" for b in bets)


def test_clv_summary_endpoint(client_with_db):
    """Guards the CLV summary API endpoint."""
    resp = client_with_db.get("/api/v1/bets/clv")
    assert resp.status_code == 200
    data = resp.json()
    assert "n_graded" in data
    assert "avg_clv_points" in data
    assert "positive_clv_pct" in data


def test_odds_movement_endpoint(client_with_db):
    """Guards the odds line movement query endpoint."""
    resp = client_with_db.get(
        "/api/v1/odds/movement",
        params={
            "event_id": "test_event_1",
            "market": "pitcher_strikeouts",
            "player": "Sonny Gray",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["n_snapshots"] == 1
    assert data["first_line"] == 4.5


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/board",
        "/models",
        "/matchup",
        "/method",
        "/dashboard",
        "/leaders",
        "/streaks",
        "/track_record",
        "/record",
        "/track_record_BOS_2026.html",
        "/index.html",
        "/models_BOS_2026.html",
        "/tonights_board_BOS_2026.html",
        "/matchup_BOS_2026.html",
        "/method_BOS_2026.html",
        "/dashboard_BOS_2026.html",
        "/leaders_BOS_2026.html",
        "/streak_records_BOS_2026.html",
    ],
)
def test_dashboard_html_routes(client_with_db, path):
    """Guards that all navigation tab URLs and clean slugs return 200 OK."""
    resp = client_with_db.get(path)
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Season, standings and analytics routes
#
# The regression these guard: HANDOFF_GUIDE and the API docs listed
# /api/v1/games, /api/v1/standings and the analytics routes as if they were
# live. None of them existed — the router stopped at /schedule/today.
#
# The season tables live in parquet, so these stub the cache rather than
# reading data/cache. The suite stays runnable with no cache built.
# ---------------------------------------------------------------------------

FAKE_GAMES = pd.DataFrame([
    # A doubleheader whose game 1 carries the *higher* pk, so a pk sort would
    # invert the pair and break the running record.
    {"game_pk": 900, "game_date": "2026-04-01", "game_number": 1, "game_num": 1,
     "opponent_id": 147, "is_home": True, "runs_scored": 5, "runs_allowed": 2,
     "result": "W", "innings": 9, "day_night": "D", "venue": "Fenway Park", "status": "Final"},
    {"game_pk": 903, "game_date": "2026-04-02", "game_number": 1, "game_num": 2,
     "opponent_id": 147, "is_home": True, "runs_scored": 1, "runs_allowed": 4,
     "result": "L", "innings": 9, "day_night": "D", "venue": "Fenway Park", "status": "Final"},
    {"game_pk": 901, "game_date": "2026-04-02", "game_number": 2, "game_num": 3,
     "opponent_id": 147, "is_home": True, "runs_scored": 7, "runs_allowed": 3,
     "result": "W", "innings": 9, "day_night": "N", "venue": "Fenway Park", "status": "Final"},
])

FAKE_PITCHING = pd.DataFrame([
    {"player_name": "Reliever A", "game_date": "2026-04-01", "is_starter": False,
     "pitches": 18, "game_pk": 900},
    {"player_name": "Reliever A", "game_date": "2026-04-02", "is_starter": False,
     "pitches": 22, "game_pk": 901},
    {"player_name": "Starter B", "game_date": "2026-04-02", "is_starter": True,
     "pitches": 95, "game_pk": 903},
])

FAKE_ROSTER = pd.DataFrame([
    {"player_id": 1, "player_name": "Reliever A", "position": "P"},
    {"player_id": 2, "player_name": "Starter B", "position": "P"},
])


@pytest.fixture
def season_client(client_with_db, monkeypatch):
    """Serve the parquet-backed routes from in-memory frames."""
    tables = {"games": FAKE_GAMES, "pitching": FAKE_PITCHING, "roster": FAKE_ROSTER}

    def fake_load(self, name):
        if name not in tables:
            raise FileNotFoundError(name)
        return tables[name].copy()

    monkeypatch.setattr("backend.api.routes.Fetcher.load", fake_load)
    return client_with_db


class TestGamesRoute:
    def test_returns_the_season_log(self, season_client):
        body = season_client.get("/api/v1/games").json()
        assert body["count"] == 3
        assert body["season"] == config.SEASON

    def test_orders_by_date_and_game_number_not_pk(self, season_client):
        """A pk sort would put the nightcap (pk 901) before game 1 (pk 903)."""
        games = season_client.get("/api/v1/games").json()["games"]
        assert [g["game_pk"] for g in games] == [900, 903, 901]

    def test_filters_by_result(self, season_client):
        body = season_client.get("/api/v1/games", params={"result": "W"}).json()
        assert body["count"] == 2
        assert {g["result"] for g in body["games"]} == {"W"}

    def test_limit_returns_the_most_recent_games(self, season_client):
        body = season_client.get("/api/v1/games", params={"limit": 1}).json()
        assert [g["game_pk"] for g in body["games"]] == [901]

    def test_a_missing_cache_is_503_not_500(self, client_with_db, monkeypatch):
        def missing(self, name):
            raise FileNotFoundError(name)

        monkeypatch.setattr("backend.api.routes.Fetcher.load", missing)
        assert client_with_db.get("/api/v1/games").status_code == 503


class TestStandingsRoute:
    def test_reports_record_and_streak(self, season_client):
        body = season_client.get("/api/v1/standings").json()
        assert body["record"]["wins"] == 2
        assert body["record"]["losses"] == 1
        assert body["longest_win_streak"] == 1
        assert body["streak"] == {"type": "W", "length": 1}

    def test_includes_pythagorean_expectation(self, season_client):
        record = season_client.get("/api/v1/standings").json()["record"]
        assert "pyth_wins" in record and "pyth_losses" in record


class TestTurnaroundRoute:
    def test_tracks_net_games_above_500(self, season_client):
        body = season_client.get("/api/v1/analytics/turnaround").json()
        assert [p["net_above_500"] for p in body["points"]] == [1, 0, 1]
        assert body["current_net"] == 1

    def test_reports_peak_and_trough(self, season_client):
        body = season_client.get("/api/v1/analytics/turnaround").json()
        assert body["peak"]["net_above_500"] == 1
        assert body["trough"]["net_above_500"] == 0


class TestMatchupTodayRoute:
    def test_bullpen_excludes_the_rotation(self, season_client):
        """Starter B has only ever started; he is not a relief option."""
        body = season_client.get("/api/v1/analytics/matchup/today").json()
        assert [b["player_name"] for b in body["bullpen"]] == ["Reliever A"]

    def test_serves_the_bullpen_with_no_schedule_row(self, season_client):
        body = season_client.get("/api/v1/analytics/matchup/today").json()
        assert body["games"] == []
        assert body["bullpen"]


class TestRefreshWebhook:
    """
    The regression this guards: an unauthenticated ingest endpoint. Refresh
    hits the MLB API and can spend odds credits, so an unset token must
    disable the route rather than leave it open.
    """

    def test_is_disabled_when_no_token_is_configured(self, client_with_db, monkeypatch):
        monkeypatch.setattr(config, "REFRESH_TOKEN", "")
        resp = client_with_db.post("/api/v1/refresh")
        assert resp.status_code == 503

    def test_rejects_a_missing_header(self, client_with_db, monkeypatch):
        monkeypatch.setattr(config, "REFRESH_TOKEN", "secret")
        assert client_with_db.post("/api/v1/refresh").status_code == 401

    def test_rejects_a_wrong_token(self, client_with_db, monkeypatch):
        monkeypatch.setattr(config, "REFRESH_TOKEN", "secret")
        resp = client_with_db.post(
            "/api/v1/refresh", headers={"X-Refresh-Token": "wrong"}
        )
        assert resp.status_code == 401

    def test_an_unknown_table_is_reported_without_fetching(self, client_with_db, monkeypatch):
        """No network: an unrecognised table must not reach the fetcher."""
        monkeypatch.setattr(config, "REFRESH_TOKEN", "secret")
        resp = client_with_db.post(
            "/api/v1/refresh",
            params={"tables": "bogus"},
            headers={"X-Refresh-Token": "secret"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "partial"
        assert body["refreshed"] == []
        assert body["errors"] == {"bogus": "unknown table"}

