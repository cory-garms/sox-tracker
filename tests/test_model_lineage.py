"""
analysis/model_lineage.py — has the model actually improved?

The question this answers could not be asked of the prediction log: its replayed
rows end 2026-08-23 and its live rows begin 2026-08-24, so any early-versus-late
split of it is exactly replay-versus-live. The lineage sidesteps that by running
every projection the repo has ever shipped over the same held-out starts.

Two bugs were found building it, both from the same cause -- one measurement
implemented more than once:

  * scripts/backtest_pitcher_k.decompose did not return `mse`, so an error bar
    computed from it read exactly zero;
  * analysis.scoring.se_of_model_error divided by sqrt(2n) where the derivation
    calls for multiplying by sqrt(2/n), making every bar half its true width.

Both are pinned below.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd
import pytest

from analysis import model_lineage as ml
from analysis import scoring


class TestPairedGap:
    def _y(self, n=400, seed=1):
        rng = np.random.default_rng(seed)
        return rng.poisson(5.0, n).astype(float)

    def test_a_model_compared_with_itself_has_no_gap(self):
        y = self._y()
        p = y + 0.5
        gap, lo, hi = ml._paired_mse_gap(p, p, y)
        assert gap == pytest.approx(0.0)
        assert lo == pytest.approx(0.0) and hi == pytest.approx(0.0)

    def test_a_clearly_better_model_wins_with_an_interval_off_zero(self):
        y = self._y()
        rng = np.random.default_rng(2)
        good = y + rng.normal(0, 0.3, len(y))
        bad = y + rng.normal(0, 2.0, len(y))
        gap, lo, hi = ml._paired_mse_gap(bad, good, y)
        assert gap > 0 and lo > 0, "the better model should win outright"

    def test_the_sign_says_which_model_is_better(self):
        y = self._y()
        rng = np.random.default_rng(3)
        good = y + rng.normal(0, 0.3, len(y))
        bad = y + rng.normal(0, 2.0, len(y))
        assert ml._paired_mse_gap(good, bad, y)[0] < 0

    def test_pairing_beats_treating_the_samples_as_independent(self):
        """
        Why it is paired. Both models predict the same starts, so most of the
        variance is the starts and cancels; resampling independently would
        drown a real difference in noise that pairing removes.
        """
        y = self._y(n=300)
        rng = np.random.default_rng(4)
        shared = rng.normal(0, 3.0, len(y))          # big common component
        a = y + shared + rng.normal(0, 0.2, len(y))
        b = y + shared + rng.normal(0, 0.6, len(y))
        gap, lo, hi = ml._paired_mse_gap(a, b, y)
        assert lo < 0 < hi or gap < 0, "a is the better model here"
        gap2, lo2, hi2 = ml._paired_mse_gap(b, a, y)
        assert lo2 > 0, "pairing should resolve b as worse despite shared noise"

    def test_too_few_points_is_refused(self):
        assert math.isnan(ml._paired_mse_gap(np.arange(3.0), np.arange(3.0),
                                             np.arange(3.0))[0])

    def test_nan_predictions_are_dropped_not_propagated(self):
        y = self._y(n=50)
        a = y.copy(); a[0] = np.nan
        b = y + 1.0
        assert np.isfinite(ml._paired_mse_gap(a, b, y)[0])


class TestLoad:
    def test_a_fresh_cache_is_served_without_remeasuring(self, tmp_path, monkeypatch):
        path = tmp_path / "lin.json"
        path.write_text(json.dumps({"n": 7, "models": [], "comparisons": []}))
        monkeypatch.setattr(ml, "cache_path", lambda season: path)
        monkeypatch.setattr(ml, "measure", lambda *a, **k: pytest.fail("remeasured"))
        assert ml.load(2026)["n"] == 7

    def test_a_stale_cache_is_remeasured(self, tmp_path, monkeypatch):
        path = tmp_path / "lin.json"
        path.write_text(json.dumps({"n": 1, "models": [], "comparisons": []}))
        monkeypatch.setattr(ml, "cache_path", lambda season: path)
        monkeypatch.setattr(ml, "measure",
                            lambda *a, **k: {"n": 2, "models": [{}], "comparisons": []})
        assert ml.load(2026, max_age_hours=0.0000001)["n"] == 2

    def test_a_failed_remeasurement_serves_the_stored_copy(self, tmp_path, monkeypatch):
        """Loudly degraded, never fatal: the section must not empty on an error."""
        path = tmp_path / "lin.json"
        path.write_text(json.dumps({"n": 9, "models": [{}], "comparisons": []}))
        monkeypatch.setattr(ml, "cache_path", lambda season: path)

        def boom(*a, **k):
            raise RuntimeError("logs moved")

        monkeypatch.setattr(ml, "measure", boom)
        assert ml.load(2026, max_age_hours=0.0000001)["n"] == 9

    def test_no_cache_and_no_measurement_is_empty_rather_than_an_exception(
            self, tmp_path, monkeypatch):
        monkeypatch.setattr(ml, "cache_path", lambda season: tmp_path / "none.json")
        monkeypatch.setattr(ml, "measure", lambda *a, **k: {})
        assert ml.load(2026) == {}


class TestTheErrorBarIsTheRightWidth:
    """
    se_of_model_error divided by sqrt(2n) where the derivation calls for
    multiplying by sqrt(2/n) -- smaller by exactly a factor of two. Nothing
    caught it because the only assertions on it were that a small sample gives a
    wider bar than a large one, which is true of both forms.
    """

    def _d(self, n=3165, rmse=2.263, model_err=0.413):
        return {"n": n, "rmse": rmse, "mse": rmse ** 2, "model_err": model_err}

    def test_it_matches_the_stated_derivation(self):
        d = self._d()
        expected = (d["mse"] * math.sqrt(2.0 / d["n"])) / (2.0 * d["model_err"])
        assert scoring.se_of_model_error(d) == pytest.approx(expected)

    def test_it_is_not_the_old_half_width_form(self):
        d = self._d()
        half = d["mse"] / (math.sqrt(2 * d["n"]) * 2 * d["model_err"])
        assert scoring.se_of_model_error(d) == pytest.approx(2 * half)

    def test_it_lands_near_the_simulated_spread(self):
        """
        Anchored to simulation rather than to itself: at n=3,165 the empirical
        spread of the estimate is about 0.185 and this returns about 0.16. The
        normal approximation understates a little, which is the honest direction.
        """
        se = scoring.se_of_model_error(self._d())
        assert 0.12 < se < 0.20

    def test_a_wider_sample_still_gives_a_tighter_bar(self):
        assert scoring.se_of_model_error(self._d(n=200)) > \
               scoring.se_of_model_error(self._d(n=5000))


class TestDecomposeCarriesEverythingItsCallersNeed:
    def test_it_returns_mse(self):
        """
        The script's own copy did not, so an error bar computed from it read
        exactly zero and printed as 0.000 for every model.
        """
        d = scoring.decompose([5.0, 5.0, 5.0], [4.0, 6.0, 5.0])
        assert "mse" in d and d["mse"] > 0
        assert scoring.se_of_model_error(d) >= 0 or math.isnan(
            scoring.se_of_model_error(d))

    def test_an_empty_input_is_not_an_exception(self):
        assert scoring.decompose([], []) == {"n": 0}
