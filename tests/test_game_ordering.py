"""
Game ordering and streak detection.

These cover the bug that made the 2026 win streak read as 14 games instead of
15: sorting by game_pk puts a doubleheader's makeup game after the nightcap,
because gamePk is assigned at scheduling time rather than playing time.
"""

from __future__ import annotations

import pandas as pd

from analysis.streaks import (
    current_streak,
    longest_streak,
    longest_streak_games,
    played_in_order,
)
from conftest import game, games_df


class TestPlayedInOrder:
    def test_orders_doubleheader_by_game_number_not_pk(self):
        """
        The real 2026-07-22 doubleheader: the makeup game (pk 824735) was game 1
        and a win; the nightcap (pk 824732) was game 2 and a loss. Sorting by pk
        would put the loss first.
        """
        df = games_df([
            game(824736, "2026-07-20", 6, 5),
            game(824732, "2026-07-22", 1, 5, game_number=2),   # lower pk, played 2nd
            game(824735, "2026-07-22", 6, 3, game_number=1),   # higher pk, played 1st
        ])

        ordered = played_in_order(df)

        assert list(ordered["game_pk"]) == [824736, 824735, 824732]
        assert list(ordered["result"]) == ["W", "W", "L"]

    def test_excludes_non_final_games(self):
        df = games_df([
            game(1, "2026-04-01", 5, 1),
            game(2, "2026-04-02", 0, 0, status="Postponed"),
            game(3, "2026-04-03", 2, 7),
        ])

        ordered = played_in_order(df)

        assert list(ordered["game_pk"]) == [1, 3]

    def test_falls_back_to_game_pk_when_game_number_absent(self):
        """Caches written before game_number existed must still order sensibly."""
        df = games_df([
            game(20, "2026-04-02", 3, 2),
            game(10, "2026-04-01", 1, 0),
        ]).drop(columns=["game_number"])

        ordered = played_in_order(df)

        assert list(ordered["game_pk"]) == [10, 20]

    def test_returns_empty_frame_for_no_completed_games(self):
        df = games_df([game(1, "2026-04-01", 0, 0, status="Postponed")])

        assert played_in_order(df).empty

    def test_reindexes_from_zero(self):
        df = games_df([
            game(2, "2026-04-02", 1, 0),
            game(1, "2026-04-01", 1, 0),
        ])

        assert list(played_in_order(df).index) == [0, 1]


class TestCurrentStreak:
    def test_reads_streak_from_playing_order_not_pk_order(self):
        """
        With the doubleheader ordered correctly the day ends on a loss, so the
        current streak is L1 — not the W it would be under a pk sort.
        """
        df = games_df([
            game(824736, "2026-07-20", 6, 5),
            game(824732, "2026-07-22", 1, 5, game_number=2),
            game(824735, "2026-07-22", 6, 3, game_number=1),
        ])

        assert current_streak(df) == ("L", 1)

    def test_counts_consecutive_wins(self):
        df = games_df([
            game(1, "2026-04-01", 1, 5),
            game(2, "2026-04-02", 5, 1),
            game(3, "2026-04-03", 6, 2),
            game(4, "2026-04-04", 3, 1),
        ])

        assert current_streak(df) == ("W", 3)

    def test_empty_when_nothing_played(self):
        assert current_streak(games_df([game(1, "2026-04-01", 0, 0,
                                             status="Postponed")])) == ("", 0)


class TestLongestStreakGames:
    def test_doubleheader_win_extends_the_streak_to_fifteen(self):
        """
        A 15-game streak whose final win is game 1 of a doubleheader, followed
        by a loss in game 2. Under a game_pk sort the loss lands first and the
        streak truncates to 14 — this is the exact regression.
        """
        rows = [game(100 + i, f"2026-07-{3 + i:02d}", 5, 1) for i in range(14)]
        rows.append(game(824735, "2026-07-22", 6, 3, game_number=1))   # 15th win
        rows.append(game(824732, "2026-07-22", 1, 5, game_number=2))   # streak ends

        streak = longest_streak_games(games_df(rows), "W")

        assert len(streak) == 15
        assert streak["game_date"].iloc[-1] == "2026-07-22"
        assert streak["game_pk"].iloc[-1] == 824735
        assert (streak["result"] == "W").all()

    def test_picks_the_earliest_of_equally_long_streaks(self):
        rows = [
            game(1, "2026-04-01", 5, 1),
            game(2, "2026-04-02", 5, 1),
            game(3, "2026-04-03", 1, 5),
            game(4, "2026-04-04", 5, 1),
            game(5, "2026-04-05", 5, 1),
        ]

        streak = longest_streak_games(games_df(rows), "W")

        assert len(streak) == 2
        assert list(streak["game_pk"]) == [1, 2]

    def test_finds_loss_streaks_too(self):
        rows = [
            game(1, "2026-04-01", 5, 1),
            game(2, "2026-04-02", 0, 3),
            game(3, "2026-04-03", 1, 4),
        ]

        streak = longest_streak_games(games_df(rows), "L")

        assert len(streak) == 2
        assert (streak["result"] == "L").all()

    def test_empty_when_no_such_result_exists(self):
        rows = [game(1, "2026-04-01", 5, 1), game(2, "2026-04-02", 6, 2)]

        assert longest_streak_games(games_df(rows), "L").empty

    def test_streak_of_whole_season(self):
        rows = [game(i, f"2026-04-{i:02d}", 5, 1) for i in range(1, 6)]

        assert len(longest_streak_games(games_df(rows), "W")) == 5

    def test_longest_streak_length_matches_the_segment(self):
        rows = [game(i, f"2026-04-{i:02d}", 5, 1) for i in range(1, 5)]
        rows.append(game(9, "2026-04-09", 1, 5))

        df = games_df(rows)

        assert longest_streak(df, "W") == len(longest_streak_games(df, "W")) == 4
