"""
Forecast scoring.

These pin the properties that make the track record page honest rather than
flattering. The recurring failure mode they guard against is a small sample
read as if it were evidence: a calibration gap smaller than its own noise
floor, a Brier "win" over the market that is really a tie, or an error bar
quoted without the uncertainty on the error bar.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from analysis.scoring import (
    brier,
    calibration,
    decompose,
    discrimination,
    sample_verdict,
    se_of_model_error,
    versus_market,
)


class TestDecompose:
    def test_a_perfect_projection_still_has_poisson_scatter(self):
        """
        The point of the decomposition: a true mean of 5 produces 3s and 8s, so
        a flawless model is not a zero-error model.
        """
        rng = np.random.default_rng(7)
        actual = rng.poisson(5.0, 4000)
        d = decompose([5.0] * len(actual), actual)
        assert d["rmse"] > 2.0                    # raw error is large
        assert d["model_err"] < 0.35              # but almost none of it is the model

    def test_a_biased_projection_shows_model_error(self):
        rng = np.random.default_rng(7)
        actual = rng.poisson(5.0, 4000)
        d = decompose([7.0] * len(actual), actual)
        # MSE = bias^2 + var = 4 + 5 = 9; the Poisson allowance is the mean
        # projection, 7. sqrt(9 - 7) ~= 1.41 is the part left for the model.
        assert d["model_err"] == pytest.approx(math.sqrt(2.0), abs=0.15)
        assert d["bias"] == pytest.approx(2.0, abs=0.15)

    def test_bias_sign_says_which_way_it_is_wrong(self):
        assert decompose([6, 6], [4, 4])["bias"] > 0     # over-projecting
        assert decompose([2, 2], [4, 4])["bias"] < 0     # under-projecting

    def test_model_error_never_goes_imaginary(self):
        """Observed scatter below Poisson noise means no demonstrable model error."""
        assert decompose([5.0, 5.0, 5.0], [5, 5, 5])["model_err"] == 0.0

    def test_an_empty_sample_reports_nothing_rather_than_zero(self):
        assert decompose([], []) == {"n": 0}

    def test_pairs_with_missing_values_are_dropped(self):
        assert decompose([1.0, float("nan"), 3.0], [1, 2, 3])["n"] == 2

    def test_a_small_sample_can_fail_to_demonstrate_any_model_error(self):
        """
        Projecting 6.0 against a Poisson(5) truth, 50 observations can scatter
        *below* the Poisson floor. The honest answer is then "no demonstrable
        model error", not a small positive number.
        """
        rng = np.random.default_rng(3)
        small = decompose([6.0] * 50, rng.poisson(5.0, 50))
        assert small["model_err"] == 0.0
        assert math.isnan(se_of_model_error(small))

    def test_standard_error_shrinks_with_sample_size(self):
        rng = np.random.default_rng(3)
        # A bias large enough that model error is clearly positive at both sizes.
        small = decompose([9.0] * 200, rng.poisson(5.0, 200))
        large = decompose([9.0] * 8000, rng.poisson(5.0, 8000))
        assert small["model_err"] > 0 and large["model_err"] > 0
        assert se_of_model_error(small) > se_of_model_error(large)

    def test_standard_error_of_a_zero_error_model_is_undefined(self):
        assert math.isnan(se_of_model_error({"n": 10, "model_err": 0.0, "mse": 1.0}))


class TestBrier:
    def test_a_confident_correct_forecast_scores_zero(self):
        assert brier([1.0, 0.0], [1, 0]) == 0.0

    def test_a_confident_wrong_forecast_scores_one(self):
        assert brier([0.0, 1.0], [1, 0]) == 1.0

    def test_a_coin_flip_scores_a_quarter(self):
        assert brier([0.5, 0.5], [1, 0]) == 0.25


class TestCalibration:
    def test_a_well_calibrated_forecast_has_a_small_gap(self):
        rng = np.random.default_rng(11)
        p = rng.uniform(0.2, 0.8, 3000)
        y = (rng.uniform(size=3000) < p).astype(int)
        out = calibration(p, y)
        assert out["rms_gap"] < 0.05

    def test_a_systematically_overconfident_forecast_is_caught(self):
        rng = np.random.default_rng(11)
        true_p = rng.uniform(0.2, 0.8, 3000)
        y = (rng.uniform(size=3000) < true_p).astype(int)
        out = calibration(np.clip(true_p + 0.2, 0, 1), y)
        assert out["rms_gap"] > 0.1
        assert out["resolvable"]

    def test_a_tiny_sample_is_marked_unresolvable(self):
        """
        The honesty guard: with 8 observations the noise floor swamps the gap,
        and the page must not present that as a finding.
        """
        # Well calibrated by construction — half of a 50% forecast came in —
        # so any measured gap is sampling noise.
        out = calibration([0.5] * 8, [1, 0] * 4)
        assert out["noise_floor"] > 0
        assert not out["resolvable"]

    def test_an_empty_sample_is_handled(self):
        assert calibration([], [])["n"] == 0

    def test_bins_collapse_rather_than_crash_on_constant_predictions(self):
        out = calibration([0.5] * 20, [0, 1] * 10)
        assert out["n"] == 20


class TestDiscrimination:
    def test_a_perfect_ranker_scores_auc_one(self):
        assert discrimination([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0])["auc"] == 1.0

    def test_an_inverted_ranker_scores_auc_zero(self):
        assert discrimination([0.1, 0.2, 0.8, 0.9], [1, 1, 0, 0])["auc"] == 0.0

    def test_a_flat_forecast_scores_a_coin_flip_not_better(self):
        """Ties must average, or a constant predictor looks skilful."""
        assert discrimination([0.5] * 8, [1, 0] * 4)["auc"] == 0.5

    def test_skill_is_positive_when_beating_the_base_rate(self):
        out = discrimination([0.9, 0.85, 0.15, 0.1], [1, 1, 0, 0])
        assert out["skill"] > 0

    def test_a_single_class_yields_no_auc_rather_than_a_wrong_one(self):
        assert math.isnan(discrimination([0.6, 0.7], [1, 1])["auc"])

    def test_an_empty_sample_is_handled(self):
        assert discrimination([], [])["n"] == 0


class TestVersusMarket:
    def test_a_better_model_beats_the_market(self):
        out = versus_market([0.9, 0.1], [0.6, 0.4], [1, 0])
        assert out["beats_market"]
        assert out["difference"] > 0

    def test_a_worse_model_does_not(self):
        out = versus_market([0.6, 0.4], [0.9, 0.1], [1, 0])
        assert not out["beats_market"]
        assert out["difference"] < 0

    def test_a_tie_goes_to_the_market(self):
        """The market's forecast is free; matching it is not an edge."""
        out = versus_market([0.7, 0.3], [0.7, 0.3], [1, 0])
        assert out["difference"] == 0
        assert not out["beats_market"]

    def test_only_events_both_forecast_are_compared(self):
        out = versus_market([0.9, 0.8, float("nan")], [0.6, float("nan"), 0.5], [1, 1, 0])
        assert out["n"] == 1

    def test_an_empty_comparison_does_not_claim_a_win(self):
        out = versus_market([], [], [])
        assert out["n"] == 0
        assert not out["beats_market"]

    def test_a_hairline_win_is_not_distinguishable_from_zero(self):
        """
        The real 2026 case: the total-bases model 'beat' the market by 0.0005
        Brier. Any comparison that stops at the sign calls that a win.
        """
        rng = np.random.default_rng(5)
        n = 140
        market = rng.uniform(0.35, 0.65, n)
        y = (rng.uniform(size=n) < market).astype(int)
        model = np.clip(market + rng.normal(0, 0.002, n), 0.01, 0.99)

        out = versus_market(model, market, y)
        assert abs(out["difference"]) < 0.01
        assert not out["distinguishable"]
        assert out["ci_low"] < 0 < out["ci_high"]

    def test_a_real_edge_is_distinguishable(self):
        rng = np.random.default_rng(5)
        n = 800
        true_p = rng.uniform(0.2, 0.8, n)
        y = (rng.uniform(size=n) < true_p).astype(int)
        model = true_p                                   # knows the truth
        market = np.full(n, float(y.mean()))             # quotes the base rate

        out = versus_market(model, market, y)
        assert out["beats_market"]
        assert out["distinguishable"]
        assert out["ci_low"] > 0


class TestSampleVerdict:
    def test_says_so_when_there_is_nothing(self):
        assert "No graded predictions" in sample_verdict(0)

    def test_calls_a_small_sample_an_anecdote(self):
        assert "anecdote" in sample_verdict(12)

    def test_stops_hedging_once_the_sample_supports_it(self):
        assert "anecdote" not in sample_verdict(120)
