"""
MLB Stats API client.

Wraps https://statsapi.mlb.com/api/v1/ with retry logic, rate limiting,
and typed response helpers.  No API key required — this is a public API.

Endpoint reference: https://github.com/toddrob99/MLB-StatsAPI/wiki
"""

from __future__ import annotations

import time
import logging
from typing import Any

import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import MLB_API_BASE, REQUEST_TIMEOUT, REQUEST_DELAY

log = logging.getLogger(__name__)


class MLBClient:
    """Thin, stateful wrapper around the MLB Stats API."""

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        self._last_call: float = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        reraise=True,
    )
    def _get(self, path: str, params: dict | None = None) -> Any:
        self._throttle()
        url = f"{MLB_API_BASE}{path}"
        log.debug("GET %s %s", url, params)
        resp = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        self._last_call = time.monotonic()
        return resp.json()

    # ------------------------------------------------------------------
    # Schedule & Games
    # ------------------------------------------------------------------

    def get_schedule(
        self,
        team_id: int,
        season: int,
        game_type: str = "R",       # R=regular season, P=postseason, S=spring
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict]:
        """Return a list of game records for the given team and season."""
        params: dict[str, Any] = {
            "sportId": 1,
            "teamId": team_id,
            "season": season,
            "gameType": game_type,
            "hydrate": "decisions,linescore",
        }
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date

        data = self._get("/schedule", params)
        games: list[dict] = []
        for date_block in data.get("dates", []):
            for game in date_block.get("games", []):
                games.append(game)
        return games

    def get_boxscore(self, game_pk: int) -> dict:
        """Full boxscore for a single game (batting, pitching, fielding lines)."""
        return self._get(f"/game/{game_pk}/boxscore")

    def get_linescore(self, game_pk: int) -> dict:
        return self._get(f"/game/{game_pk}/linescore")

    # ------------------------------------------------------------------
    # Standings
    # ------------------------------------------------------------------

    def get_standings(self, season: int, league_ids: str = "103,104") -> list[dict]:
        """
        Returns standings for all divisions.
        league_ids: 103=AL, 104=NL
        """
        data = self._get("/standings", {"leagueId": league_ids, "season": season,
                                        "hydrate": "team,division,league"})
        return data.get("records", [])

    # ------------------------------------------------------------------
    # Roster
    # ------------------------------------------------------------------

    def get_roster(self, team_id: int, season: int, roster_type: str = "active") -> list[dict]:
        """Active (or full-season) roster for a team."""
        data = self._get(
            f"/teams/{team_id}/roster",
            {"rosterType": roster_type, "season": season,
             "hydrate": "person(stats(type=season,group=hitting,season={season}))".format(season=season)},
        )
        return data.get("roster", [])

    def get_team_roster_40man(self, team_id: int, season: int) -> list[dict]:
        return self.get_roster(team_id, season, roster_type="40Man")

    # ------------------------------------------------------------------
    # Team Stats
    # ------------------------------------------------------------------

    def get_team_stats(
        self,
        team_id: int,
        season: int,
        group: str,           # "hitting", "pitching", or "fielding"
        stats_type: str = "season",
    ) -> dict:
        """Aggregate team stats for hitting, pitching, or fielding."""
        data = self._get(
            f"/teams/{team_id}/stats",
            {"stats": stats_type, "group": group, "season": season, "sportId": 1},
        )
        splits = data.get("stats", [{}])[0].get("splits", [{}])
        return splits[0].get("stat", {}) if splits else {}

    # ------------------------------------------------------------------
    # Player Stats
    # ------------------------------------------------------------------

    def get_player_season_stats(
        self,
        player_id: int,
        season: int,
        group: str,           # "hitting", "pitching", or "fielding"
    ) -> dict:
        """Season totals for a single player."""
        data = self._get(
            f"/people/{player_id}/stats",
            {"stats": "season", "group": group, "season": season, "sportId": 1},
        )
        splits = data.get("stats", [{}])[0].get("splits", [{}])
        return splits[0].get("stat", {}) if splits else {}

    def get_player_game_log(
        self,
        player_id: int,
        season: int,
        group: str,
    ) -> list[dict]:
        """Game-by-game log for a player (hitting or pitching)."""
        data = self._get(
            f"/people/{player_id}/stats",
            {"stats": "gameLog", "group": group, "season": season, "sportId": 1},
        )
        splits = data.get("stats", [{}])[0].get("splits", [])
        return splits

    def get_player_info(self, player_id: int) -> dict:
        """Basic bio for a player (name, position, bats, throws, dob)."""
        data = self._get(f"/people/{player_id}")
        people = data.get("people", [{}])
        return people[0] if people else {}

    # ------------------------------------------------------------------
    # Standings helpers
    # ------------------------------------------------------------------

    def get_division_standings(self, division_id: int, season: int) -> list[dict]:
        """
        division_id reference:
          200=AL West, 201=AL East, 202=AL Central
          203=NL West, 204=NL East, 205=NL Central
        """
        all_records = self.get_standings(season)
        for record in all_records:
            if record.get("division", {}).get("id") == division_id:
                return record.get("teamRecords", [])
        return []

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_team_info(self, team_id: int) -> dict:
        data = self._get(f"/teams/{team_id}")
        teams = data.get("teams", [{}])
        return teams[0] if teams else {}

    def search_player(self, name: str) -> list[dict]:
        data = self._get("/people/search", {"names": name})
        return data.get("people", [])
