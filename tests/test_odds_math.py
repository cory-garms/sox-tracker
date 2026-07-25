"""Odds conversion and expected-value math."""

from __future__ import annotations

import pytest

from client.odds_math import (
    american_to_decimal,
    american_to_implied_prob,
    calculate_ev,
    no_vig_probability,
)


class TestAmericanToImpliedProb:
    @pytest.mark.parametrize("odds,expected", [
        (-100, 0.5),
        (100, 0.5),
        (-200, 2 / 3),
        (200, 1 / 3),
        (-110, 110 / 210),
        (150, 0.4),
    ])
    def test_known_conversions(self, odds, expected):
        assert american_to_implied_prob(odds) == pytest.approx(expected)

    def test_favourite_is_more_likely_than_underdog(self):
        assert american_to_implied_prob(-250) > american_to_implied_prob(250)

    @pytest.mark.parametrize("bad", [None, "", "abc", float("nan")])
    def test_unparseable_input_falls_back_to_even(self, bad):
        result = american_to_implied_prob(bad)
        assert 0.0 <= result <= 1.0

    def test_zero_does_not_divide_by_zero(self):
        assert american_to_implied_prob(0) == 0.5


class TestAmericanToDecimal:
    @pytest.mark.parametrize("odds,expected", [
        (100, 2.0),
        (-100, 2.0),
        (200, 3.0),
        (-200, 1.5),
        (-110, pytest.approx(1.9090909)),
    ])
    def test_known_conversions(self, odds, expected):
        assert american_to_decimal(odds) == expected

    def test_decimal_odds_always_exceed_one(self):
        for odds in (-10000, -110, 100, 5000):
            assert american_to_decimal(odds) > 1.0


class TestNoVigProbability:
    def test_probabilities_sum_to_one(self):
        over, under = no_vig_probability(-115, -105)

        assert over + under == pytest.approx(1.0)

    def test_strips_the_margin_from_both_sides(self):
        """
        A -110/-110 market implies 52.4% each — 104.8% total. De-vigged it must
        be an even 50/50.
        """
        over, under = no_vig_probability(-110, -110)

        assert over == pytest.approx(0.5)
        assert under == pytest.approx(0.5)

    def test_favoured_side_keeps_the_higher_probability(self):
        over, under = no_vig_probability(-200, 170)

        assert over > under

    def test_devigged_probability_is_below_the_vigged_one(self):
        """This is the whole point: the raw implied number overstates the edge."""
        vigged = american_to_implied_prob(-110)
        devigged, _ = no_vig_probability(-110, -110)

        assert devigged < vigged

    def test_degenerate_input_returns_even_split(self):
        assert no_vig_probability(0, 0) == (0.5, 0.5)


class TestCalculateEV:
    def test_fair_bet_has_zero_ev(self):
        assert calculate_ev(0.5, 100) == pytest.approx(0.0)

    def test_edge_produces_positive_ev(self):
        assert calculate_ev(0.60, 100) > 0

    def test_no_edge_produces_negative_ev(self):
        assert calculate_ev(0.40, 100) < 0

    def test_vig_makes_a_coin_flip_negative(self):
        """Betting a true 50/50 at -110 loses money — the sanity check."""
        assert calculate_ev(0.5, -110) < 0

    def test_returned_as_a_percentage(self):
        # 60% at +100 pays 2.0 → EV = 0.2 → +20%
        assert calculate_ev(0.60, 100) == pytest.approx(20.0)
