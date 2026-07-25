"""
Parsing of The Odds API payloads, and how the page timestamps what it parsed.

A statically built page can only ever show odds as of its last build. The
`last_update` the bookmaker sends is the only honest answer to "as of when?",
so it has to survive parsing and reach the report.
"""

from __future__ import annotations

import pytest

from betting_report import _format_line_timestamp
from client.odds_api_client import MARKET_PITCHER_KS, _parse_player_lines


def payload(
    *,
    book_updated: str = "2026-07-25T15:01:12Z",
    market_updated: str | None = None,
    market_key: str = MARKET_PITCHER_KS,
) -> dict:
    """One bookmaker quoting Sonny Gray 4.5 strikeouts, as the API returns it."""
    market: dict = {
        "key": market_key,
        "outcomes": [
            {"name": "Over", "description": "Sonny Gray", "price": -137, "point": 4.5},
            {"name": "Under", "description": "Sonny Gray", "price": 108, "point": 4.5},
        ],
    }
    if market_updated is not None:
        market["last_update"] = market_updated
    return {
        "bookmakers": [{
            "key": "draftkings",
            "title": "DraftKings",
            "last_update": book_updated,
            "markets": [market],
        }]
    }


class TestParsingPlayerLines:
    def test_line_and_both_prices_are_parsed(self):
        entry = _parse_player_lines(payload(), MARKET_PITCHER_KS)["Sonny Gray"]

        assert entry["line"] == 4.5
        assert entry["over_odds"] == -137
        assert entry["under_odds"] == 108

    def test_book_title_is_carried(self):
        entry = _parse_player_lines(payload(), MARKET_PITCHER_KS)["Sonny Gray"]

        assert entry["book"] == "DraftKings"

    def test_other_markets_are_ignored(self):
        parsed = _parse_player_lines(payload(market_key="batter_total_bases"),
                                     MARKET_PITCHER_KS)

        assert parsed == {}

    def test_outcome_without_a_point_is_dropped(self):
        """A line we cannot pin a number to is not a line."""
        p = payload()
        for outcome in p["bookmakers"][0]["markets"][0]["outcomes"]:
            del outcome["point"]

        assert _parse_player_lines(p, MARKET_PITCHER_KS) == {}

    def test_empty_payload_parses_to_nothing(self):
        assert _parse_player_lines({}, MARKET_PITCHER_KS) == {}


class TestLastUpdateSurvivesParsing:
    def test_bookmaker_timestamp_is_carried(self):
        entry = _parse_player_lines(payload(), MARKET_PITCHER_KS)["Sonny Gray"]

        assert entry["last_update"] == "2026-07-25T15:01:12Z"

    def test_market_timestamp_wins_when_present(self):
        """The per-market stamp is the more precise of the two."""
        entry = _parse_player_lines(
            payload(book_updated="2026-07-25T15:01:12Z",
                    market_updated="2026-07-25T18:44:02Z"),
            MARKET_PITCHER_KS,
        )["Sonny Gray"]

        assert entry["last_update"] == "2026-07-25T18:44:02Z"

    def test_missing_timestamp_is_none_not_invented(self):
        p = payload()
        del p["bookmakers"][0]["last_update"]

        entry = _parse_player_lines(p, MARKET_PITCHER_KS)["Sonny Gray"]

        assert entry["last_update"] is None


class TestTimestampFormatting:
    def test_zulu_timestamp_renders_as_utc(self):
        assert _format_line_timestamp("2026-07-25T15:01:12Z") == \
            "15:01 UTC on 25 Jul 2026"

    def test_offset_timestamp_is_converted_to_utc(self):
        """16:01+01:00 is 15:01 UTC — the page states one timezone only."""
        assert _format_line_timestamp("2026-07-25T16:01:12+01:00") == \
            "15:01 UTC on 25 Jul 2026"

    @pytest.mark.parametrize("raw", [None, "", "not a timestamp"])
    def test_unusable_input_yields_no_timestamp(self, raw):
        """An unlabelled line beats a fabricated timestamp."""
        assert _format_line_timestamp(raw) is None
