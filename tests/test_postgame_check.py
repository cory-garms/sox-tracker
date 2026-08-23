"""
Post-game rebuild gate.

The regression this guards: the four scheduled builds are aimed at the pre-game
board, so a night game's result did not reach the site until 07:00 the next
morning. This gate closes that window — but only if it stays free, only fires
for games that were actually played, and never rebuilds the same game twice.

Runs fully offline against a fake schedule client.
"""

from __future__ import annotations

import json

import pytest

import config
from scripts.postgame_check import (
    completed_games,
    load_state,
    pending_games,
    save_state,
)


class FakeClient:
    """
    Stands in for MLBClient, matching get_schedule's real contract: a flat list
    of games, each carrying the officialDate the client injects.
    """

    def __init__(self, games):
        self._games = games
        self.calls: list[dict] = []

    def get_schedule(self, **kwargs):
        self.calls.append(kwargs)
        return list(self._games)


def game(pk, date, *, state="Final", detailed="Final", number=1):
    return {
        "gamePk": pk,
        "gameNumber": number,
        "officialDate": date,
        "status": {"abstractGameState": state, "detailedState": detailed},
    }


class TestWhatCountsAsComplete:
    def test_a_finished_game_is_reported(self):
        client = FakeClient([game(1, "2026-08-22")])
        assert [g["game_pk"] for g in completed_games(client)] == [1]

    def test_a_game_in_progress_is_not(self):
        client = FakeClient([game(1, "2026-08-22", state="Live", detailed="In Progress")])
        assert completed_games(client) == []

    @pytest.mark.parametrize("detailed", ["Postponed", "Cancelled", "Canceled", "Suspended"])
    def test_a_game_that_was_never_played_is_not(self, detailed):
        """
        Postponed games keep abstractGameState "Final". Rebuilding on one would
        republish the same pages and burn a marker on a game that never
        happened.
        """
        client = FakeClient([game(1, "2026-08-22", detailed=detailed)])
        assert completed_games(client) == []

    def test_both_ends_of_a_doubleheader_are_reported(self):
        """Tracked per gamePk, so the nightcap cannot mask game one."""
        client = FakeClient([
            game(824735, "2026-07-22", number=1),
            game(824732, "2026-07-22", number=2),
        ])
        found = completed_games(client)
        assert {g["game_pk"] for g in found} == {824735, 824732}
        assert {g["game_number"] for g in found} == {1, 2}

    def test_a_schedule_read_failure_reports_nothing_rather_than_raising(self):
        class Broken:
            def get_schedule(self, **kwargs):
                raise ConnectionError("MLB unreachable")

        assert completed_games(Broken()) == []

    def test_the_date_reported_is_the_one_the_game_counts_for(self):
        """A makeup game carries an officialDate later than its original."""
        client = FakeClient([game(1, "2026-07-22")])
        assert completed_games(client)[0]["game_date"] == "2026-07-22"


class TestStateFile:
    def test_a_processed_game_is_not_pending_again(self, tmp_path):
        state = tmp_path / "postgame_state.json"
        save_state({1}, state)
        client = FakeClient([game(1, "2026-08-22")])
        assert pending_games(client, state_path=state) == []

    def test_an_unprocessed_game_is_pending(self, tmp_path):
        state = tmp_path / "postgame_state.json"
        save_state({1}, state)
        client = FakeClient([game(1, "2026-08-22"), game(2, "2026-08-23")])
        assert [g["game_pk"] for g in pending_games(client, state_path=state)] == [2]

    def test_a_missing_state_file_makes_everything_pending(self, tmp_path):
        client = FakeClient([game(1, "2026-08-22")])
        state = tmp_path / "nope.json"
        assert [g["game_pk"] for g in pending_games(client, state_path=state)] == [1]

    def test_a_corrupt_state_file_does_not_crash_the_gate(self, tmp_path):
        state = tmp_path / "postgame_state.json"
        state.write_text("{not json", encoding="utf-8")
        assert load_state(state) == set()

    def test_state_round_trips(self, tmp_path):
        state = tmp_path / "postgame_state.json"
        save_state({3, 1, 2}, state)
        assert load_state(state) == {1, 2, 3}

    def test_the_file_stays_bounded(self, tmp_path):
        """Committed on every post-game run, so it must not grow without limit."""
        state = tmp_path / "postgame_state.json"
        save_state(set(range(1000)), state)
        kept = json.loads(state.read_text())["processed_game_pks"]
        assert len(kept) == 400
        assert kept[-1] == 999


class TestCost:
    def test_the_gate_makes_exactly_one_free_schedule_call(self):
        """
        The whole design rests on the gate being free. One MLB schedule read,
        and nothing that touches the odds provider.
        """
        client = FakeClient([game(1, "2026-08-22")])
        completed_games(client)
        assert len(client.calls) == 1
        assert client.calls[0]["team_id"] == config.TEAM_ID
