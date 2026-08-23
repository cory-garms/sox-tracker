"""
Predictions history log.

The regression this guards: the database archive recorded only what the models
*said*, never what happened, and read column names the models do not emit — so
every archived row's `line` was NULL and none of it could be graded.

This log is the durable record the track record page is built from. The
properties below are the ones that make it trustworthy: it never loses a graded
row to a re-run, it never invents an outcome, and a push is a push.
"""

from __future__ import annotations

import pandas as pd
import pytest

from data import predictions_history as ph


def _frame():
    return pd.DataFrame([{
        "player_id": 700, "player_name": "Test Starter", "prop_line": 4.5,
        "proj_k": 5.1, "edge": 0.6, "model_over_prob": 0.61,
        "book_over_prob": 0.52, "recommendation": "OVER 🔥", "opp_k_factor": 1.04,
    }])


def _rows(**kwargs):
    base = dict(
        frame=_frame(), market="pitcher_strikeouts", game_date="2026-08-22",
        model_version="v1.2", model_error=0.45,
        line_col="prop_line", projection_col="proj_k", edge_col="edge",
        captured_at="2026-08-22T15:00:00+00:00",
    )
    base.update(kwargs)
    return ph.snapshot_rows(**base)


class TestSnapshotRows:
    def test_carries_the_line(self):
        """The exact failure in the DB archiver: line came through as None."""
        assert _rows()[0]["line"] == 4.5

    def test_carries_projection_edge_and_error(self):
        row = _rows()[0]
        assert row["projection"] == 5.1
        assert row["edge"] == 0.6
        assert row["model_error"] == 0.45

    def test_starts_ungraded(self):
        row = _rows()[0]
        assert row["outcome"] == ""
        assert pd.isna(row["actual"])

    def test_an_empty_frame_logs_nothing(self):
        assert ph.snapshot_rows(
            frame=pd.DataFrame(), market="m", game_date="2026-08-22",
            model_version="v1", model_error=0.4,
            line_col="prop_line", projection_col="proj_k", edge_col="edge",
        ) == []

    def test_a_frame_missing_a_named_column_logs_nothing_rather_than_nulls(self):
        """
        Refusing beats silently writing None. The DB archiver's whole failure
        was that a missing column read as None and nobody noticed.
        """
        assert _rows(projection_col="does_not_exist") == []

    def test_a_row_with_no_book_line_is_still_logged(self):
        """Projections without a line are most of the sample and still gradeable."""
        frame = _frame()
        frame.loc[0, "prop_line"] = None
        rows = _rows(frame=frame)
        assert len(rows) == 1
        assert pd.isna(rows[0]["line"])


class TestAppendAndLoad:
    def test_round_trips(self, tmp_path):
        path = tmp_path / "p.parquet"
        assert ph.append_snapshot(_rows(), path) == 1
        assert len(ph.load_history(path)) == 1

    def test_the_same_build_appended_twice_adds_nothing(self, tmp_path):
        path = tmp_path / "p.parquet"
        ph.append_snapshot(_rows(), path)
        assert ph.append_snapshot(_rows(), path) == 0
        assert len(ph.load_history(path)) == 1

    def test_a_later_capture_is_a_new_row(self, tmp_path):
        path = tmp_path / "p.parquet"
        ph.append_snapshot(_rows(), path)
        ph.append_snapshot(_rows(captured_at="2026-08-22T18:00:00+00:00"), path)
        assert len(ph.load_history(path)) == 2

    def test_re_appending_does_not_undo_grading(self, tmp_path):
        """
        A rebuild must never wipe an outcome already recorded. keep="first"
        holds the graded copy.
        """
        path = tmp_path / "p.parquet"
        ph.append_snapshot(_rows(), path)

        frame = ph.load_history(path)
        frame.loc[0, ["actual", "outcome", "settled_at"]] = [6.0, "over", "2026-08-23T02:00:00+00:00"]
        ph.write_history(frame, path)

        ph.append_snapshot(_rows(), path)
        assert ph.load_history(path).loc[0, "outcome"] == "over"

    def test_a_missing_file_loads_empty_with_the_right_columns(self, tmp_path):
        frame = ph.load_history(tmp_path / "nope.parquet")
        assert frame.empty
        assert list(frame.columns) == ph.COLUMNS

    def test_an_unwritable_path_returns_zero_rather_than_raising(self, tmp_path):
        blocked = tmp_path / "afile"
        blocked.write_text("not a directory")
        assert ph.append_snapshot(_rows(), blocked / "p.parquet") == 0


class TestSettle:
    @pytest.mark.parametrize("actual,line,expected", [
        (6, 4.5, "over"),
        (3, 4.5, "under"),
        (5, 5.0, "push"),      # whole-number line landed on exactly
        (6, 5.0, "over"),
        (4, 5.0, "under"),
    ])
    def test_classifies_against_the_line(self, actual, line, expected):
        assert ph.settle(actual, line) == expected

    def test_a_whole_number_line_can_push(self):
        """Books refund it; scoring it a miss would understate the model."""
        assert ph.settle(2.0, 2.0) == ph.OUTCOME_PUSH

    def test_a_half_point_line_never_pushes(self):
        assert ph.settle(2.0, 1.5) == ph.OUTCOME_OVER
        assert ph.settle(1.0, 1.5) == ph.OUTCOME_UNDER

    def test_no_actual_is_not_classified(self):
        assert ph.settle(None, 4.5) == ""
        assert ph.settle(float("nan"), 4.5) == ""

    def test_no_line_is_not_guessed_at(self):
        assert ph.settle(6.0, None) == ""


class TestLatestPerGame:
    """
    The regression this guards: every build logs a snapshot, so scoring the raw
    log counts the same player-game once per build. In the real backfill 882
    directional rows were only 164 distinct player-games, and one pitcher-game
    had been captured 23 times — a sample five times overstated, weighted by how
    often each game happened to be captured.
    """

    def _log(self):
        return pd.DataFrame([
            {"game_date": "2026-08-20", "market": "pitcher_strikeouts", "player": "SP",
             "captured_at": "2026-08-20T11:00:00+00:00", "line": 4.5, "projection": 5.0},
            {"game_date": "2026-08-20", "market": "pitcher_strikeouts", "player": "SP",
             "captured_at": "2026-08-20T19:00:00+00:00", "line": 5.5, "projection": 5.0},
            {"game_date": "2026-08-20", "market": "pitcher_strikeouts", "player": "SP",
             "captured_at": "2026-08-20T15:00:00+00:00", "line": 5.0, "projection": 5.0},
            {"game_date": "2026-08-21", "market": "pitcher_strikeouts", "player": "SP",
             "captured_at": "2026-08-21T15:00:00+00:00", "line": 4.5, "projection": 5.2},
        ])

    def test_collapses_repeat_captures_to_one_row(self):
        assert len(ph.latest_per_game(self._log())) == 2

    def test_keeps_the_last_capture_before_first_pitch(self):
        """The most informed projection, and the one comparable to a close."""
        out = ph.latest_per_game(self._log())
        row = out[out["game_date"] == "2026-08-20"].iloc[0]
        assert row["captured_at"] == "2026-08-20T19:00:00+00:00"
        assert row["line"] == 5.5

    def test_keeps_separate_games_separate(self):
        assert set(ph.latest_per_game(self._log())["game_date"]) == {"2026-08-20", "2026-08-21"}

    def test_does_not_stitch_columns_from_different_rows(self):
        """
        groupby().last() takes the last non-null of each column independently
        and can produce a row that never existed.
        """
        log = self._log()
        log.loc[1, "line"] = None            # latest capture has a null line
        row = ph.latest_per_game(log)
        row = row[row["game_date"] == "2026-08-20"].iloc[0]
        assert row["captured_at"] == "2026-08-20T19:00:00+00:00"
        assert pd.isna(row["line"]), "line was back-filled from an earlier capture"

    def test_an_empty_log_is_handled(self):
        assert ph.latest_per_game(pd.DataFrame(columns=ph.COLUMNS)).empty


class TestGradedAndUngraded:
    def _log(self):
        return pd.DataFrame([
            {"outcome": "over"}, {"outcome": "under"}, {"outcome": "push"},
            {"outcome": "void"}, {"outcome": ""}, {"outcome": None},
        ])

    def test_ungraded_finds_the_unsettled(self):
        assert len(ph.ungraded(self._log())) == 2

    def test_graded_excludes_voids(self):
        """A void game says nothing about the model and must not be scored."""
        out = ph.graded(self._log())
        assert len(out) == 3
        assert "void" not in set(out["outcome"])
