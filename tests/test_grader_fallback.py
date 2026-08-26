"""
Two holes in the grader, both found by watching it run rather than by reading it.

**The opposing starter could never settle.** The Fetcher caches hold one team,
so Tyler Phillips on 2026-08-25 -- the first opposing-starter projection this
project ever logged -- resolved as "player did not appear" and would have
waited forever. His line was in the box score of the same game the entire time:
one call, both teams.

**A bench bat came back every run.** These tables rank the top ten hitters by
projection across the roster, so four or five a night never bat. Left blank
they returned to the ungraded queue on every future run for the rest of the
season -- the exact leak `no_line` exists to prevent one market over. 2,799 rows
were in that state.

The order matters and is the whole subtlety: absent from our caches does not
mean absent from the game. The box score is consulted first, and only a player
nobody can find anywhere is settled as DNP.
"""

from __future__ import annotations

import pandas as pd

from analysis.grading import grade_frame
from data import predictions_history as ph

LOGS_DATE = "2026-08-25"


def _pred(player_id, player, market, line, **kw):
    row = {
        "captured_at": "2026-08-25T21:00:00+00:00", "game_date": LOGS_DATE,
        "commence_time": "2026-08-25T22:40:00Z", "event_id": "e1",
        "game_pk": pd.NA, "market": market, "player_id": player_id,
        "player": player, "lineup_slot": pd.NA, "line": line, "projection": 3.4,
        "model_over_prob": 0.45, "book_over_prob": 0.5, "edge": 0.0,
        "model_error": 0.37, "recommendation": "NO CALL", "model_version": "v1",
        "opponent_name": "", "opponent_factor": float("nan"),
        "actual": float("nan"), "outcome": "", "settled_at": "",
    }
    row.update(kw)
    return row


# Our caches: one Boston hitter who played. Nobody else is in here.
BATTING = pd.DataFrame([{"game_date": LOGS_DATE, "game_pk": 823826, "player_id": 1,
                         "player_name": "Played Hitter", "h": 2, "b2": 1, "b3": 0, "hr": 0}])
PITCHING = pd.DataFrame([{"game_date": LOGS_DATE, "game_pk": 823826, "player_id": 2,
                          "player_name": "Our Starter", "so": 5}])


class TestTheOpposingStarter:
    def test_a_player_absent_from_our_caches_is_found_in_the_box_score(self):
        preds = pd.DataFrame([_pred(999, "Tyler Phillips", "pitcher_strikeouts", 3.5)])
        calls = []

        def lookup(game_date, player_id, player_name, market):
            calls.append((game_date, player_id, market))
            return 7.0, 823826

        out, stats = grade_frame(preds, PITCHING, BATTING, boxscore_lookup=lookup)
        assert stats["boxscore"] == 1
        assert out.iloc[0]["actual"] == 7.0
        assert out.iloc[0]["outcome"] == ph.OUTCOME_OVER      # 7 over a 3.5 line
        assert out.iloc[0]["game_pk"] == 823826
        assert calls == [(LOGS_DATE, 999, "pitcher_strikeouts")]

    def test_our_own_players_never_reach_the_box_score(self):
        """One call per game is cheap; one per player is not, and unnecessary."""
        preds = pd.DataFrame([_pred(2, "Our Starter", "pitcher_strikeouts", 4.5)])
        called = []
        grade_frame(preds, PITCHING, BATTING,
                    boxscore_lookup=lambda *a: called.append(a) or (9.0, 1))
        assert called == []

    def test_a_lookup_that_raises_does_not_take_the_run_down(self):
        """A box score is not worth losing the grading of everything else."""
        preds = pd.DataFrame([_pred(999, "Someone", "pitcher_strikeouts", 3.5)])

        def boom(*a):
            raise RuntimeError("502")

        out, stats = grade_frame(preds, PITCHING, BATTING, boxscore_lookup=boom)
        assert stats["dnp"] == 1          # unfound, so terminal
        assert out.iloc[0]["outcome"] == ph.OUTCOME_DNP


class TestDidNotPlay:
    def test_a_bench_bat_gets_a_terminal_state(self):
        preds = pd.DataFrame([_pred(77, "Bench Bat", "batter_total_bases", 1.5)])
        out, stats = grade_frame(preds, PITCHING, BATTING)
        assert stats["dnp"] == 1
        assert out.iloc[0]["outcome"] == ph.OUTCOME_DNP
        assert str(out.iloc[0]["settled_at"]) != ""

    def test_it_does_not_come_back_on_the_next_run(self):
        """The whole point: blank means 'ask again', forever."""
        preds = pd.DataFrame([_pred(77, "Bench Bat", "batter_total_bases", 1.5)])
        once, _ = grade_frame(preds, PITCHING, BATTING)
        _, stats = grade_frame(once, PITCHING, BATTING)
        assert stats["dnp"] == 0
        assert stats["already"] == 1

    def test_a_game_not_played_yet_stays_open(self):
        """
        Tonight's prediction must wait for tonight, not be written off. Only
        "did not appear" is terminal; "no game on that date yet" is not.
        """
        preds = pd.DataFrame([_pred(77, "Bench Bat", "batter_total_bases", 1.5,
                                    game_date="2026-09-30")])
        out, stats = grade_frame(preds, PITCHING, BATTING)
        assert stats["dnp"] == 0
        assert stats["skipped"] == 1
        assert out.iloc[0]["outcome"] == ""

    def test_dnp_never_reaches_a_score(self):
        """
        It has no actual, so it can measure neither calibration nor projection
        error. It exists to leave the queue, not to be counted.
        """
        preds = pd.DataFrame([_pred(77, "Bench Bat", "batter_total_bases", 1.5)])
        out, _ = grade_frame(preds, PITCHING, BATTING)
        assert ph.graded(out).empty
        assert ph.OUTCOME_DNP not in ph.DIRECTIONAL

    def test_the_box_score_is_tried_before_giving_up(self):
        """Absent from our caches is not absent from the game."""
        preds = pd.DataFrame([_pred(999, "Opposing Hitter", "batter_total_bases", 1.5)])
        out, stats = grade_frame(preds, PITCHING, BATTING,
                                 boxscore_lookup=lambda *a: (3.0, 823826))
        assert stats["dnp"] == 0
        assert out.iloc[0]["outcome"] == ph.OUTCOME_OVER
