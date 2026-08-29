"""
The closing capture has to survive GitHub's scheduler.

On 2026-08-26 no closing snapshot was taken at all, and with it went the first
live run of the totals capture shipped that afternoon. Nothing failed: the gate
did exactly what it was told.

The cause was arithmetic. For a 22:40 first pitch the old window was 22:05-22:38
and the poll ran at :00/:20/:40, so precisely one tick -- 22:20 -- could ever
land inside it. GitHub delays scheduled runs as a matter of course; the close
landed 4 minutes late on 08-24, 14 late on 08-25, and on 08-26 it evidently
passed 22:38. One tick inside the window is not a schedule, it is a coin flip.

Both bounds are tested here because they do different jobs. The floor is a
correctness constraint -- past first pitch the book is pricing a different
market -- and it does not move. The ceiling is a quality preference, and a row
not taken cannot be filtered into existence later.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from client.odds_api_client import OddsAPIClient
from scripts.capture_close import (
    DEFAULT_FLOOR_MIN,
    DEFAULT_WINDOW_MIN,
    minutes_to_first_pitch,
)

FIRST_PITCH = datetime(2026, 8, 26, 22, 40, tzinfo=timezone.utc)
EVENT = {"commence_time": "2026-08-26T22:40:00Z"}


def ticks(step: int, window: int, floor: int = DEFAULT_FLOOR_MIN) -> list[str]:
    """Which polls of a `step`-minute cron land inside the gate."""
    out = []
    for h in range(21, 24):
        for m in range(0, 60, step):
            t = datetime(2026, 8, 26, h, m, tzinfo=timezone.utc)
            mins = (FIRST_PITCH - t).total_seconds() / 60.0
            if floor <= mins <= window:
                out.append(f"{h:02d}:{m:02d}")
    return out


class TestTheMissOn0826:
    def test_the_old_cadence_had_exactly_one_chance(self):
        """Which is why losing it lost the whole capture."""
        assert ticks(20, 35) == ["22:20"]

    def test_the_new_cadence_has_several(self):
        assert len(ticks(10, DEFAULT_WINDOW_MIN)) >= 3

    def test_it_now_tolerates_a_realistic_delay(self):
        """
        The observed delays were 4 and 14 minutes and growing. At least one tick
        must still land inside the gate when every run is pushed back 25.
        """
        delayed = []
        for h in range(21, 24):
            for m in range(0, 60, 10):
                t = datetime(2026, 8, 26, h, m, tzinfo=timezone.utc) + timedelta(minutes=25)
                mins = (FIRST_PITCH - t).total_seconds() / 60.0
                if DEFAULT_FLOOR_MIN <= mins <= DEFAULT_WINDOW_MIN:
                    delayed.append(t.strftime("%H:%M"))
        assert delayed, "a 25-minute delay would lose the capture again"


class TestTheFloorIsNotNegotiable:
    def test_after_first_pitch_is_refused(self):
        """In-play prices are a different market and would corrupt the record."""
        after = datetime(2026, 8, 26, 22, 45, tzinfo=timezone.utc)
        assert minutes_to_first_pitch(EVENT, now=after) < 0

    def test_the_floor_did_not_move(self):
        assert DEFAULT_FLOOR_MIN == 2

    def test_inside_the_floor_is_outside_the_gate(self):
        one_min = datetime(2026, 8, 26, 22, 39, tzinfo=timezone.utc)
        assert minutes_to_first_pitch(EVENT, now=one_min) < DEFAULT_FLOOR_MIN


class TestMinutesArithmetic:
    @pytest.mark.parametrize("hh,mm,expected", [
        (22, 10, 30.0), (22, 20, 20.0), (22, 38, 2.0), (21, 55, 45.0),
    ])
    def test_minutes_before_first_pitch(self, hh, mm, expected):
        now = datetime(2026, 8, 26, hh, mm, tzinfo=timezone.utc)
        assert minutes_to_first_pitch(EVENT, now=now) == pytest.approx(expected)

    def test_a_missing_commence_time_is_none_not_zero(self):
        """Zero would read as 'right now' and capture in-play prices."""
        assert minutes_to_first_pitch({}, now=FIRST_PITCH) is None


class TestTheDoubleheaderNightcap:
    """
    The gate reads one event, and on 2026-08-29 there are two.

    Boston plays a split doubleheader at Yankee Stadium that day: game 1 at
    17:05Z, game 2 at 23:15Z. The provider orders /events by commence_time and
    keeps a game listed until it settles rather than until it starts -- measured
    2026-08-27, when the feed still carried a game 81 minutes underway, and
    carried it first.

    So while game 1 is live, an unfiltered find_event keeps returning it. The
    nightcap's window (22:30-23:13Z) then reads a first pitch six hours in the
    past, falls under the floor, and declines -- printing the same line as a
    healthy skip. That is the 2026-08-26 failure again: not an error, just a
    close that never got taken, and a close cannot be reconstructed afterwards.
    """

    NOW = datetime(2026, 8, 29, 22, 40, tzinfo=timezone.utc)  # inside game 2's window
    OPENER = {"id": "g1", "commence_time": "2026-08-29T17:05:00Z",
              "away_team": "Boston Red Sox", "home_team": "New York Yankees"}
    NIGHTCAP = {"id": "g2", "commence_time": "2026-08-29T23:15:00Z",
                "away_team": "Boston Red Sox", "home_team": "New York Yankees"}

    @property
    def client(self):
        return OddsAPIClient(api_key="test-key")

    def test_the_unfiltered_read_still_returns_the_opener(self):
        """The behaviour being guarded against, stated as a fact."""
        ev = self.client.find_event(
            "Boston Red Sox", events=[self.OPENER, self.NIGHTCAP], now=self.NOW
        )
        assert ev["id"] == "g1"

    def test_and_that_opener_would_be_refused_as_in_play(self):
        """Which is why the miss is silent: it looks exactly like a normal skip."""
        assert minutes_to_first_pitch(self.OPENER, now=self.NOW) < DEFAULT_FLOOR_MIN

    def test_upcoming_only_selects_the_nightcap(self):
        ev = self.client.find_event(
            "Boston Red Sox", events=[self.OPENER, self.NIGHTCAP],
            upcoming_only=True, now=self.NOW,
        )
        assert ev["id"] == "g2"

    def test_and_the_nightcap_is_then_inside_the_gate(self):
        mins = minutes_to_first_pitch(self.NIGHTCAP, now=self.NOW)
        assert DEFAULT_FLOOR_MIN <= mins <= DEFAULT_WINDOW_MIN

    def test_a_single_game_day_is_unaffected(self):
        """The flag must be free on the other 95% of the schedule."""
        events = [self.NIGHTCAP]
        before = datetime(2026, 8, 29, 22, 40, tzinfo=timezone.utc)
        plain = self.client.find_event("Boston Red Sox", events=events, now=before)
        filtered = self.client.find_event(
            "Boston Red Sox", events=events, upcoming_only=True, now=before
        )
        assert plain == filtered == self.NIGHTCAP

    def test_no_upcoming_game_returns_none_rather_than_a_finished_one(self):
        """A stale event would be captured as if it were a close."""
        after_both = datetime(2026, 8, 30, 3, 0, tzinfo=timezone.utc)
        assert self.client.find_event(
            "Boston Red Sox", events=[self.OPENER, self.NIGHTCAP],
            upcoming_only=True, now=after_both,
        ) is None

    def test_an_unparseable_commence_time_is_not_silently_dropped(self):
        """
        Skipping it would turn a malformed field into a missed capture. The
        window check refuses to spend on it anyway, so keeping it is the safe
        direction of the two.
        """
        broken = {"id": "g?", "commence_time": "not-a-date",
                  "away_team": "Boston Red Sox", "home_team": "New York Yankees"}
        ev = self.client.find_event(
            "Boston Red Sox", events=[broken], upcoming_only=True, now=self.NOW
        )
        assert ev["id"] == "g?"
        assert minutes_to_first_pitch(broken, now=self.NOW) is None
