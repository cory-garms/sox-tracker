"""
First-pitch time on the matchup and odds pages.

The odds page states "lines as of HH:MM UTC"; that number only means something
next to a first-pitch time, so the two are shown together and share a timezone.
"""

from __future__ import annotations

import pytest

from analysis.matchup import _parse_single_preview, format_first_pitch

BOS = 111
TOR = 141


def raw_game(
    *,
    game_date: str | None = "2026-07-25T20:10:00Z",
    tbd: bool = False,
) -> dict:
    """A schedule game as the MLB API returns it, Red Sox at home."""
    game: dict = {
        "gamePk": 824739,
        "officialDate": "2026-07-25",
        "status": {"detailedState": "Pre-Game", "startTimeTBD": tbd},
        "teams": {
            "home": {"team": {"id": BOS}},
            "away": {"team": {"id": TOR}},
        },
    }
    if game_date is not None:
        game["gameDate"] = game_date
    return game


def preview(**kwargs) -> dict:
    return _parse_single_preview(raw_game(**kwargs), BOS, "2026-07-25")


class TestFirstPitchFormatting:
    def test_utc_start_is_shown_in_eastern_and_utc(self):
        assert format_first_pitch(preview()) == "4:10 PM ET (20:10 UTC)"

    def test_leading_zero_is_dropped_from_the_hour(self):
        """"7:10 PM", not "07:10 PM"."""
        assert format_first_pitch(preview(game_date="2026-07-25T23:10:00Z")) \
            .startswith("7:10 PM ET")

    def test_a_game_after_midnight_utc_reports_the_correct_eastern_evening(self):
        """
        A 20:10 ET first pitch is 00:10 UTC the *next* day. Reporting the UTC
        date as the game date would put the game on the wrong night.
        """
        assert format_first_pitch(preview(game_date="2026-07-26T00:10:00Z")) == \
            "8:10 PM ET (00:10 UTC)"

    def test_eastern_offset_is_daylight_time_in_season(self):
        """April–September is EDT (UTC-4), not EST — a season-long off-by-one."""
        assert format_first_pitch(preview(game_date="2026-04-15T17:05:00Z")) == \
            "1:05 PM ET (17:05 UTC)"


class TestFirstPitchUnknown:
    def test_schedule_flagged_tbd_reports_tbd(self):
        """
        startTimeTBD is the schedule saying the time is genuinely undecided.
        MLB still sends a placeholder gameDate, so trusting the field alone
        would print a confident, wrong time.
        """
        assert format_first_pitch(preview(tbd=True)) == "TBD"

    def test_missing_time_reports_tbd(self):
        assert format_first_pitch(preview(game_date=None)) == "TBD"

    def test_unparseable_time_reports_tbd_rather_than_raising(self):
        assert format_first_pitch(preview(game_date="not a timestamp")) == "TBD"

    def test_empty_preview_reports_tbd(self):
        assert format_first_pitch({}) == "TBD"


class TestPreviewCarriesTheStartTime:
    def test_preview_keeps_the_raw_utc_instant(self):
        assert preview()["game_time_utc"] == "2026-07-25T20:10:00Z"

    def test_preview_carries_the_tbd_flag(self):
        assert preview(tbd=True)["start_time_tbd"] is True
        assert preview()["start_time_tbd"] is False
