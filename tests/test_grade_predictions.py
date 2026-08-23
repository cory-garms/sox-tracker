"""
Outcome grading.

The regression this guards: nothing ever scored a prediction against what
happened, so the models' NO CALL discipline was unfalsifiable.

The traps this pins down, in order of how badly they would corrupt the record:

1. **Doubleheaders.** A prop is per game, not per date. Summing both ends of
   2026-07-22 invents a player who batted nine times, and every calibration
   number downstream inherits the lie.
2. **Postponements.** A game that was never played must never settle a
   prediction.
3. **Pushes.** An actual landing exactly on a whole-number line is refunded by
   the book; scoring it as a miss understates the model.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.grading import grade_frame, resolve_appearance, total_bases
from data import predictions_history as ph


def prediction(**kwargs):
    base = {
        "captured_at": "2026-08-22T15:00:00+00:00",
        "game_date": "2026-08-22", "commence_time": None, "event_id": "e1",
        "game_pk": pd.NA, "market": "pitcher_strikeouts",
        "player_id": 700, "player": "Test Starter",
        "line": 4.5, "projection": 5.1, "model_over_prob": 0.61,
        "book_over_prob": 0.52, "edge": 0.6, "model_error": 0.45,
        "recommendation": "OVER 🔥", "model_version": "v1.2",
        "opponent_name": "SF", "opponent_factor": 1.0,
        "actual": float("nan"), "outcome": "", "settled_at": "",
    }
    base.update(kwargs)
    return base


def pitching_log(**kwargs):
    base = {"player_id": 700, "player_name": "Test Starter",
            "game_date": "2026-08-22", "game_pk": 500, "so": 6, "is_starter": True}
    base.update(kwargs)
    return pd.DataFrame([base])


def batting_log(rows):
    return pd.DataFrame(rows)


EMPTY_BAT = pd.DataFrame(columns=["player_id", "player_name", "game_date", "game_pk",
                                  "h", "doubles", "triples", "hr"])
EMPTY_PIT = pd.DataFrame(columns=["player_id", "player_name", "game_date", "game_pk", "so"])


class TestTotalBases:
    @pytest.mark.parametrize("h,d,t,hr,expected", [
        (0, 0, 0, 0, 0),
        (1, 0, 0, 0, 1),      # single
        (1, 1, 0, 0, 2),      # the hit *is* the double
        (1, 0, 1, 0, 3),
        (1, 0, 0, 1, 4),
        (3, 1, 0, 1, 7),      # 1B + 2B + HR = 1+2+4
    ])
    def test_reduces_correctly(self, h, d, t, hr, expected):
        """TB = H + 2B + 2·3B + 3·HR, since a hit already counts its own base."""
        assert total_bases(pd.Series({"h": h, "doubles": d, "triples": t, "hr": hr})) == expected

    def test_missing_columns_count_as_zero(self):
        assert total_bases(pd.Series({"h": 2})) == 2


class TestGrading:
    def test_settles_a_strikeout_prediction(self):
        frame = pd.DataFrame([prediction()])
        out, stats = grade_frame(frame, pitching_log(so=6), EMPTY_BAT)
        assert stats["graded"] == 1
        assert out.loc[0, "actual"] == 6.0
        assert out.loc[0, "outcome"] == "over"
        assert out.loc[0, "game_pk"] == 500

    def test_settles_a_total_bases_prediction(self):
        frame = pd.DataFrame([prediction(market="batter_total_bases", player_id=800,
                                         player="Test Hitter", line=1.5)])
        bat = batting_log([{"player_id": 800, "player_name": "Test Hitter",
                            "game_date": "2026-08-22", "game_pk": 500,
                            "h": 2, "doubles": 1, "triples": 0, "hr": 0}])
        out, stats = grade_frame(frame, EMPTY_PIT, bat)
        assert stats["graded"] == 1
        assert out.loc[0, "actual"] == 3.0
        assert out.loc[0, "outcome"] == "over"

    def test_an_actual_on_a_whole_number_line_pushes(self):
        frame = pd.DataFrame([prediction(line=6.0)])
        out, _ = grade_frame(frame, pitching_log(so=6), EMPTY_BAT)
        assert out.loc[0, "outcome"] == "push"

    def test_records_when_it_settled(self):
        frame = pd.DataFrame([prediction()])
        out, _ = grade_frame(frame, pitching_log(), EMPTY_BAT, now="2026-08-23T04:00:00+00:00")
        assert out.loc[0, "settled_at"] == "2026-08-23T04:00:00+00:00"

    def test_an_already_settled_row_is_untouched(self):
        frame = pd.DataFrame([prediction(actual=9.0, outcome="over", settled_at="earlier")])
        out, stats = grade_frame(frame, pitching_log(so=2), EMPTY_BAT)
        assert stats["graded"] == 0
        assert stats["already"] == 1
        assert out.loc[0, "actual"] == 9.0      # not overwritten by the new log
        assert out.loc[0, "settled_at"] == "earlier"

    def test_a_prediction_for_an_unplayed_game_waits(self):
        """Tonight's projection simply stays ungraded until tonight finishes."""
        frame = pd.DataFrame([prediction(game_date="2026-09-01")])
        out, stats = grade_frame(frame, pitching_log(), EMPTY_BAT)
        assert stats["graded"] == 0
        assert out.loc[0, "outcome"] == ""

    def test_a_postponed_game_never_settles(self):
        """
        The cache only holds games that were actually played, so a postponement
        leaves no row to join to and the prediction stays open.
        """
        frame = pd.DataFrame([prediction(game_date="2026-08-22")])
        out, stats = grade_frame(frame, EMPTY_PIT, EMPTY_BAT)
        assert stats["graded"] == 0
        assert out.loc[0, "outcome"] == ""

    def test_a_player_who_did_not_appear_is_not_settled(self):
        frame = pd.DataFrame([prediction(player_id=999, player="Someone Else")])
        out, stats = grade_frame(frame, pitching_log(), EMPTY_BAT)
        assert stats["graded"] == 0

    def test_an_unknown_market_is_skipped(self):
        frame = pd.DataFrame([prediction(market="team_totals")])
        _, stats = grade_frame(frame, pitching_log(), EMPTY_BAT)
        assert stats["skipped"] == 1


class TestDoubleheaders:
    """
    2026-07-22 is a real doubleheader in the cache, and the date whose game 1
    carries the *higher* gamePk — the case that has already broken this project
    once.
    """

    def test_a_starter_resolves_cleanly(self):
        """A pitcher starts one end of a doubleheader, so there is no ambiguity."""
        logs = pd.DataFrame([
            {"player_id": 700, "player_name": "SP", "game_date": "2026-07-22",
             "game_pk": 824735, "so": 7},
        ])
        row, reason = resolve_appearance(logs, 700, "SP", "2026-07-22")
        assert reason == "ok"
        assert row["game_pk"] == 824735

    def test_a_batter_in_both_games_is_refused_not_guessed(self):
        logs = pd.DataFrame([
            {"player_id": 800, "player_name": "BAT", "game_date": "2026-07-22",
             "game_pk": 824735, "h": 2, "doubles": 0, "triples": 0, "hr": 0},
            {"player_id": 800, "player_name": "BAT", "game_date": "2026-07-22",
             "game_pk": 824732, "h": 1, "doubles": 1, "triples": 0, "hr": 0},
        ])
        row, reason = resolve_appearance(logs, 800, "BAT", "2026-07-22")
        assert row is None
        assert "ambiguous" in reason

    def test_totals_are_never_summed_across_a_doubleheader(self):
        """
        The failure mode: 2 TB in game one plus 3 in game two graded as a
        5-total-base day against a 1.5 line.
        """
        frame = pd.DataFrame([prediction(market="batter_total_bases", player_id=800,
                                         player="BAT", game_date="2026-07-22", line=1.5)])
        bat = batting_log([
            {"player_id": 800, "player_name": "BAT", "game_date": "2026-07-22",
             "game_pk": 824735, "h": 2, "doubles": 0, "triples": 0, "hr": 0},
            {"player_id": 800, "player_name": "BAT", "game_date": "2026-07-22",
             "game_pk": 824732, "h": 1, "doubles": 1, "triples": 0, "hr": 0},
        ])
        out, stats = grade_frame(frame, EMPTY_PIT, bat)
        assert stats["graded"] == 0
        assert out.loc[0, "outcome"] == ""
        assert pd.isna(out.loc[0, "actual"])

    def test_a_single_appearance_on_a_doubleheader_date_still_grades(self):
        """A bench bat used in only one end resolves fine."""
        frame = pd.DataFrame([prediction(market="batter_total_bases", player_id=801,
                                         player="BENCH", game_date="2026-07-22", line=0.5)])
        bat = batting_log([
            {"player_id": 801, "player_name": "BENCH", "game_date": "2026-07-22",
             "game_pk": 824732, "h": 1, "doubles": 0, "triples": 0, "hr": 0},
        ])
        out, stats = grade_frame(frame, EMPTY_PIT, bat)
        assert stats["graded"] == 1
        assert out.loc[0, "actual"] == 1.0


class TestPredictionsWithNoBookLine:
    """
    Most logged projections never had a line matched to them. They still settle
    — the actual measures projection error — but they carry no over/under, so
    they must stay out of calibration and must not return to the queue forever.
    """

    def _graded_once(self):
        frame = pd.DataFrame([prediction(line=float("nan"))])
        return grade_frame(frame, pitching_log(so=6), EMPTY_BAT)

    def test_the_actual_is_still_recorded(self):
        out, stats = self._graded_once()
        assert stats["graded"] == 1
        assert out.loc[0, "actual"] == 6.0

    def test_it_is_marked_settled_rather_than_left_blank(self):
        out, _ = self._graded_once()
        assert out.loc[0, "outcome"] == ph.OUTCOME_NO_LINE

    def test_it_does_not_come_back_around_on_the_next_run(self):
        out, _ = self._graded_once()
        _, stats = grade_frame(out, pitching_log(so=6), EMPTY_BAT)
        assert stats["graded"] == 0
        assert stats["already"] == 1

    def test_it_is_excluded_from_scoring(self):
        out, _ = self._graded_once()
        assert ph.graded(out).empty

    def test_but_is_available_for_projection_error(self):
        out, _ = self._graded_once()
        assert len(ph.with_actuals(out)) == 1


class TestGradedRowsAreUsable:
    def test_every_graded_row_has_a_line(self):
        """
        The Phase 1 regression, restated as a property of the output: a row with
        no line cannot be scored and must not appear graded.
        """
        frame = pd.DataFrame([prediction(), prediction(player="No Line", line=float("nan"),
                                                       captured_at="2026-08-22T16:00:00+00:00")])
        logs = pd.DataFrame([
            {"player_id": 700, "player_name": "Test Starter", "game_date": "2026-08-22",
             "game_pk": 500, "so": 6},
            {"player_id": 700, "player_name": "No Line", "game_date": "2026-08-22",
             "game_pk": 500, "so": 6},
        ])
        out, _ = grade_frame(frame, logs, EMPTY_BAT)
        settled = ph.graded(out)
        assert not settled.empty
        assert settled["line"].notna().all()
