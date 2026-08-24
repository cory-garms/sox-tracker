"""
A side is only named when the price pays for it.

Ranger Suarez projected 4.99 K against a 4.5 line on 2026-08-24. That cleared
MIN_EDGE_K, so the board printed "OVER (-5.9% EV) 🔥" -- a flame on a bet the
same line of code had just computed to lose 5.9 cents on the dollar. The
model's own over-probability was 55.71% against the book's de-vigged 55.88%,
so there was no edge to have: the K-unit gate never looked at the price.

Clearing the model's error bar means it has an opinion. It does not mean the
opinion is worth money at the number quoted, and a page that says OVER while
showing negative EV is claiming something it has already disproved.
"""

from __future__ import annotations

import pytest

from analysis.betting import _prop_ev, _side_call


class TestNegativeEvIsNeverASide:
    def test_the_suarez_case(self):
        """The exact numbers that shipped: 55.71% over 4.5 K at -145."""
        rec, ev = _side_call("OVER", 0.5571, 0.0, -145)
        assert ev < 0
        assert not rec.startswith("OVER")
        assert "PRICED OUT" in rec
        assert "🔥" not in rec

    @pytest.mark.parametrize("direction,p_win,odds", [
        ("OVER", 0.50, -145),
        ("OVER", 0.5571, -145),
        ("UNDER", 0.40, -120),
        ("UNDER", 0.52, -180),
    ])
    def test_no_direction_word_survives_negative_ev(self, direction, p_win, odds):
        rec, ev = _side_call(direction, p_win, 0.0, odds)
        assert ev <= 0
        # The badge class and the "called props" count both key off these.
        assert not rec.startswith(("OVER", "UNDER"))

    def test_exactly_zero_ev_is_not_a_bet_either(self):
        """A coin flip priced fairly is not an edge; it is a fee waiting."""
        p = 0.5
        rec, ev = _side_call("OVER", p, 0.0, 100)   # +100 -> break-even at 50%
        assert ev == pytest.approx(0.0)
        assert "PRICED OUT" in rec


class TestPositiveEvStillCallsTheSide:
    def test_a_real_over_is_still_an_over(self):
        rec, ev = _side_call("OVER", 0.62, 0.0, -145)
        assert ev > 0
        assert rec.startswith("OVER")
        assert "🔥" in rec

    def test_a_real_under_is_still_an_under(self):
        rec, ev = _side_call("UNDER", 0.55, 0.0, 114)
        assert ev > 0
        assert rec.startswith("UNDER")
        assert "🧊" in rec

    def test_the_reported_ev_is_the_computed_ev(self):
        """The number on the badge must be the one the model actually derived."""
        for p, odds in ((0.62, -145), (0.55, 114), (0.5571, -145)):
            rec, ev = _side_call("OVER", p, 0.0, odds)
            assert ev == _prop_ev(p, 0.0, odds)
            assert f"{ev:+.1f}%" in rec


class TestTheLabelFitsWhereItIsStored:
    def test_worst_case_length_fits_the_database_column(self):
        """
        ModelPrediction.recommendation is String(32). A label that overflows
        fails only on Postgres, which is how a day of deploys was lost once
        already.
        """
        worst, _ = _side_call("OVER", 0.0, 0.0, -100000)   # EV floor, -100.0%
        assert len(worst) <= 32, worst
