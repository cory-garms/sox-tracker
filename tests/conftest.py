"""Shared fixtures and helpers for the sox_tracker test suite."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

# Tests run against the working tree, not an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


BOS = 111
BAL = 110


def game(
    game_pk: int,
    game_date: str,
    runs_scored: int,
    runs_allowed: int,
    *,
    game_number: int = 1,
    status: str = "Final",
    is_home: bool = True,
    opponent_id: int = BAL,
) -> dict:
    """One row of the cached games table, with sane defaults."""
    if runs_scored > runs_allowed:
        result = "W"
    elif runs_scored < runs_allowed:
        result = "L"
    else:
        result = "T"
    return {
        "game_pk": game_pk,
        "game_date": game_date,
        "season": 2026,
        "game_num": game_pk,
        "game_number": game_number,
        "home_team_id": BOS if is_home else opponent_id,
        "away_team_id": opponent_id if is_home else BOS,
        "team_id": BOS,
        "opponent_id": opponent_id,
        "is_home": is_home,
        "runs_scored": runs_scored,
        "runs_allowed": runs_allowed,
        "result": result,
        "win_pitcher": "",
        "loss_pitcher": "",
        "save_pitcher": "",
        "innings": 9,
        "day_night": "N",
        "game_type": "R",
        "venue": "Fenway Park",
        "status": status,
    }


def games_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def schedule_entry(
    game_pk: int,
    official_date: str,
    our_score: int,
    their_score: int,
    *,
    game_number: int = 1,
    abstract_state: str = "Final",
    detailed_state: str = "Final",
    home: bool = True,
    opponent_id: int = BAL,
) -> dict:
    """One game as the MLB schedule endpoint returns it."""
    us = {"team": {"id": BOS}, "score": our_score}
    them = {"team": {"id": opponent_id}, "score": their_score}
    return {
        "gamePk": game_pk,
        "officialDate": official_date,
        "gameNumber": game_number,
        "dayNight": "night",
        "gameType": "R",
        "venue": {"name": "Fenway Park"},
        "status": {
            "abstractGameState": abstract_state,
            "detailedState": detailed_state,
        },
        "teams": {
            "home": us if home else them,
            "away": them if home else us,
        },
    }


class FakeMLBClient:
    """Stands in for MLBClient. Records calls; serves canned linescores."""

    def __init__(self, linescores: dict[int, dict] | None = None,
                 fail_for: set[int] | None = None) -> None:
        self.linescores = linescores or {}
        self.fail_for = fail_for or set()
        self.linescore_calls: list[int] = []

    def get_linescore(self, game_pk: int) -> dict:
        self.linescore_calls.append(game_pk)
        if game_pk in self.fail_for:
            raise RuntimeError("simulated API failure")
        return self.linescores.get(game_pk, {})


def linescore(first_inning_away: int, first_inning_home: int) -> dict:
    return {"innings": [{
        "num": 1,
        "away": {"runs": first_inning_away},
        "home": {"runs": first_inning_home},
    }]}


@pytest.fixture
def bos() -> int:
    return BOS
