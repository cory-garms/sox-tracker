"""
Game totals, captured once per game at the close.

Totals and the run line were the only markets this project stored *nothing*
for -- and a closing total is one of the few things here that cannot be
reconstructed later. A projection can be replayed from stored odds; a price
nobody wrote down is gone when the game starts, and there are about thirty
games left.

Once per game rather than on every build, and that is a budget decision with a
real cost. Four builds a day is ~124 credits a cycle against a 500 quota
already spending ~454. The only way to fund it would be dropping the moneyline,
which is the sole market benchmark the win-probability model has. One capture at
the close is ~30 and fits. It trades away intraday movement and keeps the close;
of the two, only the close expires.
"""

from __future__ import annotations

from client.odds_api_client import MARKET_TOTALS, parse_two_way_by_book
from data import odds_history
from scripts.capture_close import EXTRA_CLOSING_MARKETS, EXTRA_CLOSING_TWO_WAY

EVENT = {"id": "e1", "commence_time": "2026-08-26T22:40:00Z",
         "home_team": "Miami Marlins", "away_team": "Boston Red Sox"}


def payload(*books):
    """books: (title, point, over_price, under_price)"""
    return {"bookmakers": [
        {"title": t, "last_update": "2026-08-26T22:10:00Z", "markets": [
            {"key": "totals", "outcomes": [
                {"name": "Over", "point": pt, "price": op},
                {"name": "Under", "point": pt, "price": up}]}]}
        for t, pt, op, up in books
    ]}


class TestTotalsAreCaptured:
    def test_totals_are_in_the_closing_set(self):
        assert MARKET_TOTALS in EXTRA_CLOSING_TWO_WAY

    def test_they_are_not_in_the_player_prop_set(self):
        """Their outcomes are Over/Under, not a player; a different parser."""
        assert MARKET_TOTALS not in EXTRA_CLOSING_MARKETS

    def test_both_sides_reach_the_log(self):
        rows = odds_history.snapshot_rows_by_book(
            EVENT, MARKET_TOTALS,
            parse_two_way_by_book(payload(("DraftKings", 8.5, -110, -110)), MARKET_TOTALS))
        assert {r["player"] for r in rows} == {"Over", "Under"}

    def test_every_row_carries_its_number(self):
        """
        A total without its point is not a bet. Discarding it is what made the
        consensus read a 10.0 and a 9.5 as the same market on 2026-07-27 and
        report a -5.56% price as +0.27%.
        """
        rows = odds_history.snapshot_rows_by_book(
            EVENT, MARKET_TOTALS,
            parse_two_way_by_book(payload(("DraftKings", 8.5, -110, -110)), MARKET_TOTALS))
        assert all(r["line"] == 8.5 for r in rows)

    def test_books_on_different_totals_stay_apart(self):
        rows = odds_history.snapshot_rows_by_book(
            EVENT, MARKET_TOTALS,
            parse_two_way_by_book(
                payload(("DraftKings", 8.5, -110, -110), ("FanDuel", 9.0, -105, -115)),
                MARKET_TOTALS))
        by_book = {(r["book"], r["player"]): r["line"] for r in rows}
        assert by_book[("DraftKings", "Over")] == 8.5
        assert by_book[("FanDuel", "Over")] == 9.0

    def test_each_side_gets_the_opposing_price_to_de_vig_against(self):
        rows = odds_history.snapshot_rows_by_book(
            EVENT, MARKET_TOTALS,
            parse_two_way_by_book(payload(("FanDuel", 9.0, -105, -115)), MARKET_TOTALS))
        over = next(r for r in rows if r["player"] == "Over")
        under = next(r for r in rows if r["player"] == "Under")
        assert (over["over_odds"], over["under_odds"]) == (-105, -115)
        assert (under["over_odds"], under["under_odds"]) == (-115, -105)

    def test_a_three_way_market_is_refused_rather_than_guessed(self):
        """Nothing to de-vig a third outcome against."""
        odd = {"bookmakers": [{"title": "X", "markets": [{"key": "totals", "outcomes": [
            {"name": "Over", "point": 8.5, "price": -110},
            {"name": "Under", "point": 8.5, "price": -110},
            {"name": "Exactly", "point": 8.5, "price": 900}]}]}]}
        assert parse_two_way_by_book(odd, MARKET_TOTALS) == {}

    def test_an_empty_payload_logs_nothing(self):
        assert odds_history.snapshot_rows_by_book(
            EVENT, MARKET_TOTALS, parse_two_way_by_book({}, MARKET_TOTALS)) == []
