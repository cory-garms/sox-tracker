"""
Async background scheduler service for dirtywater on Render.
Manages automated polling for MLB schedules, starting lineups, odds snapshots,
prediction archival, closing-line capture, and bet grading.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from analysis.betting import (
    batter_total_bases_model,
    fetch_book_lines,
    pitcher_strikeout_model,
)
from backend.database import get_db_session
from backend.repository import (
    grade_bets_from_snapshots,
    upsert_game_schedule,
)
from backend.services.archiver import (
    archive_market_odds,
    archive_strikeout_projections,
    archive_total_bases_projections,
)
from client.mlb_client import MLBClient
from client.odds_api_client import OddsAPIClient
from data.fetcher import Fetcher

log = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def sync_game_schedule_job() -> None:
    """
    Poll MLB Stats API for today's schedule, probable starters, and lineup confirmation status.
    Free API call, runs every 10 minutes.
    """
    log.info("Running MLB schedule sync job...")
    client = MLBClient()
    today_str = datetime.now().strftime("%Y-%m-%d")

    try:
        data = client.get(f"/schedule?sportId=1&teamId={config.TEAM_ID}&date={today_str}&hydrate=probablePitcher,lineups,linescore")
        dates = data.get("dates", [])
        if not dates:
            log.info("No games scheduled for team %d on %s", config.TEAM_ID, today_str)
            return

        with get_db_session() as session:
            for d in dates:
                for g in d.get("games", []):
                    game_pk = g.get("gamePk")
                    status_info = g.get("status", {})
                    teams_info = g.get("teams", {})
                    home = teams_info.get("home", {})
                    away = teams_info.get("away", {})

                    home_prob = home.get("probablePitcher", {})
                    away_prob = away.get("probablePitcher", {})

                    # Check if starting lineups are posted
                    lineups = g.get("lineups", {})
                    home_lineup_posted = bool(lineups.get("homePlayers"))
                    away_lineup_posted = bool(lineups.get("awayPlayers"))

                    game_data = {
                        "game_pk": game_pk,
                        "game_date": d.get("date", today_str),
                        "game_number": g.get("gameNumber", 1),
                        "season": g.get("season", config.SEASON),
                        "home_team_id": home.get("team", {}).get("id"),
                        "home_team_name": home.get("team", {}).get("name"),
                        "away_team_id": away.get("team", {}).get("id"),
                        "away_team_name": away.get("team", {}).get("name"),
                        "status": status_info.get("abstractGameState", "Scheduled"),
                        "detailed_state": status_info.get("detailedState", ""),
                        "probable_home_id": home_prob.get("id"),
                        "probable_home_name": home_prob.get("fullName"),
                        "probable_away_id": away_prob.get("id"),
                        "probable_away_name": away_prob.get("fullName"),
                        "first_pitch_utc": g.get("gameDate"),
                        "home_score": home.get("score"),
                        "away_score": away.get("score"),
                        "lineup_home_confirmed": home_lineup_posted,
                        "lineup_away_confirmed": away_lineup_posted,
                    }
                    upsert_game_schedule(session, game_data)

            log.info("Synced %d game(s) for %s", len(dates[0].get("games", [])), today_str)
    except Exception as e:
        log.warning("Schedule sync job failed: %s", e)


async def fetch_odds_and_archive_job() -> None:
    """
    Fetch sportsbook odds, run analytical models, and snapshot both into PostgreSQL.
    Runs at scheduled times or when triggered by lineup confirmation.
    """
    if not config.ODDS_API_KEY:
        log.info("ODDS_API_KEY not configured — skipping live odds fetch.")
        return

    log.info("Running odds fetch and prediction archival job...")
    client = MLBClient()
    odds_client = OddsAPIClient(api_key=config.ODDS_API_KEY)
    fetcher = Fetcher(team_id=config.TEAM_ID, season=config.SEASON, client=client)

    try:
        book = fetch_book_lines(odds_client, team_id=config.TEAM_ID)
        event = book.get("event")
        if not event:
            log.info("No active odds event found for team %d", config.TEAM_ID)
            return

        event_id = str(event.get("id", ""))
        today_str = datetime.now().strftime("%Y-%m-%d")

        with get_db_session() as session:
            # 1. Archive raw odds snapshots
            for market in ("pitcher_strikeouts", "batter_total_bases", "h2h"):
                archive_market_odds(session, event, market, book.get(market, {}))

            # 2. Generate and archive model predictions
            pitching = fetcher.load("pitching")
            batting = fetcher.load("batting")
            games = fetcher.load("games")

            k_lines = book.get("pitcher_strikeouts", {})
            tb_lines = book.get("batter_total_bases", {})

            if not pitching.empty:
                k_df = pitcher_strikeout_model(pitching, batting, games, client=client, book_lines=k_lines)
                archive_strikeout_projections(session, k_df, event_id=event_id, game_date=today_str)

            if not batting.empty:
                tb_df = batter_total_bases_model(batting, book_lines=tb_lines)
                archive_total_bases_projections(session, tb_df, event_id=event_id, game_date=today_str)

            # 3. Grade any bets against new odds snapshots
            graded = grade_bets_from_snapshots(session)
            if graded > 0:
                log.info("Graded %d bet(s) with new closing line data", graded)

    except Exception as e:
        log.warning("Odds fetch & archive job failed: %s", e)


def start_scheduler() -> AsyncIOScheduler:
    """Configure and start the background scheduler."""
    # Free MLB schedule listener every 10 minutes
    scheduler.add_job(
        sync_game_schedule_job,
        "interval",
        minutes=10,
        id="sync_mlb_schedule",
        replace_existing=True,
    )

    # Gated Odds Polling & Prediction Archival:
    # 08:00 ET (Morning Line), 12:00 ET (Midday), 15:00 ET (Lineup Release), 17:30 ET (Pre-Game Board)
    scheduler.add_job(
        fetch_odds_and_archive_job,
        "cron",
        hour="8,12,15,17",
        minute="30",
        timezone="America/New_York",
        id="archive_odds_and_predictions",
        replace_existing=True,
    )

    scheduler.start()
    log.info("Background scheduler started successfully.")
    return scheduler
