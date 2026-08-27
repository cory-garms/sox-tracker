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
