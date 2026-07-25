"""
The betting page's display helpers.

The regression these guard: a page that shows "nan%" where a probability is
missing, or announces line movement it has not actually observed. Both are ways
of putting a number in front of a reader that nothing stands behind — the same
failure as an invented prop line, one layer further out.
"""

from __future__ import annotations

import pandas as pd

from betting_report import _movement_notes, _pct, _quote, _short_time
from data import odds_history

EVENT = {"id": "evt-1", "commence_time": "2026-07-25T20:11:00Z",
         "home_team": "Boston Red Sox", "away_team": "Toronto Blue Jays"}


def history_of(*snapshots) -> pd.DataFrame:
    """snapshots: (captured_at, over_odds) pairs for one pitcher's line."""
    rows = []
    for captured_at, over in snapshots:
        rows += odds_history.snapshot_rows(
            EVENT, "pitcher_strikeouts",
            {"Sonny Gray": {"line": 4.5, "over_odds": over, "under_odds": 108,
                            "book": "DraftKings",
                            "last_update": "2026-07-25T15:01:12Z"}},
            captured_at=captured_at)
    return pd.DataFrame(rows)


class TestProbabilityFormatting:
    def test_a_probability_renders_as_a_percentage(self):
        assert _pct(0.5462) == "54.6%"

    def test_a_missing_probability_renders_as_a_dash_not_nan(self):
        """
        None becomes a float NaN once pandas has boxed the column, and "nan%"
        on the page reads as a broken number rather than an absent one.
        """
        for missing in (None, float("nan"), "", "—"):
            assert "nan" not in _pct(missing)
            assert "mdash" in _pct(missing)


class TestQuoteFormatting:
    def test_line_and_price_read_the_way_a_book_posts_them(self):
        assert _quote(4.5, -154) == "4.5 (-154)"
        assert _quote(1.5, 137) == "1.5 (+137)"

    def test_a_line_without_a_price_still_renders(self):
        assert _quote(4.5, None) == "4.5"

    def test_no_line_at_all_renders_as_a_dash(self):
        assert _quote(None, -154) == "—"

    def test_an_unparseable_timestamp_does_not_invent_a_time(self):
        assert _short_time(None) == "an earlier build"
        assert _short_time("not a timestamp") == "an earlier build"
        assert _short_time("2026-07-25T15:01:12Z") == "15:01 UTC"


class TestMovementNotes:
    def test_a_price_move_is_reported_with_both_ends(self):
        note = _movement_notes(
            history_of(("2026-07-25T16:00:00+00:00", -137),
                       ("2026-07-25T19:00:00+00:00", -154)),
            EVENT, ["Sonny Gray"], "pitcher_strikeouts")

        assert "Line movement" in note
        assert "4.5 (-137)" in note and "4.5 (-154)" in note
        assert "16:00 UTC" in note

    def test_an_unmoved_line_says_so_rather_than_staying_silent(self):
        """"Watched, and it did not move" is a finding; silence is not."""
        note = _movement_notes(
            history_of(("2026-07-25T16:00:00+00:00", -137),
                       ("2026-07-25T19:00:00+00:00", -137)),
            EVENT, ["Sonny Gray"], "pitcher_strikeouts")

        assert "No line movement" in note
        assert "2 builds" in note

    def test_a_single_build_claims_no_movement_either_way(self):
        """
        The state of every line on the day the history file is created. The page
        must not imply it has been watching.
        """
        note = _movement_notes(history_of(("2026-07-25T16:00:00+00:00", -137)),
                               EVENT, ["Sonny Gray"], "pitcher_strikeouts")

        assert note == ""

    def test_no_history_yields_no_claim(self):
        for history in (None, pd.DataFrame()):
            assert _movement_notes(history, EVENT, ["Sonny Gray"],
                                   "pitcher_strikeouts") == ""

    def test_a_market_with_no_logged_players_yields_no_claim(self):
        note = _movement_notes(
            history_of(("2026-07-25T16:00:00+00:00", -137),
                       ("2026-07-25T19:00:00+00:00", -154)),
            EVENT, ["Sonny Gray"], "batter_total_bases")

        assert note == ""
