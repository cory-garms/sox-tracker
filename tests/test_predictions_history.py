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


class TestTheKeyIsANoOpOnHistory:
    """
    latest_per_game is now keyed by event, not by date.

    A prop is per game and a doubleheader puts two games on one date, so the
    old key collapsed both ends into whichever was captured later: one of the
    two predictions vanished rather than being scored. 2026-08-29 at Yankee
    Stadium is the first doubleheader this archive will hold predictions for.

    The change is only safe if it leaves every existing row alone, and that is
    checkable rather than arguable: no date in the archive has ever carried two
    event_ids, so the two keys must partition it identically. This reads the
    real file when it is present and says so when it is not, because the claim
    is about this archive and not about a fixture.
    """

    def _history(self):
        if not ph.HISTORY_PATH.exists():
            pytest.skip(f"no archive at {ph.HISTORY_PATH}")
        frame = ph.load_history()
        if frame.empty:
            pytest.skip("archive is empty")
        return frame

    def test_a_mislabelled_row_cannot_reach_scoring(self):
        """
        game_date comes from the runner's clock, the event from find_event, and
        on a build that straddles a game they disagree.

        Observed twice: the 08-27 builds (an off day) and the 08-28 late builds
        (after midnight UTC, still pointing at that night's game in progress).
        Both filed predictions under a date whose game they were not about.

        Almost all of it is harmless -- the same builds are in-play captures,
        and the filter above discards them before anything is scored. What is
        not harmless is a *pre-game* projection filed under the wrong date: it
        is a real prediction about a real game that can never be graded,
        because grading looks for a game on its game_date and finds none.

        One such batch exists, from the 2026-08-27 20:57Z build. This asserts
        that set does not grow -- the count is deliberately not pinned, since
        the roster size behind it may change, but a *new date* appearing here
        means the bug has bitten again and wants a human.
        """
        frame = self._history()
        kept = ph.latest_per_game(frame)
        event_day = (
            pd.to_datetime(kept["commence_time"], utc=True, errors="coerce")
            .dt.tz_convert("America/New_York").dt.date.astype(str)
        )
        orphan_dates = set(kept.loc[event_day != kept["game_date"].astype(str), "game_date"])
        assert orphan_dates <= {"2026-08-27"}, (
            f"predictions filed under a date they are not about: {sorted(orphan_dates)}"
        )

    def test_the_in_play_half_is_discarded_before_scoring(self):
        """The reason the above is a leak and not a flood."""
        frame = self._history()
        event_day = (
            pd.to_datetime(frame["commence_time"], utc=True, errors="coerce")
            .dt.tz_convert("America/New_York").dt.date.astype(str)
        )
        mislabelled = (event_day != frame["game_date"].astype(str)).sum()
        kept = ph.latest_per_game(frame)
        kept_day = (
            pd.to_datetime(kept["commence_time"], utc=True, errors="coerce")
            .dt.tz_convert("America/New_York").dt.date.astype(str)
        )
        survived = (kept_day != kept["game_date"].astype(str)).sum()
        assert survived < mislabelled, "the filter is not removing any of them"

    def test_the_two_keys_select_the_same_rows(self):
        frame = self._history()
        new = ph.latest_per_game(frame)

        ordered = frame.sort_values("captured_at")
        commence = pd.to_datetime(ordered["commence_time"], utc=True, errors="coerce")
        captured = pd.to_datetime(ordered["captured_at"], utc=True, errors="coerce")
        ordered = ordered[~(commence.notna() & captured.notna() & (captured >= commence))]
        old = ordered.groupby(["game_date", "market", "player"], sort=False).tail(1)

        assert len(new) == len(old)
        assert sorted(new.index) == sorted(old.index)

    def test_a_doubleheader_keeps_both_ends(self):
        """A fixture, because the archive has no such date yet -- until Saturday."""
        rows = []
        for event, commence in (("e1", "2026-08-29T17:05:00Z"),
                                ("e2", "2026-08-29T23:15:00Z")):
            rows.append({
                "captured_at": "2026-08-29T15:00:00+00:00",
                "game_date": "2026-08-29", "commence_time": commence,
                "event_id": event, "market": "batter_total_bases",
                "player": "BAT", "player_id": 800, "line": 1.5,
            })
        keep = ph.latest_per_game(pd.DataFrame(rows))
        assert len(keep) == 2
        assert set(keep["event_id"]) == {"e1", "e2"}


class TestBothEndsOfADoubleheaderAreWritten:
    """
    The write-side twin of TestTheKeyIsANoOpOnHistory, and the worse of the two.

    A doubleheader logs both games from a single build, so game 1 and game 2
    share captured_at, market, player and game_date -- every field the dedupe
    key had. The nightcap's rows were therefore dropped as duplicates of the
    opener's, by the mechanism that exists to drop duplicates, leaving no trace.

    Caught on 2026-08-29 by the board rendering two games and the log holding
    one. The read-side fix could not have saved it: latest_per_game can only
    pick among rows that were written.
    """

    def _row(self, event_id, player="BAT", captured="2026-08-29T12:00:00+00:00"):
        return {
            "captured_at": captured, "game_date": "2026-08-29",
            "commence_time": "2026-08-29T17:05:00Z", "event_id": event_id,
            "market": "batter_total_bases", "player": player, "player_id": 800,
            "line": 1.5, "projection": 1.8,
        }

    def test_the_nightcap_is_not_dropped_as_a_duplicate_of_the_opener(self, tmp_path):
        path = tmp_path / "history.parquet"
        added = ph.append_snapshot(
            [self._row("evt-g1"), self._row("evt-g2")], path=path
        )
        assert added == 2
        frame = ph.load_history(path)
        assert set(frame["event_id"]) == {"evt-g1", "evt-g2"}

    def test_a_genuine_repeat_of_the_same_game_still_dedupes(self, tmp_path):
        """The key still has to do the job it was added for."""
        path = tmp_path / "history.parquet"
        ph.append_snapshot([self._row("evt-g1")], path=path)
        added = ph.append_snapshot([self._row("evt-g1")], path=path)
        assert added == 0
        assert len(ph.load_history(path)) == 1

    def test_event_id_is_in_the_key(self):
        assert "event_id" in ph.KEY
