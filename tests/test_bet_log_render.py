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


class TestProvisionalLabelling:
    """
    A snapshot 34 minutes before first pitch is not a close, and CLV computed
    from one must not be presented as final.
    """

    def test_says_provisional_before_first_pitch(self):
        html = _position_html(
            bets(("A", 1.0, -110, -110)), EID, {"n": 0},
            reference={"at": "01:28 UTC", "mins_before": 12.0, "started": False},
        )
        assert "Provisional" in html
        assert "12 minutes before first pitch" in html

    def test_says_final_once_the_game_has_started(self):
        html = _position_html(
            bets(("A", 1.0, -110, -110)), EID, {"n": 0},
            reference={"at": "01:38 UTC", "mins_before": 2.0, "started": True},
        )
        assert "these are final" in html
        assert "Provisional" not in html

    def test_no_reference_means_no_claim_either_way(self):
        html = _position_html(bets(("A", 1.0, -110, -110)), EID, {"n": 0})
        assert "Provisional" not in html
        assert "these are final" not in html


class TestGradingConverges:
    """
    grade_from_history used to skip rows that already had a closing price, which
    froze whichever early snapshot landed first. The last pre-game snapshot keeps
    improving until first pitch, so grading must keep following it.
    """

    def test_a_later_pre_game_snapshot_supersedes_an_earlier_one(self, tmp_path):
        import pandas as pd
        from data import bet_log, odds_history

        ev = {"id": "e1", "commence_time": "2026-07-28T01:40:00Z",
              "home_team": "A", "away_team": "B"}
        rows = []
        for stamp, price in (("2026-07-28T01:06:00+00:00", 158),
                             ("2026-07-28T01:27:00+00:00", 171)):
            rows += odds_history.snapshot_rows(
                ev, "h2h", {"Athletics": {"line": None, "over_odds": price,
                                          "under_odds": -190}}, captured_at=stamp)
        history = pd.DataFrame(rows).reindex(columns=odds_history.COLUMNS)

        path = tmp_path / "b.parquet"
        bet_log.record_bet("Athletics", "h2h", "Moneyline", 158,
                           event_id="e1", stake=1.0, path=path)
        first = bet_log.grade_from_history(history, path=path)
        assert first.iloc[0]["closing_price"] == 171

        # a still-later pre-game read must win again
        rows += odds_history.snapshot_rows(
            ev, "h2h", {"Athletics": {"line": None, "over_odds": 180,
                                      "under_odds": -200}},
            captured_at="2026-07-28T01:38:00+00:00")
        later = bet_log.grade_from_history(
            pd.DataFrame(rows).reindex(columns=odds_history.COLUMNS), path=path)
        assert later.iloc[0]["closing_price"] == 180
