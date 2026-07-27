"""
Tests for consensus pricing and promotion valuation.

The promotion maths is the only positive expectation on the page that does not
route through a model, so it is also the only part where an arithmetic slip
would produce a confident wrong answer rather than a visible "no call".
"""

from __future__ import annotations

import pytest

from analysis.betting import consensus_edge_table, promo_comparison
from client.odds_api_client import parse_two_way_by_book, parse_player_lines_by_book
from client.odds_math import (
    american_to_decimal,
    consensus_probability,
    early_win_token_ev,
    no_vig_probability,
    profit_boost_ev,
)


class TestConsensusProbability:
    def test_needs_two_books(self):
        assert consensus_probability([(-110, -110)]) is None
        assert consensus_probability([]) is None

    def test_devigs_each_book_before_combining(self):
        # A fat-margin book and a tight one that hold the same *opinion* (an
        # even market) must not pull the consensus away from 0.50.
        tight = (-105, -105)
        fat = (-130, -130)
        assert consensus_probability([tight, fat]) == pytest.approx(0.50)

    def test_uses_median_not_mean(self):
        # Four books near 0.50 and one wild outlier: the median ignores it.
        quotes = [(-110, -110)] * 4 + [(-1000, +600)]
        assert consensus_probability(quotes) == pytest.approx(0.50, abs=0.01)


class TestProfitBoost:
    @pytest.mark.parametrize("odds", [-200, -110, 100, 148, 400])
    def test_matches_the_closed_form(self, odds):
        """EV_boost = (1+b)*EV_raw + b*(1-p), against the direct computation."""
        p = 1.0 / american_to_decimal(odds)          # exactly fair
        direct = (p * (1 + 1.5 * (american_to_decimal(odds) - 1)) - 1) * 100
        assert profit_boost_ev(p, odds, 50.0) == pytest.approx(direct, abs=0.01)

    def test_fair_bet_returns_half_of_one_minus_p(self):
        """At a fair price a 50% boost is worth exactly 0.5*(1-p)."""
        for odds in (-300, -110, 100, 250, 900):
            p = 1.0 / american_to_decimal(odds)
            assert profit_boost_ev(p, odds, 50.0) == pytest.approx(
                50.0 * (1.0 - p), abs=0.01
            )

    def test_value_climbs_with_price(self):
        """The reason a boost belongs on the longest fairly-priced leg."""
        evs = [
            profit_boost_ev(1.0 / american_to_decimal(o), o, 50.0)
            for o in (-300, -110, 100, 300, 800)
        ]
        assert evs == sorted(evs), evs

    def test_zero_boost_is_the_raw_edge(self):
        assert profit_boost_ev(0.50, 100, 0.0) == pytest.approx(0.0, abs=0.01)


class TestEarlyWinToken:
    def test_lift_is_paid_at_the_offered_price(self):
        # The token adds `lift` to the win probability; its EV contribution is
        # therefore lift * decimal odds.
        p, odds, lift = 0.384, 148, 0.1028
        base = (p * american_to_decimal(odds) - 1) * 100
        with_token = early_win_token_ev(p, odds, lift)
        assert with_token - base == pytest.approx(
            lift * american_to_decimal(odds) * 100, abs=0.01
        )

    def test_zero_lift_changes_nothing(self):
        assert early_win_token_ev(0.5, 100, 0.0) == pytest.approx(0.0, abs=0.01)

    def test_also_prefers_longer_prices(self):
        evs = [
            early_win_token_ev(1.0 / american_to_decimal(o), o, 0.1028)
            for o in (-300, -110, 100, 300)
        ]
        assert evs == sorted(evs), evs


class TestPromoComparison:
    def test_reports_all_three_numbers(self):
        out = promo_comparison(0.384, 148)
        assert set(out) == {"raw_ev_pct", "boost_ev_pct", "token_ev_pct"}
        # Both promotions must improve on the unpromoted bet.
        assert out["boost_ev_pct"] > out["raw_ev_pct"]
        assert out["token_ev_pct"] > out["raw_ev_pct"]


class TestTwoWayParsing:
    PAYLOAD = {
        "bookmakers": [
            {
                "title": "DraftKings",
                "last_update": "2026-07-27T19:34:22Z",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Athletics", "price": 148},
                            {"name": "Boston Red Sox", "price": -180},
                        ],
                    }
                ],
            }
        ]
    }

    def test_each_team_gets_both_prices(self):
        out = parse_two_way_by_book(self.PAYLOAD)
        assert out["Athletics"]["DraftKings"]["over_odds"] == 148
        assert out["Athletics"]["DraftKings"]["under_odds"] == -180
        assert out["Boston Red Sox"]["DraftKings"]["over_odds"] == -180
        assert out["Boston Red Sox"]["DraftKings"]["under_odds"] == 148

    def test_moneyline_carries_no_line(self):
        out = parse_two_way_by_book(self.PAYLOAD)
        assert out["Athletics"]["DraftKings"]["line"] is None

    def test_devigs_to_complementary_probabilities(self):
        out = parse_two_way_by_book(self.PAYLOAD)["Athletics"]["DraftKings"]
        a, b = no_vig_probability(out["over_odds"], out["under_odds"])
        assert a + b == pytest.approx(1.0)


class TestPlayerLinesAreNotBlendedAcrossBooks:
    """The regression that widening the request to every US book could cause."""

    PAYLOAD = {
        "bookmakers": [
            {
                "title": "DraftKings",
                "markets": [{
                    "key": "pitcher_strikeouts",
                    "outcomes": [
                        {"description": "Payton Tolle", "name": "Over",
                         "point": 5.5, "price": -125},
                        {"description": "Payton Tolle", "name": "Under",
                         "point": 5.5, "price": -102},
                    ],
                }],
            },
            {
                "title": "FanDuel",
                "markets": [{
                    "key": "pitcher_strikeouts",
                    "outcomes": [
                        {"description": "Payton Tolle", "name": "Over",
                         "point": 6.5, "price": 120},
                        {"description": "Payton Tolle", "name": "Under",
                         "point": 6.5, "price": -145},
                    ],
                }],
            },
        ]
    }

    def test_books_stay_separate(self):
        out = parse_player_lines_by_book(self.PAYLOAD, "pitcher_strikeouts")
        assert out["Payton Tolle"]["DraftKings"]["line"] == 5.5
        assert out["Payton Tolle"]["FanDuel"]["line"] == 6.5
        assert out["Payton Tolle"]["DraftKings"]["over_odds"] == -125
        assert out["Payton Tolle"]["FanDuel"]["over_odds"] == 120


class TestConsensusEdgeTable:
    def _book(self, title, line, over, under):
        return {title: {"line": line, "over_odds": over, "under_odds": under,
                        "book": title}}

    def test_only_compares_matching_lines(self):
        """An over 5.5 and an over 6.5 are different bets and must not average."""
        by_book = {"pitcher_strikeouts": {"Payton Tolle": {
            **self._book("DraftKings", 5.5, -125, -102),
            **self._book("FanDuel", 6.5, 120, -145),
            **self._book("BetMGM", 6.5, 115, -140),
            **self._book("Bovada", 6.5, 118, -142),
        }}}
        # Every comparison book is on 6.5, so nothing is comparable to DK's 5.5.
        assert consensus_edge_table(by_book).empty

    def test_excludes_the_primary_book_from_its_own_benchmark(self):
        by_book = {"pitcher_strikeouts": {"P": {
            **self._book("DraftKings", 5.5, 100, -120),
            **self._book("FanDuel", 5.5, -110, -110),
            **self._book("BetMGM", 5.5, -110, -110),
            **self._book("Bovada", 5.5, -110, -110),
        }}}
        row = consensus_edge_table(by_book)
        over = row[row["side"] == "Over"].iloc[0]
        # The three comparison books all say 0.50; DK's own +100 must not drag it.
        assert over["consensus_prob"] == pytest.approx(0.50)
        assert over["n_books"] == 3

    def test_respects_the_minimum_book_count(self):
        by_book = {"pitcher_strikeouts": {"P": {
            **self._book("DraftKings", 5.5, 100, -120),
            **self._book("FanDuel", 5.5, -110, -110),
        }}}
        assert consensus_edge_table(by_book).empty

    def test_moneyline_rows_are_labelled_and_not_duplicated(self):
        by_book = {"h2h": {"Athletics": {
            **self._book("DraftKings", None, 148, -180),
            **self._book("FanDuel", None, 145, -175),
            **self._book("BetMGM", None, 150, -182),
            **self._book("Bovada", None, 147, -178),
        }}}
        table = consensus_edge_table(by_book)
        assert len(table) == 1
        assert table.iloc[0]["side"] == "Moneyline"
        assert table.iloc[0]["line"] is None
