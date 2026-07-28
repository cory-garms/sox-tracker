"""
Ranking what moved.

The two design decisions worth guarding are both about not misleading a reader:
movement is measured in de-vigged probability rather than in odds, and a line
move is kept separate from a price move. Either shortcut would produce a list
that looks authoritative and is ordered by the wrong thing.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.betting import biggest_movers
from data import odds_history

EVENT = {
    "id": "evt-move",
    "commence_time": "2026-07-28T01:40:00Z",
    "home_team": "Athletics",
    "away_team": "Boston Red Sox",
}


def history(*snapshots) -> pd.DataFrame:
    """snapshots: (stamp, market, player, line, over, under) tuples."""
    rows = []
    for stamp, market, player, line, over, under in snapshots:
        rows += odds_history.snapshot_rows(
            EVENT, market,
            {player: {"line": line, "over_odds": over, "under_odds": under}},
            captured_at=stamp,
        )
    return pd.DataFrame(rows).reindex(columns=odds_history.COLUMNS)


T0, T1 = "2026-07-27T19:00:00+00:00", "2026-07-27T23:00:00+00:00"


class TestMeasuredInProbabilityNotOdds:
    def test_a_long_price_move_can_rank_below_a_short_one(self):
        """
        +200 -> +190 is a smaller shift in probability than -110 -> -130,
        even though the odds moved by ten points in one case and twenty in the
        other. Ranking on raw odds would invert these.
        """
        h = history(
            (T0, "batter_total_bases", "Long", 1.5, 200, -240),
            (T1, "batter_total_bases", "Long", 1.5, 190, -230),
            (T0, "batter_total_bases", "Short", 1.5, -110, -110),
            (T1, "batter_total_bases", "Short", 1.5, -130, 110),
        )
        out = biggest_movers(h, "evt-move", min_points=0.0)
        assert out.iloc[0]["player"] == "Short"

    def test_widening_the_margin_is_not_an_opinion_changing(self):
        """
        A book that widens both sides has not changed its view. De-vigging both
        snapshots cancels the margin; reading either side alone would not.
        """
        h = history(
            (T0, "batter_total_bases", "Even", 1.5, -105, -105),
            (T1, "batter_total_bases", "Even", 1.5, -130, -130),
        )
        out = biggest_movers(h, "evt-move", min_points=0.0)
        assert out.empty or abs(out.iloc[0]["points"]) == pytest.approx(0.0, abs=0.01)

    def test_direction_is_signed_toward_the_over(self):
        h = history(
            (T0, "pitcher_strikeouts", "P", 5.5, -125, 105),
            (T1, "pitcher_strikeouts", "P", 5.5, -115, -105),
        )
        out = biggest_movers(h, "evt-move", min_points=0.0)
        assert out.iloc[0]["points"] < 0        # over got cheaper: away from the over


class TestLineMovesAreNotPriceMoves:
    def test_a_line_move_sorts_above_a_bigger_price_move(self):
        h = history(
            (T0, "pitcher_strikeouts", "LineMover", 5.5, -110, -110),
            (T1, "pitcher_strikeouts", "LineMover", 6.5, -110, -110),
            (T0, "batter_total_bases", "PriceMover", 1.5, -110, -110),
            (T1, "batter_total_bases", "PriceMover", 1.5, -200, 170),
        )
        out = biggest_movers(h, "evt-move", min_points=0.0)
        assert out.iloc[0]["player"] == "LineMover"
        assert bool(out.iloc[0]["line_moved"]) is True

    def test_a_line_move_is_reported_even_at_an_unchanged_price(self):
        """The churn floor must not swallow a change of bet."""
        h = history(
            (T0, "pitcher_strikeouts", "P", 5.5, -110, -110),
            (T1, "pitcher_strikeouts", "P", 6.5, -110, -110),
        )
        out = biggest_movers(h, "evt-move", min_points=5.0)
        assert len(out) == 1
        assert out.iloc[0]["open_line"] == 5.5
        assert out.iloc[0]["current_line"] == 6.5


class TestNoiseAndEmptiness:
    def test_churn_below_the_floor_is_dropped(self):
        h = history(
            (T0, "batter_total_bases", "Quiet", 1.5, -110, -110),
            (T1, "batter_total_bases", "Quiet", 1.5, -111, -109),
        )
        assert biggest_movers(h, "evt-move", min_points=0.8).empty

    def test_a_single_snapshot_yields_nothing(self):
        h = history((T0, "batter_total_bases", "Only", 1.5, -110, -110))
        assert biggest_movers(h, "evt-move").empty

    def test_other_events_are_not_mixed_in(self):
        h = history(
            (T0, "batter_total_bases", "Ours", 1.5, -110, -110),
            (T1, "batter_total_bases", "Ours", 1.5, -200, 170),
        )
        assert biggest_movers(h, "some-other-event").empty

    def test_empty_history_is_survivable(self):
        empty = pd.DataFrame(columns=odds_history.COLUMNS)
        assert biggest_movers(empty, "evt-move").empty
        assert biggest_movers(None, "evt-move").empty

    def test_respects_top_n(self):
        snaps = []
        for i, price in enumerate([-200, -180, -160, -140, -120, 100, 120]):
            snaps.append((T0, "batter_total_bases", f"P{i}", 1.5, -110, -110))
            snaps.append((T1, "batter_total_bases", f"P{i}", 1.5, price, 110))
        out = biggest_movers(history(*snaps), "evt-move", top_n=3, min_points=0.0)
        assert len(out) == 3

    def test_a_missing_side_is_skipped_not_guessed(self):
        h = history(
            (T0, "batter_total_bases", "Half", 1.5, -110, None),
            (T1, "batter_total_bases", "Half", 1.5, -200, None),
        )
        assert biggest_movers(h, "evt-move", min_points=0.0).empty


class TestAgainstTonightsRealHistory:
    """A shape check against the file the page actually reads."""

    def test_returns_expected_columns(self):
        h = odds_history.load_history()
        out = biggest_movers(h, "ee5f7b3a90890ec4fbb3146543125fe7", top_n=5)
        expected = {"market", "player", "opened_at", "current_at", "open_line",
                    "current_line", "open_price", "current_price", "points",
                    "line_moved"}
        assert expected.issubset(set(out.columns))
        assert len(out) <= 5
        if not out.empty:
            # Ranked by magnitude within the line-moved grouping.
            price_moves = out[~out["line_moved"]]["points"].abs().tolist()
            assert price_moves == sorted(price_moves, reverse=True)
