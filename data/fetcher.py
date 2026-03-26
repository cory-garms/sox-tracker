"""
Data fetcher — orchestrates all API calls and builds the four canonical tables.

Usage (programmatic):
    from data.fetcher import Fetcher
    f = Fetcher(team_id=111, season=2026)
    f.fetch_all()

Tables written to data/cache/:
    games_{team_id}_{season}.parquet
    batting_{team_id}_{season}.parquet
    pitching_{team_id}_{season}.parquet
    fielding_{team_id}_{season}.parquet
    roster_{team_id}_{season}.parquet
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import pandas as pd

from client.mlb_client import MLBClient
from data.schema import (
    GAMES_SCHEMA, BATTING_LOG_SCHEMA, PITCHING_LOG_SCHEMA,
    FIELDING_LOG_SCHEMA, enforce_schema,
)
from data.roster import fetch_roster
from config import CACHE_DIR

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ip_to_outs(ip: float) -> int:
    """Convert innings pitched (6.2 = 6⅔) to total outs."""
    whole = int(ip)
    frac  = round((ip - whole) * 10)
    return whole * 3 + frac


def _game_score(ip: float, h: int, er: int, bb: int, so: int) -> int:
    """Bill James game score formula (approximate)."""
    return 50 + _ip_to_outs(ip) - 2 * h - 4 * er - 2 * bb + so


def _safe_int(val, default=0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _safe_float(val, default=0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Fetcher
# ---------------------------------------------------------------------------

class Fetcher:
    def __init__(
        self,
        team_id: int,
        season: int,
        client: MLBClient | None = None,
        force_refresh: bool = False,
    ) -> None:
        self.team_id = team_id
        self.season  = season
        self.client  = client or MLBClient()
        self.force   = force_refresh

    def _cache(self, name: str) -> Path:
        return CACHE_DIR / f"{name}_{self.team_id}_{self.season}.parquet"

    def _needs_refresh(self, name: str) -> bool:
        return self.force or not self._cache(name).exists()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def fetch_all(self) -> dict[str, pd.DataFrame]:
        """Fetch and cache all tables.  Returns dict of DataFrames."""
        log.info("=== Fetching all data: team=%d season=%d ===", self.team_id, self.season)

        roster   = fetch_roster(self.team_id, self.season, self.client, self.force)
        games    = self.fetch_games()
        batting  = self.fetch_batting_logs(games)
        pitching = self.fetch_pitching_logs(games)
        fielding = self.fetch_fielding_logs(games)

        log.info("=== Fetch complete ===")
        return {
            "roster":   roster,
            "games":    games,
            "batting":  batting,
            "pitching": pitching,
            "fielding": fielding,
        }

    # ------------------------------------------------------------------
    # Games
    # ------------------------------------------------------------------

    def fetch_games(self) -> pd.DataFrame:
        if not self._needs_refresh("games"):
            log.info("Loading games from cache")
            return pd.read_parquet(self._cache("games"))

        log.info("Fetching schedule for team %d season %d", self.team_id, self.season)
        raw_games = self.client.get_schedule(self.team_id, self.season)
        rows: list[dict] = []

        completed = [g for g in raw_games if g.get("status", {}).get("abstractGameState") == "Final"]
        log.info("Processing %d completed games", len(completed))

        for i, game in enumerate(completed):
            gp          = game["gamePk"]
            teams       = game.get("teams", {})
            home        = teams.get("home", {})
            away        = teams.get("away", {})
            home_id     = home.get("team", {}).get("id")
            away_id     = away.get("team", {}).get("id")
            is_home     = home_id == self.team_id
            our_side    = home if is_home else away
            their_side  = away if is_home else home
            runs_scored  = _safe_int(our_side.get("score"))
            runs_allowed = _safe_int(their_side.get("score"))

            result = "W" if runs_scored > runs_allowed else "L"

            decisions = game.get("decisions", {})
            linescore = game.get("linescore", {})

            rows.append({
                "game_pk":        gp,
                "game_date":      game.get("gameDate", "")[:10],
                "season":         self.season,
                "game_num":       i + 1,
                "home_team_id":   home_id,
                "away_team_id":   away_id,
                "team_id":        self.team_id,
                "opponent_id":    their_side.get("team", {}).get("id"),
                "is_home":        is_home,
                "runs_scored":    runs_scored,
                "runs_allowed":   runs_allowed,
                "result":         result,
                "win_pitcher":    decisions.get("winner", {}).get("fullName", ""),
                "loss_pitcher":   decisions.get("loser",  {}).get("fullName", ""),
                "save_pitcher":   decisions.get("save",   {}).get("fullName", ""),
                "innings":        _safe_int(linescore.get("currentInning", 9), 9),
                "day_night":      game.get("dayNight", "").upper()[:1] or "N",
                "game_type":      game.get("gameType", "R"),
                "venue":          game.get("venue", {}).get("name", ""),
                "status":         game.get("status", {}).get("detailedState", "Final"),
            })

        df = pd.DataFrame(rows)
        df = enforce_schema(df, GAMES_SCHEMA)
        df.to_parquet(self._cache("games"), index=False)
        log.info("Cached %d games → %s", len(df), self._cache("games"))
        return df

    # ------------------------------------------------------------------
    # Batting logs
    # ------------------------------------------------------------------

    def fetch_batting_logs(self, games: pd.DataFrame) -> pd.DataFrame:
        if not self._needs_refresh("batting"):
            log.info("Loading batting logs from cache")
            return pd.read_parquet(self._cache("batting"))

        log.info("Fetching batting logs for %d games", len(games))
        rows: list[dict] = []

        for _, game_row in games.iterrows():
            gp   = int(game_row["game_pk"])
            date = game_row["game_date"]
            try:
                boxscore = self.client.get_boxscore(gp)
            except Exception as e:
                log.warning("Boxscore failed for game %d: %s", gp, e)
                continue

            side_key = "home" if game_row["is_home"] else "away"
            team_data = boxscore.get("teams", {}).get(side_key, {})
            batters   = team_data.get("batters", [])
            players   = team_data.get("players", {})
            batting_order = team_data.get("battingOrder", [])
            order_map = {pid: i + 1 for i, pid in enumerate(batting_order)}

            for pid in batters:
                pkey  = f"ID{pid}"
                pdata = players.get(pkey, {})
                stats = pdata.get("stats", {}).get("batting", {})
                info  = pdata.get("person", {})
                pos   = pdata.get("position", {}).get("abbreviation", "")

                ab  = _safe_int(stats.get("atBats"))
                h   = _safe_int(stats.get("hits"))
                bb  = _safe_int(stats.get("baseOnBalls"))
                hbp = _safe_int(stats.get("hitByPitch"))
                sf  = _safe_int(stats.get("sacFlies"))
                pa  = ab + bb + hbp + sf + _safe_int(stats.get("sacBunts"))

                obp = _safe_float(stats.get("obp")) or (
                    (h + bb + hbp) / pa if pa > 0 else 0.0
                )
                slg = _safe_float(stats.get("slg")) or (
                    (_safe_int(stats.get("totalBases")) / ab) if ab > 0 else 0.0
                )

                rows.append({
                    "game_pk":       gp,
                    "game_date":     date,
                    "season":        self.season,
                    "team_id":       self.team_id,
                    "player_id":     pid,
                    "player_name":   info.get("fullName", ""),
                    "batting_order": order_map.get(pid, 0),
                    "position":      pos,
                    "ab":            ab,
                    "pa":            pa,
                    "h":             h,
                    "doubles":       _safe_int(stats.get("doubles")),
                    "triples":       _safe_int(stats.get("triples")),
                    "hr":            _safe_int(stats.get("homeRuns")),
                    "rbi":           _safe_int(stats.get("rbi")),
                    "r":             _safe_int(stats.get("runs")),
                    "bb":            bb,
                    "ibb":           _safe_int(stats.get("intentionalWalks")),
                    "so":            _safe_int(stats.get("strikeOuts")),
                    "hbp":           hbp,
                    "sb":            _safe_int(stats.get("stolenBases")),
                    "cs":            _safe_int(stats.get("caughtStealing")),
                    "sac_bunt":      _safe_int(stats.get("sacBunts")),
                    "sac_fly":       sf,
                    "gidp":          _safe_int(stats.get("groundIntoDoublePlay")),
                    "avg":           _safe_float(stats.get("avg")),
                    "obp":           obp,
                    "slg":           slg,
                    "ops":           _safe_float(stats.get("ops")) or (obp + slg),
                })

        df = pd.DataFrame(rows)
        df = enforce_schema(df, BATTING_LOG_SCHEMA)
        df.to_parquet(self._cache("batting"), index=False)
        log.info("Cached %d batting rows → %s", len(df), self._cache("batting"))
        return df

    # ------------------------------------------------------------------
    # Pitching logs
    # ------------------------------------------------------------------

    def fetch_pitching_logs(self, games: pd.DataFrame) -> pd.DataFrame:
        if not self._needs_refresh("pitching"):
            log.info("Loading pitching logs from cache")
            return pd.read_parquet(self._cache("pitching"))

        log.info("Fetching pitching logs for %d games", len(games))
        rows: list[dict] = []

        for _, game_row in games.iterrows():
            gp   = int(game_row["game_pk"])
            date = game_row["game_date"]
            try:
                boxscore = self.client.get_boxscore(gp)
            except Exception as e:
                log.warning("Boxscore failed for game %d: %s", gp, e)
                continue

            side_key  = "home" if game_row["is_home"] else "away"
            team_data = boxscore.get("teams", {}).get(side_key, {})
            pitchers  = team_data.get("pitchers", [])
            players   = team_data.get("players", {})

            for i, pid in enumerate(pitchers):
                pkey  = f"ID{pid}"
                pdata = players.get(pkey, {})
                stats = pdata.get("stats", {}).get("pitching", {})
                info  = pdata.get("person", {})

                ip  = _safe_float(stats.get("inningsPitched"))
                h   = _safe_int(stats.get("hits"))
                er  = _safe_int(stats.get("earnedRuns"))
                bb  = _safe_int(stats.get("baseOnBalls"))
                so  = _safe_int(stats.get("strikeOuts"))
                hr  = _safe_int(stats.get("homeRuns"))
                bf  = _safe_int(stats.get("battersFaced"))
                pit = _safe_int(stats.get("numberOfPitches"))
                stk = _safe_int(stats.get("strikes"))

                outs = _ip_to_outs(ip)
                era  = (er * 27 / outs) if outs > 0 else 0.0
                whip = ((h + bb) / ip) if ip > 0 else 0.0
                k9   = (so * 9 / ip) if ip > 0 else 0.0
                bb9  = (bb * 9 / ip) if ip > 0 else 0.0
                gs   = _game_score(ip, h, er, bb, so) if i == 0 else 0

                rows.append({
                    "game_pk":     gp,
                    "game_date":   date,
                    "season":      self.season,
                    "team_id":     self.team_id,
                    "player_id":   pid,
                    "player_name": info.get("fullName", ""),
                    "is_starter":  i == 0,
                    "ip":          ip,
                    "ip_outs":     outs,
                    "h":           h,
                    "r":           _safe_int(stats.get("runs")),
                    "er":          er,
                    "bb":          bb,
                    "so":          so,
                    "hr":          hr,
                    "hbp":         _safe_int(stats.get("hitByPitch")),
                    "bf":          bf,
                    "pitches":     pit,
                    "strikes":     stk,
                    "era":         era,
                    "whip":        whip,
                    "k_per_9":     k9,
                    "bb_per_9":    bb9,
                    "win":         bool(stats.get("wins", 0)),
                    "loss":        bool(stats.get("losses", 0)),
                    "save":        bool(stats.get("saves", 0)),
                    "hold":        bool(stats.get("holds", 0)),
                    "blown_save":  bool(stats.get("blownSaves", 0)),
                    "game_score":  gs,
                })

        df = pd.DataFrame(rows)
        df = enforce_schema(df, PITCHING_LOG_SCHEMA)
        df.to_parquet(self._cache("pitching"), index=False)
        log.info("Cached %d pitching rows → %s", len(df), self._cache("pitching"))
        return df

    # ------------------------------------------------------------------
    # Fielding logs
    # ------------------------------------------------------------------

    def fetch_fielding_logs(self, games: pd.DataFrame) -> pd.DataFrame:
        if not self._needs_refresh("fielding"):
            log.info("Loading fielding logs from cache")
            return pd.read_parquet(self._cache("fielding"))

        log.info("Fetching fielding logs for %d games", len(games))
        rows: list[dict] = []

        for _, game_row in games.iterrows():
            gp   = int(game_row["game_pk"])
            date = game_row["game_date"]
            try:
                boxscore = self.client.get_boxscore(gp)
            except Exception as e:
                log.warning("Boxscore failed for game %d: %s", gp, e)
                continue

            side_key  = "home" if game_row["is_home"] else "away"
            team_data = boxscore.get("teams", {}).get(side_key, {})
            players   = team_data.get("players", {})

            for pkey, pdata in players.items():
                field_stats = pdata.get("stats", {}).get("fielding", {})
                if not field_stats:
                    continue

                info = pdata.get("person", {})
                pos  = pdata.get("position", {}).get("abbreviation", "")
                pid  = info.get("id")

                po  = _safe_int(field_stats.get("putOuts"))
                a   = _safe_int(field_stats.get("assists"))
                e   = _safe_int(field_stats.get("errors"))
                ch  = po + a + e
                fp  = (po + a) / ch if ch > 0 else 1.0

                rows.append({
                    "game_pk":      gp,
                    "game_date":    date,
                    "season":       self.season,
                    "team_id":      self.team_id,
                    "player_id":    pid,
                    "player_name":  info.get("fullName", ""),
                    "position":     pos,
                    "innings":      9.0,
                    "putouts":      po,
                    "assists":      a,
                    "errors":       e,
                    "chances":      ch,
                    "fielding_pct": fp,
                    "dp":           _safe_int(field_stats.get("doublePlays")),
                    "passed_balls": _safe_int(field_stats.get("passedBall")),
                    "sb_against":   _safe_int(field_stats.get("stolenBases")),
                    "cs_against":   _safe_int(field_stats.get("caughtStealing")),
                })

        df = pd.DataFrame(rows)
        df = enforce_schema(df, FIELDING_LOG_SCHEMA)
        df.to_parquet(self._cache("fielding"), index=False)
        log.info("Cached %d fielding rows → %s", len(df), self._cache("fielding"))
        return df

    # ------------------------------------------------------------------
    # Load helpers (read-only, no API calls)
    # ------------------------------------------------------------------

    def load(self, name: str) -> pd.DataFrame:
        """Load a cached table by name: 'games', 'batting', 'pitching', 'fielding', 'roster'."""
        path = self._cache(name)
        if not path.exists():
            raise FileNotFoundError(
                f"Cache not found: {path}\n"
                f"Run `python fetch.py --team {self.team_id} --season {self.season}` first."
            )
        return pd.read_parquet(path)
