"""
Schedule ingestion — the filtering that decides what counts as a played game.

MLB reports a postponed game with abstractGameState "Final", and re-reports the
same gamePk under its makeup date. Both traps produced bad cache rows.
"""

from __future__ import annotations

import pytest

from data.fetcher import parse_schedule
from conftest import BOS, schedule_entry


class TestPostponedGames:
    def test_postponed_game_is_excluded(self):
        """
        A postponed game carries abstractGameState "Final" with a 0-0 score. It
        used to pass the completed filter and land in the cache as a phantom
        loss.
        """
        raw = [
            schedule_entry(1, "2026-07-20", 6, 5),
            schedule_entry(2, "2026-07-21", 0, 0, detailed_state="Postponed"),
        ]

        rows = parse_schedule(raw, BOS, 2026)

        assert [r["game_pk"] for r in rows] == [1]

    @pytest.mark.parametrize("state", ["Postponed", "Cancelled", "Canceled", "Suspended"])
    def test_all_unplayed_states_are_excluded(self, state):
        raw = [schedule_entry(1, "2026-07-21", 0, 0, detailed_state=state)]

        assert parse_schedule(raw, BOS, 2026) == []

    def test_scheduled_games_are_excluded(self):
        raw = [schedule_entry(1, "2026-08-01", 0, 0,
                              abstract_state="Preview", detailed_state="Scheduled")]

        assert parse_schedule(raw, BOS, 2026) == []


class TestDuplicateGamePks:
    def test_same_pk_under_two_dates_yields_one_row(self):
        """
        pk 824735 appears twice: once as the postponed 07-21 entry and once as
        the played 07-22 makeup. Only the played one should survive.
        """
        raw = [
            schedule_entry(824735, "2026-07-22", 0, 0, detailed_state="Postponed"),
            schedule_entry(824735, "2026-07-22", 6, 3, game_number=1),
        ]

        rows = parse_schedule(raw, BOS, 2026)

        assert len(rows) == 1
        assert rows[0]["runs_scored"] == 6

    def test_dedupe_is_keyed_on_pk_not_date(self):
        raw = [
            schedule_entry(500, "2026-07-01", 4, 2),
            schedule_entry(500, "2026-07-01", 4, 2),
            schedule_entry(501, "2026-07-01", 1, 3, game_number=2),
        ]

        rows = parse_schedule(raw, BOS, 2026)

        assert sorted(r["game_pk"] for r in rows) == [500, 501]


class TestDoubleheaderOrdering:
    def test_game_one_precedes_game_two_regardless_of_pk(self):
        raw = [
            schedule_entry(824732, "2026-07-22", 1, 5, game_number=2),
            schedule_entry(824735, "2026-07-22", 6, 3, game_number=1),
        ]

        rows = parse_schedule(raw, BOS, 2026)

        assert [r["game_pk"] for r in rows] == [824735, 824732]
        assert [r["result"] for r in rows] == ["W", "L"]

    def test_game_num_is_sequential_in_playing_order(self):
        raw = [
            schedule_entry(824732, "2026-07-22", 1, 5, game_number=2),
            schedule_entry(824735, "2026-07-22", 6, 3, game_number=1),
            schedule_entry(824700, "2026-07-19", 6, 1),
        ]

        rows = parse_schedule(raw, BOS, 2026)

        assert [r["game_num"] for r in rows] == [1, 2, 3]
        assert [r["game_pk"] for r in rows] == [824700, 824735, 824732]

    def test_game_number_is_captured(self):
        raw = [schedule_entry(1, "2026-07-22", 6, 3, game_number=2)]

        assert parse_schedule(raw, BOS, 2026)[0]["game_number"] == 2

    def test_missing_game_number_defaults_to_one(self):
        entry = schedule_entry(1, "2026-07-22", 6, 3)
        del entry["gameNumber"]

        assert parse_schedule([entry], BOS, 2026)[0]["game_number"] == 1


class TestResultAssignment:
    def test_win_loss_and_tie(self):
        raw = [
            schedule_entry(1, "2026-04-01", 6, 3),
            schedule_entry(2, "2026-04-02", 2, 8),
            schedule_entry(3, "2026-04-03", 4, 4),
        ]

        assert [r["result"] for r in parse_schedule(raw, BOS, 2026)] == ["W", "L", "T"]

    def test_scoreless_game_is_a_tie_not_a_loss(self):
        """A 0-0 row used to score as "L" because the check was `else: "L"`."""
        raw = [schedule_entry(1, "2026-04-01", 0, 0)]

        assert parse_schedule(raw, BOS, 2026)[0]["result"] == "T"

    def test_home_and_away_scores_map_to_the_tracked_team(self):
        raw = [
            schedule_entry(1, "2026-04-01", 7, 2, home=True),
            schedule_entry(2, "2026-04-02", 7, 2, home=False),
        ]

        rows = parse_schedule(raw, BOS, 2026)

        assert [r["runs_scored"] for r in rows] == [7, 7]
        assert [r["is_home"] for r in rows] == [True, False]
        assert all(r["result"] == "W" for r in rows)
