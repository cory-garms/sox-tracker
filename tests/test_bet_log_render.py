"""
The My Position card.

The number that must not drift is the stake. Paper rows and real positions both
live in the log and both grade, but counting a stake-0 measurement row as a bet
would overstate what is actually at risk - which is the one figure on this page
the reader might act on.
"""

from __future__ import annotations

import pandas as pd
import pytest

from betting_report import _position_html

EID = "evt-1"


def bets(*rows) -> pd.DataFrame:
    """rows: (selection, stake, price, closing_price)"""
    return pd.DataFrame([
        {"event_id": EID, "selection": s, "side": "Under", "line": 1.5,
         "price": p, "closing_price": c, "stake": st, "promo": "", "market": "x"}
        for s, st, p, c in rows
    ])


class TestStakeAccounting:
    def test_paper_rows_are_not_counted_as_bets(self):
        html = _position_html(
            bets(("Real", 1.0, -110, -110), ("Paper", 0.0, -110, -110)),
            EID, {"n": 0},
        )
        assert "<strong>1 bets</strong>" in html
        assert "<strong>1U</strong> staked" in html
        assert "1</strong> paper row" in html

    def test_staked_total_excludes_paper(self):
        html = _position_html(
            bets(("A", 0.5, -110, -110), ("B", 0.25, -110, -110),
                 ("P", 0.0, -110, -110)),
            EID, {"n": 0},
        )
        assert "<strong>0.75U</strong> staked" in html

    def test_no_paper_sentence_when_there_are_none(self):
        html = _position_html(bets(("A", 1.0, -110, -110)), EID, {"n": 0})
        assert "paper" not in html.lower()


class TestClv:
    def test_beating_the_close_reads_positive(self):
        """Took +298, closed +260: the market moved toward the bet."""
        html = _position_html(bets(("C", 0.5, 298, 260)), EID, {"n": 0})
        assert "delta-pos" in html

    def test_drifting_out_reads_negative(self):
        html = _position_html(bets(("C", 1.0, 158, 163)), EID, {"n": 0})
        assert "delta-neg" in html

    def test_an_ungraded_bet_says_so_rather_than_guessing(self):
        html = _position_html(bets(("C", 1.0, 158, float("nan"))), EID, {"n": 0})
        assert "not yet" in html


class TestSampleSizeHonesty:
    def test_a_small_sample_is_labelled_an_anecdote(self):
        html = _position_html(
            bets(("A", 1.0, -110, -110)), EID,
            {"n": 10, "beat_close_pct": 20.0, "mean_clv_points": -0.38},
        )
        assert "anecdote, not a record" in html

    def test_a_larger_sample_drops_the_caveat(self):
        html = _position_html(
            bets(("A", 1.0, -110, -110)), EID,
            {"n": 40, "beat_close_pct": 55.0, "mean_clv_points": 0.9},
        )
        assert "anecdote" not in html

    def test_nothing_graded_says_nothing_graded(self):
        html = _position_html(bets(("A", 1.0, -110, -110)), EID, {"n": 0})
        assert "Nothing graded yet" in html


class TestEmptyStates:
    def test_no_log_at_all(self):
        assert "No bets logged" in _position_html(pd.DataFrame(), EID, {"n": 0})

    def test_bets_exist_but_none_on_this_game(self):
        html = _position_html(bets(("A", 1.0, -110, -110)), "other-event", {"n": 0})
        assert "No bets logged on tonight's game" in html
