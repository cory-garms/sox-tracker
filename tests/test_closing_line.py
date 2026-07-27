"""
Closing-line capture, and the two ways it can quietly record the wrong thing.

Both failures here are silent rather than loud: an in-play price looks exactly
like a closing price in the file, and a binary-conflict resolution that drops
half the log leaves a file that still opens cleanly. Neither would surface as an
error, and both would corrupt the only measurement this repo has that does not
depend on results.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from data import bet_log, odds_history
from scripts.capture_close import minutes_to_first_pitch
from scripts.merge_odds_history import union

EVENT_ID = "evt-close"
FIRST_PITCH = "2026-07-28T01:40:00Z"


def _now(minutes_before: float) -> datetime:
    start = datetime(2026, 7, 28, 1, 40, tzinfo=timezone.utc)
    return start - timedelta(minutes=minutes_before)


class TestMinutesToFirstPitch:
    def test_counts_down_to_the_start(self):
        ev = {"commence_time": FIRST_PITCH}
        assert minutes_to_first_pitch(ev, _now(35)) == pytest.approx(35)
        assert minutes_to_first_pitch(ev, _now(0)) == pytest.approx(0)

    def test_goes_negative_once_underway(self):
        ev = {"commence_time": FIRST_PITCH}
        assert minutes_to_first_pitch(ev, _now(-20)) == pytest.approx(-20)

    def test_handles_a_missing_or_unparseable_time(self):
        assert minutes_to_first_pitch({}, _now(30)) is None
        assert minutes_to_first_pitch({"commence_time": "soon"}, _now(30)) is None

    def test_accepts_both_offset_spellings(self):
        """The provider sends "Z"; our own log writes "+00:00"."""
        a = minutes_to_first_pitch({"commence_time": "2026-07-28T01:40:00Z"}, _now(10))
        b = minutes_to_first_pitch(
            {"commence_time": "2026-07-28T01:40:00+00:00"}, _now(10)
        )
        assert a == pytest.approx(b)


class TestUnionIsLossless:
    """
    Every ordinary binary-conflict resolution picks a side. Both sides of this
    file routinely hold snapshots the other lacks.
    """

    def _rows(self, stamp: str, over: int):
        return pd.DataFrame(odds_history.snapshot_rows(
            {"id": EVENT_ID, "commence_time": FIRST_PITCH,
             "home_team": "Athletics", "away_team": "Boston Red Sox"},
            "h2h",
            {"Athletics": {"line": None, "over_odds": over, "under_odds": -180}},
            captured_at=stamp,
        ))

    def test_keeps_snapshots_unique_to_either_side(self):
        ours = self._rows("2026-07-27T19:00:00+00:00", 148)
        theirs = self._rows("2026-07-27T23:00:00+00:00", 158)
        merged = union([ours, theirs])
        assert len(merged) == 2
        assert set(merged["over_odds"]) == {148, 158}

    def test_is_idempotent(self):
        ours = self._rows("2026-07-27T19:00:00+00:00", 148)
        once = union([ours, ours])
        twice = union([once, ours, once])
        assert len(once) == len(twice) == 1

    def test_orders_oldest_first(self):
        late = self._rows("2026-07-27T23:00:00+00:00", 158)
        early = self._rows("2026-07-27T19:00:00+00:00", 148)
        merged = union([late, early])
        assert list(merged["over_odds"]) == [148, 158]

    def test_empty_inputs_are_survivable(self):
        assert union([]).empty
        assert union([pd.DataFrame(columns=odds_history.COLUMNS)]).empty


class TestGradingIgnoresInPlayPrices:
    """
    Now that a job runs minutes before first pitch, a delayed runner can land
    after the game has started. An in-play price is a different market, and
    recording one as the close would invert the CLV of every bet on that game.
    """

    def _history(self, stamps_and_prices):
        rows = []
        for stamp, price in stamps_and_prices:
            rows += odds_history.snapshot_rows(
                {"id": EVENT_ID, "commence_time": FIRST_PITCH,
                 "home_team": "Athletics", "away_team": "Boston Red Sox"},
                "h2h",
                {"Athletics": {"line": None, "over_odds": price, "under_odds": -180}},
                captured_at=stamp,
            )
        return pd.DataFrame(rows).reindex(columns=odds_history.COLUMNS)

    def _log(self, tmp_path):
        path = tmp_path / "bets.parquet"
        bet_log.record_bet("Athletics", "h2h", "Moneyline", 148,
                           event_id=EVENT_ID, path=path)
        return path

    def test_uses_the_last_pre_game_price(self, tmp_path):
        path = self._log(tmp_path)
        history = self._history([
            ("2026-07-27T19:00:00+00:00", 148),
            ("2026-07-28T01:20:00+00:00", 158),   # 20 min before: the close
            ("2026-07-28T02:30:00+00:00", 600),   # in play: must be ignored
        ])
        graded = bet_log.grade_from_history(history, path=path)
        assert graded.iloc[0]["closing_price"] == 158

    def test_leaves_it_ungraded_when_every_snapshot_is_in_play(self, tmp_path):
        path = self._log(tmp_path)
        history = self._history([("2026-07-28T02:30:00+00:00", 600)])
        graded = bet_log.grade_from_history(history, path=path)
        assert pd.isna(graded.iloc[0]["closing_price"])

    def test_a_snapshot_exactly_at_first_pitch_still_counts(self, tmp_path):
        path = self._log(tmp_path)
        history = self._history([("2026-07-28T01:40:00+00:00", 158)])
        graded = bet_log.grade_from_history(history, path=path)
        assert graded.iloc[0]["closing_price"] == 158


class TestClvSummary:
    def test_beating_the_close_is_a_lower_price_at_the_time_taken(self):
        frame = pd.DataFrame([
            {"price": 148.0, "closing_price": 120.0},   # took +148, closed +120: good
            {"price": 120.0, "closing_price": 148.0},   # the reverse: bad
        ])
        out = bet_log.clv_summary(frame)
        assert out["n"] == 2
        assert out["beat_close_pct"] == 50.0

    def test_reports_nothing_when_nothing_is_graded(self):
        frame = pd.DataFrame([{"price": 148.0, "closing_price": float("nan")}])
        assert bet_log.clv_summary(frame)["n"] == 0
