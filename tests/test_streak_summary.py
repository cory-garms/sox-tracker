"""
The streak page's commemorative summary.

Guards the reframe: every figure on the page is derived from the game log, not
from the hardcoded 15 the old template asserted regardless of the data.
"""

from __future__ import annotations

import pytest

from analysis.streaks import longest_streak_games
from streak_report import _FRANCHISE_RECORD, _pretty_date, _short_date, summarize_streak
from conftest import game, games_df


def fifteen_game_streak():
    """The real July 2026 run: 15 wins, the last being game 1 of a doubleheader."""
    rows = [game(100 + i, f"2026-07-{3 + i:02d}", 6, 2) for i in range(14)]
    rows.append(game(824735, "2026-07-22", 6, 3, game_number=1))
    rows.append(game(824732, "2026-07-22", 1, 5, game_number=2))
    return games_df(rows)


class TestDateFormatting:
    def test_pretty_date_is_month_and_day(self):
        assert _pretty_date("2026-07-03") == "July 3"

    def test_short_date_abbreviates_for_a_stat_tile(self):
        assert _short_date("2026-07-03") == "Jul 3"

    def test_no_zero_padded_day(self):
        assert _short_date("2026-07-03") == "Jul 3"

    def test_unparseable_input_passes_through(self):
        assert _pretty_date("not a date") == "not a date"


class TestSummarizeStreak:
    def test_length_and_bounds_come_from_the_data(self):
        facts = summarize_streak(longest_streak_games(fifteen_game_streak(), "W"))

        assert facts["length"] == 15
        assert facts["start"] == "2026-07-03"
        assert facts["end"] == "2026-07-22"

    def test_runs_and_differential(self):
        facts = summarize_streak(longest_streak_games(fifteen_game_streak(), "W"))

        # 14 games of 6-2 plus one 6-3
        assert facts["runs_scored"] == 14 * 6 + 6
        assert facts["runs_allowed"] == 14 * 2 + 3
        assert facts["run_diff"] == facts["runs_scored"] - facts["runs_allowed"]

    def test_average_margin(self):
        facts = summarize_streak(longest_streak_games(fifteen_game_streak(), "W"))

        assert facts["avg_margin"] == pytest.approx(
            facts["run_diff"] / facts["length"], abs=0.05
        )

    def test_shutouts_counted(self):
        rows = [
            game(1, "2026-07-01", 5, 0),
            game(2, "2026-07-02", 3, 0),
            game(3, "2026-07-03", 4, 2),
        ]

        assert summarize_streak(longest_streak_games(games_df(rows), "W"))["shutouts"] == 2

    def test_opponents_deduplicated_in_first_faced_order(self):
        rows = [
            game(1, "2026-07-01", 5, 1, opponent_id=110),
            game(2, "2026-07-02", 5, 1, opponent_id=110),
            game(3, "2026-07-03", 5, 1, opponent_id=147),
        ]

        facts = summarize_streak(longest_streak_games(games_df(rows), "W"))

        assert facts["opponents"] == ["BAL", "NYY"]

    def test_ties_record_true_at_the_franchise_mark(self):
        facts = summarize_streak(longest_streak_games(fifteen_game_streak(), "W"))

        assert facts["length"] == _FRANCHISE_RECORD
        assert facts["ties_record"] is True

    def test_ties_record_false_below_the_mark(self):
        rows = [game(i, f"2026-07-{i:02d}", 5, 1) for i in range(1, 4)]

        assert summarize_streak(longest_streak_games(games_df(rows), "W"))["ties_record"] is False

    def test_date_range_spans_start_to_end(self):
        facts = summarize_streak(longest_streak_games(fifteen_game_streak(), "W"))

        assert "July 3" in facts["date_range"]
        assert "July 22" in facts["date_range"]

    def test_empty_streak_yields_empty_summary(self):
        assert summarize_streak(longest_streak_games(games_df([]), "W")) == {}
