"""
Baseball Savant / Statcast client.

Fetches Statcast data from baseballsavant.mlb.com CSV endpoints.
No authentication required.

Key datasets:
  - Batter leaderboard  (exit velo, barrel %, hard-hit %, xBA, xwOBA, xSLG)
  - Pitcher leaderboard (xERA, xFIP, spin rate, extension)
  - Fielding / OAA      (outs above average by position)
  - Catcher framing     (runs saved via pitch framing)
  - Sprint speed        (ft/sec, 90-ft sprint)
"""

from __future__ import annotations

import io
import logging
import time
from typing import Literal

import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import SAVANT_BASE, REQUEST_TIMEOUT, REQUEST_DELAY

log = logging.getLogger(__name__)

# Statcast leaderboard columns we care about per group
_BATTER_COLS = [
    "player_id", "player_name", "team_id", "team",
    "pa", "ab", "exit_velocity_avg", "launch_angle_avg",
    "barrel_batted_rate", "hard_hit_percent",
    "xba", "xslg", "xwoba", "xobp",
]

_PITCHER_COLS = [
    "player_id", "player_name", "team_id", "team",
    "p_game", "p_formatted_ip",
    "exit_velocity_avg", "barrel_batted_rate",
    "xera", "xfip_minus",
    "spin_rate_avg", "extension_avg",
]

_OAA_COLS = [
    "player_id", "player_name", "team_id", "team",
    "season", "inn", "outs_above_average",
    "attempts", "success_rate_above_avg",
]

_FRAMING_COLS = [
    "player_id", "player_name", "team_id", "team",
    "n", "strike_rate", "runs_extra_strikes",
]

_SPRINT_COLS = [
    "player_id", "player_name", "team_id", "team",
    "sprint_speed", "hp_to_1b", "competitive_runs",
]


class SavantClient:
    """Fetches Statcast leaderboard data from Baseball Savant CSV exports."""

    _LEADERBOARD_URL = f"{SAVANT_BASE}/leaderboard/custom"
    _OAA_URL         = f"{SAVANT_BASE}/leaderboard/outs_above_average"
    _FRAMING_URL     = f"{SAVANT_BASE}/leaderboard/catching"
    _SPRINT_URL      = f"{SAVANT_BASE}/running_splits"

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "sox-tracker/1.0 (portfolio demo)"})
        self._last_call: float = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)

    @retry(
        retry=retry_if_exception_type(requests.RequestException),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        reraise=True,
    )
    def _get_csv(self, url: str, params: dict) -> pd.DataFrame:
        self._throttle()
        log.debug("GET CSV %s %s", url, params)
        resp = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        self._last_call = time.monotonic()
        return pd.read_csv(io.StringIO(resp.text))

    # ------------------------------------------------------------------
    # Batter Statcast leaderboard
    # ------------------------------------------------------------------

    def get_batter_statcast(self, season: int, team_abbr: str | None = None) -> pd.DataFrame:
        """
        Exit velocity, barrel%, hard-hit%, xBA, xwOBA for all qualifying batters.
        Filter to a specific team by passing team_abbr (e.g. "BOS").
        """
        params = {
            "year": season,
            "type": "batter",
            "min": "q",        # qualified plate appearances
            "csv": "true",
            "selections": ",".join([
                "pa", "ab",
                "exit_velocity_avg", "launch_angle_avg",
                "barrel_batted_rate", "hard_hit_percent",
                "xba", "xslg", "xwoba", "xobp",
            ]),
        }
        df = self._get_csv(self._LEADERBOARD_URL, params)
        df = self._normalize_ids(df)
        if team_abbr:
            df = df[df["team"].str.upper() == team_abbr.upper()]
        return df

    # ------------------------------------------------------------------
    # Pitcher Statcast leaderboard
    # ------------------------------------------------------------------

    def get_pitcher_statcast(self, season: int, team_abbr: str | None = None) -> pd.DataFrame:
        """xERA, barrel% allowed, avg exit velo allowed, spin rate for pitchers."""
        params = {
            "year": season,
            "type": "pitcher",
            "min": "q",
            "csv": "true",
            "selections": ",".join([
                "p_game", "p_formatted_ip",
                "exit_velocity_avg", "barrel_batted_rate",
                "xera", "spin_rate_avg", "extension_avg",
            ]),
        }
        df = self._get_csv(self._LEADERBOARD_URL, params)
        df = self._normalize_ids(df)
        if team_abbr:
            df = df[df["team"].str.upper() == team_abbr.upper()]
        return df

    # ------------------------------------------------------------------
    # Outs Above Average (fielding)
    # ------------------------------------------------------------------

    def get_oaa(
        self,
        season: int,
        team_abbr: str | None = None,
        position: Literal["all", "1B", "2B", "3B", "SS", "LF", "CF", "RF", "C"] = "all",
    ) -> pd.DataFrame:
        """Outs above average per fielder. Positive = above avg, negative = below."""
        params = {
            "year": season,
            "team": "",
            "range": "year",
            "min": 1,
            "pos": position,
            "roles": "z",
            "viz": "hide",
            "csv": "true",
        }
        df = self._get_csv(self._OAA_URL, params)
        df = self._normalize_ids(df)
        if team_abbr and "team" in df.columns:
            df = df[df["team"].str.upper() == team_abbr.upper()]
        return df

    # ------------------------------------------------------------------
    # Catcher framing
    # ------------------------------------------------------------------

    def get_catcher_framing(self, season: int, team_abbr: str | None = None) -> pd.DataFrame:
        """Strike rate and runs saved/lost via pitch framing for catchers."""
        params = {
            "year": season,
            "type": "catcher_framing",
            "min": 100,
            "csv": "true",
        }
        df = self._get_csv(self._FRAMING_URL, params)
        df = self._normalize_ids(df)
        if team_abbr and "team" in df.columns:
            df = df[df["team"].str.upper() == team_abbr.upper()]
        return df

    # ------------------------------------------------------------------
    # Sprint speed
    # ------------------------------------------------------------------

    def get_sprint_speed(self, season: int, team_abbr: str | None = None) -> pd.DataFrame:
        """Sprint speed (ft/sec) and HP-to-1B time for all tracked players."""
        params = {
            "year": season,
            "position": "",
            "team": team_abbr or "",
            "min_opp": 10,
            "csv": "true",
        }
        df = self._get_csv(self._SPRINT_URL, params)
        df = self._normalize_ids(df)
        return df

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_ids(df: pd.DataFrame) -> pd.DataFrame:
        """Standardize player_id column name across different Savant endpoints."""
        for candidate in ("mlbam_id", "mlb_id", "id", "pitcher", "batter"):
            if candidate in df.columns and "player_id" not in df.columns:
                df = df.rename(columns={candidate: "player_id"})
                break
        if "player_id" in df.columns:
            df["player_id"] = pd.to_numeric(df["player_id"], errors="coerce").astype("Int64")
        return df
