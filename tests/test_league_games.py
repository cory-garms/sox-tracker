"""
League-wide results, and the as-of totals a backtest depends on.

The win-probability baseline needs both teams' runs scored and allowed. Those
sit on the standings endpoint for *today*, and today is the one date a backtest
must not use: scoring an April game with August's standings leaks four months
of results into the projection. It fails silently — the numbers still compute,
and the model looks far better than it is. Same failure the projection backfill
guards against, same guard: truncate the inputs and prove the truncation bites.
"""

from __future__ import annotations

import pandas as pd

from data import league_games as lg

# 111 hosts 147 twice, then travels. Scores chosen so every total is distinct.
GAMES = pd.DataFrame([
    {"game_pk": 1, "game_date": "2026-04-01", "home_team_id": 111, "away_team_id": 147,
     "home_score": 5, "away_score": 2},
    {"game_pk": 2, "game_date": "2026-05-01", "home_team_id": 111, "away_team_id": 147,
     "home_score": 1, "away_score": 7},
    {"game_pk": 3, "game_date": "2026-06-01", "home_team_id": 147, "away_team_id": 111,
     "home_score": 4, "away_score": 6},
])


class TestAsOfTotals:
    def test_home_and_away_games_both_count(self):
        rs, ra, n = lg.team_runs_before(GAMES, 111)
        assert (rs, ra, n) == (5 + 1 + 6, 2 + 7 + 4, 3)

    def test_the_other_side_is_the_mirror(self):
        a = lg.team_runs_before(GAMES, 111)
        b = lg.team_runs_before(GAMES, 147)
        assert a[0] == b[1] and a[1] == b[0] and a[2] == b[2]

    def test_before_is_exclusive(self):
        """
        A projection for a date may use the games before it and not the day
        itself. Inclusive would hand the model the result it is predicting.
        """
        rs, ra, n = lg.team_runs_before(GAMES, 111, before="2026-05-01")
        assert (rs, ra, n) == (5, 2, 1)

    def test_truncation_actually_bites(self):
        early = lg.team_runs_before(GAMES, 111, before="2026-05-01")
        late = lg.team_runs_before(GAMES, 111, before="2026-07-01")
        assert early[2] < late[2]

    def test_a_future_result_cannot_reach_a_past_projection(self):
        """The load-bearing one: splice a wildly different future in, and the
        answer for an earlier date must not move."""
        future = pd.DataFrame([{"game_pk": 9, "game_date": "2026-09-01",
                                "home_team_id": 111, "away_team_id": 147,
                                "home_score": 30, "away_score": 0}])
        asof = "2026-05-01"
        assert (lg.team_runs_before(GAMES, 111, before=asof)
                == lg.team_runs_before(pd.concat([GAMES, future]), 111, before=asof))

    def test_a_team_with_no_games_yet_is_zeroed_not_guessed(self):
        assert lg.team_runs_before(GAMES, 999) == (0.0, 0.0, 0)

    def test_an_empty_frame_does_not_raise(self):
        assert lg.team_runs_before(pd.DataFrame(), 111) == (0.0, 0.0, 0)
        assert lg.team_runs_before(None, 111) == (0.0, 0.0, 0)


class TestOnlyFinishedGamesAreResults:
    def test_a_postponed_game_is_not_final(self):
        """
        detailedState is the field to trust: a postponed game keeps
        abstractGameState "Final", which is why the fetcher and the post-game
        check both key on the detailed one.
        """
        assert "Postponed" not in lg.FINAL_STATES
        assert "Final" in lg.FINAL_STATES
