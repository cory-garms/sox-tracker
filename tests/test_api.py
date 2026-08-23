"""
Tests for FastAPI REST API endpoints.
Runs 100% offline using FastAPI TestClient with an isolated in-memory SQLite database.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sqlalchemy.pool import StaticPool

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

