"""
The win-probability baseline.

Built before it was measured is how the prop models happened, and the track
record says how that went. This one is the other way round: the moneyline is
already captured across nine books on every build and analysis.clv can score a
projection against the price it was quoted at, so the scoreboard existed first.

It is deliberately the *null* model — team run-scoring and run-prevention, log5,
home field, and nothing about who is pitching. These tests pin the arithmetic
and the refusals, not the accuracy; accuracy is what the backtest is for.
"""

from __future__ import annotations

import pytest

from analysis.win_probability import (
    HOME_FIELD_WIN_PCT,
    apply_home_field,
    implied_edge,
    log5,
    pythagenpat_exponent,
    pythagorean,
    win_probability,
)


class TestPythagorean:
    def test_equal_runs_is_a_500_team(self):
        assert pythagorean(600, 600, 130) == pytest.approx(0.5)

    def test_outscoring_the_opposition_beats_500(self):
        assert pythagorean(700, 600, 130) > 0.5

    def test_it_tracks_the_real_thing(self):
        """
        Tampa Bay through 131 games in 2026: 591 scored, 544 allowed, .595
        actual. Pythagorean should land near the record without matching it —
        the gap is the luck in one-run games, which is the reason for using
        this rather than W-L in the first place.
        """
        p = pythagorean(591, 544, 131)
        assert 0.50 < p < 0.60

    def test_no_games_played_is_none_not_500(self):
        """"No information" and "evenly matched" are different claims."""
        assert pythagorean(0, 0, 0) is None

    def test_the_exponent_responds_to_the_run_environment(self):
        """Pythagenpat's whole point: 1.83 is only right in an average league."""
        low = pythagenpat_exponent(400, 400, 162)
        high = pythagenpat_exponent(900, 900, 162)
        assert low < high

    def test_a_scoreless_team_does_not_divide_by_zero(self):
        assert pythagenpat_exponent(0, 0, 10) > 0


class TestLog5:
    def test_two_equal_teams_make_a_coin_flip(self):
        assert log5(0.600, 0.600) == pytest.approx(0.5)

    def test_the_opponents_weakness_compounds(self):
        """
        .600 against .400 is not .600. It is .692, because the favourite's
        strength and the opponent's weakness both apply.
        """
        assert log5(0.600, 0.400) == pytest.approx(0.6923, abs=0.001)

    def test_it_is_antisymmetric(self):
        assert log5(0.7, 0.3) == pytest.approx(1 - log5(0.3, 0.7))

    def test_a_missing_side_is_none(self):
        assert log5(None, 0.5) is None
        assert log5(0.5, None) is None

    def test_two_perfect_teams_do_not_divide_by_zero(self):
        assert log5(1.0, 1.0) == 0.5
        assert log5(0.0, 0.0) == 0.5


class TestHomeField:
    def test_home_helps_and_away_hurts(self):
        assert apply_home_field(0.5, True) > 0.5
        assert apply_home_field(0.5, False) < 0.5

    def test_the_two_sides_are_mirror_images(self):
        assert apply_home_field(0.5, True) == pytest.approx(1 - apply_home_field(0.5, False))

    def test_an_even_matchup_gets_the_league_home_rate(self):
        assert apply_home_field(0.5, True) == pytest.approx(HOME_FIELD_WIN_PCT, abs=0.001)

    def test_it_cannot_push_a_favourite_past_certainty(self):
        """
        The reason this goes through log5 rather than adding a flat few points:
        a .95 favourite has no room for three more, and addition would happily
        take it over 1.0.
        """
        assert apply_home_field(0.95, True) < 1.0
        assert apply_home_field(0.99, True) < 1.0

    def test_the_advantage_shrinks_as_the_game_gets_lopsided(self):
        even = apply_home_field(0.50, True) - 0.50
        lopsided = apply_home_field(0.90, True) - 0.90
        assert lopsided < even


class TestWinProbability:
    BOS = dict(team_runs_scored=700, team_runs_allowed=600, team_games=131)
    WEAK = dict(opp_runs_scored=550, opp_runs_allowed=680, opp_games=131)

    def test_the_better_team_at_home_is_favoured(self):
        p = win_probability(**self.BOS, **self.WEAK, is_home=True)
        assert p > 0.5

    def test_the_same_matchup_on_the_road_is_worth_less(self):
        home = win_probability(**self.BOS, **self.WEAK, is_home=True)
        away = win_probability(**self.BOS, **self.WEAK, is_home=False)
        assert home > away

    def test_identical_teams_on_the_road_sit_below_even(self):
        p = win_probability(600, 600, 131, 600, 600, 131, is_home=False)
        assert p == pytest.approx(1 - HOME_FIELD_WIN_PCT, abs=0.001)

    def test_an_unevaluable_opponent_yields_none(self):
        """
        Half a model priced against a real moneyline is worse than no number,
        which is what the board's NO LINE state exists to say.
        """
        assert win_probability(**self.BOS, opp_runs_scored=0, opp_runs_allowed=0,
                               opp_games=0, is_home=True) is None

    def test_probabilities_stay_in_range(self):
        for rs, ra in ((900, 400), (400, 900), (1, 1), (700, 600)):
            for home in (True, False):
                p = win_probability(rs, ra, 131, 600, 600, 131, is_home=home)
                assert 0.0 < p < 1.0


class TestEdge:
    def test_the_edge_is_in_probability_points(self):
        assert implied_edge(0.58, 0.55) == pytest.approx(3.0)

    def test_it_is_signed(self):
        assert implied_edge(0.52, 0.55) < 0

    def test_a_missing_side_is_none_rather_than_zero(self):
        """Zero edge and no opinion are different, and only one is a finding."""
        assert implied_edge(None, 0.55) is None
        assert implied_edge(0.55, None) is None
