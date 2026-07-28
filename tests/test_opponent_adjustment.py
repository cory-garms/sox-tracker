"""
The opponent adjustment, and the leakage it must not commit.

The adjustment itself is minor. The thing worth guarding is that the opponent's
strikeout rate is bounded to games *before* the one being projected: a rate that
includes tonight would let the model see its own future, and would make the
backtested error bar optimistic. Since that error bar is the only thing standing
between this page and recommendations it cannot support, leakage here is the
expensive kind of bug.
"""

from __future__ import annotations

import pandas as pd
import pytest

from data.opponent import (
    REGRESSION_PA,
    league_k_rate,
    opponent_k_factor,
    opponent_k_rate,
)


def logs(*rows) -> pd.DataFrame:
    """rows: (team_id, date, pa, so)"""
    return pd.DataFrame(
        [{"team_id": t, "team_name": f"T{t}", "game_date": d, "pa": pa, "so": so}
         for t, d, pa, so in rows]
    )


LEAGUE = logs(
    (1, "2026-04-01", 1000, 300),   # team 1 strikes out a lot: 30%
    (2, "2026-04-01", 1000, 100),   # team 2 barely at all: 10%
    (3, "2026-04-01", 1000, 200),
)


class TestNoLeakage:
    def test_a_game_on_the_date_itself_is_excluded(self):
        """Strictly before, because tonight's Ks are what we are projecting."""
        frame = logs((1, "2026-04-01", 100, 40), (1, "2026-04-02", 100, 10))
        rate, pa = opponent_k_rate(frame, 1, before="2026-04-02")
        assert pa == 100
        assert rate == pytest.approx(0.40)

    def test_later_games_are_invisible(self):
        frame = logs((1, "2026-04-01", 100, 20), (1, "2026-09-01", 100, 60))
        rate, _ = opponent_k_rate(frame, 1, before="2026-05-01")
        assert rate == pytest.approx(0.20)

    def test_league_rate_is_bounded_the_same_way(self):
        frame = logs((1, "2026-04-01", 100, 20), (2, "2026-09-01", 100, 60))
        assert league_k_rate(frame, before="2026-05-01") == pytest.approx(0.20)

    def test_no_prior_games_yields_a_neutral_factor(self):
        """Opening day has nothing behind it and must not invent a number."""
        frame = logs((1, "2026-04-01", 100, 40))
        assert opponent_k_factor(frame, 1, before="2026-04-01") == 1.0


class TestRegression:
    def test_small_samples_are_pulled_toward_league_average(self):
        tiny = logs((1, "2026-04-01", 20, 20), (2, "2026-04-01", 2000, 400))
        # team 1 struck out in 100% of 20 PA - absurd, and must barely move.
        factor = opponent_k_factor(tiny, 1, before="2026-05-01")
        assert 1.0 < factor < 1.5, factor

    def test_large_samples_approach_the_raw_ratio(self):
        big = logs((1, "2026-04-01", 100_000, 30_000),
                   (2, "2026-04-01", 100_000, 10_000))
        # league is 20%, team 1 is 30% -> factor approaches 1.5
        factor = opponent_k_factor(big, 1, before="2026-05-01")
        assert factor == pytest.approx(1.5, abs=0.02)

    def test_regression_constant_is_the_halfway_point(self):
        frame = logs((1, "2026-04-01", int(REGRESSION_PA), int(REGRESSION_PA * 0.4)),
                     (2, "2026-04-01", 100_000, 20_000))
        # team at 40%, league ~20%, with exactly REGRESSION_PA behind it:
        # weight 0.5, so the regressed rate is halfway -> ~30% -> factor ~1.5
        assert opponent_k_factor(frame, 1, before="2026-05-01") == pytest.approx(
            1.5, abs=0.05
        )


class TestDegradesToNeutral:
    @pytest.mark.parametrize("frame", [
        None,
        pd.DataFrame(columns=["team_id", "team_name", "game_date", "pa", "so"]),
    ])
    def test_missing_data_changes_nothing(self, frame):
        assert opponent_k_factor(frame, 1) == 1.0

    def test_an_unknown_team_changes_nothing(self):
        assert opponent_k_factor(LEAGUE, 999) == 1.0

    def test_a_neutral_lineup_leaves_the_projection_alone(self):
        """Team 3 is exactly league average; its factor must be 1.0."""
        assert opponent_k_factor(LEAGUE, 3, regression_pa=0.0) == pytest.approx(1.0)


class TestDirection:
    def test_a_high_strikeout_lineup_raises_the_projection(self):
        assert opponent_k_factor(LEAGUE, 1, regression_pa=0.0) > 1.0

    def test_a_contact_lineup_lowers_it(self):
        assert opponent_k_factor(LEAGUE, 2, regression_pa=0.0) < 1.0


class TestModelIntegration:
    def test_the_factor_multiplies_the_blended_rate(self):
        from analysis.betting import pitcher_strikeout_model
        from conftest import games_df
        import tests.test_betting_models as tb

        base = pitcher_strikeout_model(tb.five_starts(), pd.DataFrame(), games_df([]))
        adj = pitcher_strikeout_model(
            tb.five_starts(), pd.DataFrame(), games_df([]),
            opponent_logs=LEAGUE, opponent_team_id=1, as_of_date="2026-05-01",
        )
        assert adj.iloc[0]["opp_k_factor"] > 1.0
        assert adj.iloc[0]["proj_k"] > base.iloc[0]["proj_k"]
        # the unadjusted rate is still reported, so the adjustment is auditable
        assert adj.iloc[0]["blended_k9_own"] == pytest.approx(
            base.iloc[0]["blended_k9"]
        )
