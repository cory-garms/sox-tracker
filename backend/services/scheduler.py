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
    pitcher_strikeout_model,
)
from backend.database import get_db_session
from backend.repository import (
    grade_bets_from_snapshots,
    latest_event_id,
    latest_lines_by_market,
    upsert_game_schedule,
)
from backend.services.archiver import (
    archive_strikeout_projections,
    archive_total_bases_projections,
)
from client.mlb_client import MLBClient
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
        # MLBClient exposes get_schedule(), not a raw get(). This called
        # client.get(...) and raised AttributeError on every tick — caught by
        # the handler below and logged as a warning, so the job had been a
        # silent no-op and game_schedules was never populated. That is why
        # /api/v1/analytics/matchup/today returned an empty games list.
        games = client.get_schedule(
            team_id=config.TEAM_ID,
            season=config.SEASON,
            start_date=today_str,
            end_date=today_str,
            hydrate="probablePitcher,lineups,linescore",
        )
        if not games:
            log.info("No games scheduled for team %d on %s", config.TEAM_ID, today_str)
            return

        with get_db_session() as session:
            for g in games:
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
                    "game_pk": g.get("gamePk"),
                    "game_date": g.get("officialDate") or today_str,
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

            log.info("Synced %d game(s) for %s", len(games), today_str)
    except Exception as e:
        log.warning("Schedule sync job failed: %s", e)


async def archive_predictions_job() -> None:
    """
    Run the models and archive their projections — spending no odds quota.

    This job used to call fetch_book_lines() on its own schedule, which meant
    two independent systems were buying the same prices:

        refresh.yml   07:00 / 12:00 / 15:00 / 17:30 ET   (~450/mo with close.yml)
        this job      08:30 / 12:30 / 15:30 / 17:30 ET   (2 credits x 4 = ~240/mo)

    At 17:30 ET they fired simultaneously and pulled the same board twice.
    Combined that is ~690/month against a 500 quota, so the month ran dry and
    late-season captures silently degraded to projections-only.

    The GitHub Actions build is now the single owner of odds fetching: it is
    the reliable one (Render's free plan spins this process down when idle, so
    its cron was never dependable anyway), and it commits odds_history.parquet,
    which the deploy migrates into Postgres. This job reads those stored prices
    back out and archives what the models make of them.
    """
    log.info("Running prediction archival job (no odds fetch)...")
    client = MLBClient()
    fetcher = Fetcher(team_id=config.TEAM_ID, season=config.SEASON, client=client)

    try:
        today_str = datetime.now().strftime("%Y-%m-%d")

        with get_db_session() as session:
            event_id = latest_event_id(session)
            k_lines = latest_lines_by_market(session, "pitcher_strikeouts", event_id or None)
            tb_lines = latest_lines_by_market(session, "batter_total_bases", event_id or None)

            if not k_lines and not tb_lines:
                log.info("No stored odds to project against yet — nothing to archive.")
                return

            pitching = fetcher.load("pitching")
            batting = fetcher.load("batting")
            games = fetcher.load("games")

            if not pitching.empty:
                k_df = pitcher_strikeout_model(pitching, batting, games, client=client, book_lines=k_lines)
                archive_strikeout_projections(session, k_df, event_id=event_id, game_date=today_str)

            if not batting.empty:
                tb_df = batter_total_bases_model(batting, book_lines=tb_lines)
                archive_total_bases_projections(session, tb_df, event_id=event_id, game_date=today_str)

            graded = grade_bets_from_snapshots(session)
            if graded > 0:
                log.info("Graded %d bet(s) against stored closing lines", graded)

    except FileNotFoundError as e:
        log.info("Parquet cache not built on this instance yet: %s", e)
    except Exception as e:
        log.warning("Prediction archival job failed: %s", e)


def start_scheduler() -> AsyncIOScheduler:
    """Configure and start the background scheduler."""
    try:
        # Free MLB schedule listener every 10 minutes
        scheduler.add_job(
            sync_game_schedule_job,
            "interval",
            minutes=10,
            id="sync_mlb_schedule",
            replace_existing=True,
        )

        # Prediction archival, deliberately offset from refresh.yml's builds
        # (07:00 / 12:00 / 15:00 / 17:30 ET) so it reads prices the Action has
        # already fetched and committed rather than racing it. Spends no odds
        # quota — see archive_predictions_job.
        #
        # The times below are the real ones. This previously read
        # hour="8,12,15,17", minute="30" under a comment claiming
        # "08:00/12:00/15:00/17:30", so three of the four fired 30 minutes
        # later than documented.
        scheduler.add_job(
            archive_predictions_job,
            "cron",
            hour="8,13,16,18",
            minute="15",
            timezone="America/New_York",
            id="archive_predictions",
            replace_existing=True,
        )

        scheduler.start()
        log.info("Background scheduler started successfully.")
    except Exception as e:
        log.warning("Background scheduler could not be started: %s", e)
    return scheduler

