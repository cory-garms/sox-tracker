"""
The odds history log — the page's only memory of what the market did.

The regression this guards: every build fetched fresh lines and threw the
previous snapshot away, so a price that moved -137 to -154 inside one afternoon
left no trace anywhere. Everything here is about that file being written
faithfully, read back honestly, and never being the reason a build fails.
"""

from __future__ import annotations

import pandas as pd
import pytest

from data import odds_history

EVENT = {
    "id": "evt-1",
    "commence_time": "2026-07-25T20:11:00Z",
    "home_team": "Boston Red Sox",
    "away_team": "Toronto Blue Jays",
}


def lines(line: float = 4.5, over: int = -137, under: int = 108,
          player: str = "Sonny Gray") -> dict:
    return {player: {"line": line, "over_odds": over, "under_odds": under,
                     "book": "DraftKings", "last_update": "2026-07-25T15:01:12Z"}}


class TestSnapshotRows:
    def test_flattens_a_market_into_rows(self):
        rows = odds_history.snapshot_rows(EVENT, "pitcher_strikeouts", lines(),
                                          captured_at="2026-07-25T16:00:00+00:00")

        assert len(rows) == 1
        assert rows[0]["event_id"] == "evt-1"
        assert rows[0]["market"] == "pitcher_strikeouts"
        assert rows[0]["player"] == "Sonny Gray"
        assert rows[0]["line"] == 4.5
        assert rows[0]["over_odds"] == -137

    def test_keeps_when_we_looked_apart_from_when_the_book_moved(self):
        """
        Two different facts. `captured_at` is this build; `last_update` is the
        bookmaker's own timestamp, and a page that conflates them will claim
        freshness it does not have.
        """
        rows = odds_history.snapshot_rows(EVENT, "pitcher_strikeouts", lines(),
                                          captured_at="2026-07-25T16:00:00+00:00")

        assert rows[0]["captured_at"] == "2026-07-25T16:00:00+00:00"
        assert rows[0]["last_update"] == "2026-07-25T15:01:12Z"

    def test_an_empty_market_logs_nothing(self):
        assert odds_history.snapshot_rows(EVENT, "batter_total_bases", {}) == []

    def test_no_event_logs_nothing(self):
        assert odds_history.snapshot_rows(None, "pitcher_strikeouts", lines()) == []

    def test_entries_without_a_numeric_line_are_skipped(self):
        broken = {"Sonny Gray": {"line": None, "over_odds": -137}}

        assert odds_history.snapshot_rows(EVENT, "pitcher_strikeouts", broken) == []


class TestAppendSnapshot:
    def test_writes_and_reads_back(self, tmp_path):
        path = tmp_path / "odds_history.parquet"
        rows = odds_history.snapshot_rows(EVENT, "pitcher_strikeouts", lines(),
                                          captured_at="2026-07-25T16:00:00+00:00")

        assert odds_history.append_snapshot(rows, path) == 1
        assert len(odds_history.load_history(path)) == 1

    def test_appends_rather_than_replacing(self, tmp_path):
        """The whole point is accumulation — a build must never truncate history."""
        path = tmp_path / "odds_history.parquet"
        odds_history.append_snapshot(
            odds_history.snapshot_rows(EVENT, "pitcher_strikeouts", lines(),
                                       captured_at="2026-07-25T16:00:00+00:00"), path)
        odds_history.append_snapshot(
            odds_history.snapshot_rows(EVENT, "pitcher_strikeouts", lines(over=-154),
                                       captured_at="2026-07-25T19:00:00+00:00"), path)

        stored = odds_history.load_history(path)
        assert len(stored) == 2
        assert sorted(stored["over_odds"]) == [-154, -137]

    def test_rerunning_the_same_build_changes_nothing(self, tmp_path):
        """Workflows get re-run. A re-run must be idempotent, not a duplicate."""
        path = tmp_path / "odds_history.parquet"
        rows = odds_history.snapshot_rows(EVENT, "pitcher_strikeouts", lines(),
                                          captured_at="2026-07-25T16:00:00+00:00")
        odds_history.append_snapshot(rows, path)

        assert odds_history.append_snapshot(rows, path) == 0
        assert len(odds_history.load_history(path)) == 1

    def test_an_unwritable_path_does_not_break_the_build(self, tmp_path):
        """Losing a snapshot is a shame; failing the page over it is worse."""
        unwritable = tmp_path / "not-a-dir.parquet" / "odds.parquet"
        rows = odds_history.snapshot_rows(EVENT, "pitcher_strikeouts", lines())
        (tmp_path / "not-a-dir.parquet").write_text("i am a file")

        assert odds_history.append_snapshot(rows, unwritable) == 0

    def test_missing_history_reads_as_empty_not_an_error(self, tmp_path):
        history = odds_history.load_history(tmp_path / "nothing-here.parquet")

        assert history.empty
        assert list(history.columns) == odds_history.COLUMNS


class TestLineMovement:
    def _history(self, *snapshots) -> pd.DataFrame:
        rows = []
        for captured_at, kwargs in snapshots:
            rows += odds_history.snapshot_rows(EVENT, "pitcher_strikeouts",
                                               lines(**kwargs), captured_at=captured_at)
        return pd.DataFrame(rows)

    def test_reports_a_price_move_from_the_first_snapshot_to_the_last(self):
        history = self._history(
            ("2026-07-25T16:00:00+00:00", {"over": -137}),
            ("2026-07-25T19:00:00+00:00", {"over": -154}),
        )

        move = odds_history.line_movement(history, "evt-1", "pitcher_strikeouts",
                                          "Sonny Gray")

        assert move["moved"]
        assert move["opened_over_odds"] == -137
        assert move["current_over_odds"] == -154
        assert move["snapshots"] == 2

    def test_reports_an_unmoved_line_as_watched_but_still(self):
        """
        "We watched and it did not move" and "we have not watched" are different
        facts, and the page says different things about them.
        """
        history = self._history(
            ("2026-07-25T16:00:00+00:00", {}),
            ("2026-07-25T19:00:00+00:00", {}),
        )

        move = odds_history.line_movement(history, "evt-1", "pitcher_strikeouts",
                                          "Sonny Gray")

        assert move["moved"] is False

    def test_a_single_snapshot_reports_nothing(self):
        """Which is every line on the day the history file is created."""
        history = self._history(("2026-07-25T16:00:00+00:00", {}))

        assert odds_history.line_movement(history, "evt-1", "pitcher_strikeouts",
                                          "Sonny Gray") is None

    def test_movement_is_scoped_to_one_event(self):
        """Tomorrow's line is not a later observation of today's."""
        history = self._history(("2026-07-25T16:00:00+00:00", {}))
        tomorrow = pd.DataFrame(odds_history.snapshot_rows(
            {**EVENT, "id": "evt-2"}, "pitcher_strikeouts", lines(line=5.5),
            captured_at="2026-07-26T16:00:00+00:00"))

        move = odds_history.line_movement(pd.concat([history, tomorrow]),
                                          "evt-1", "pitcher_strikeouts", "Sonny Gray")

        assert move is None

    def test_unknown_player_or_empty_history_reports_nothing(self):
        history = self._history(("2026-07-25T16:00:00+00:00", {}))

        assert odds_history.line_movement(history, "evt-1", "pitcher_strikeouts",
                                          "Nobody At All") is None
        assert odds_history.line_movement(pd.DataFrame(), "evt-1",
                                          "pitcher_strikeouts", "Sonny Gray") is None


class TestLinelessMarkets:
    """
    Capture timestamps here predate EVENT's commence_time on purpose: snapshots
    taken after first pitch are in-play prices and are filtered out everywhere.

    A moneyline has two team names and a price each, and no number at all.

    The regression: snapshot_rows() dropped every entry whose `line` was None,
    which is correct for a prop the parser could not pin a number to and wrong
    for a market that has no number by nature. It silently discarded every h2h
    row, so a moneyline bet could be logged but never graded against a close.
    """

    ML = {
        "Athletics": {"line": None, "over_odds": 148, "under_odds": -180,
                      "book": "DraftKings", "last_update": "2026-07-27T19:34:22Z"},
        "Boston Red Sox": {"line": None, "over_odds": -180, "under_odds": 148,
                           "book": "DraftKings", "last_update": "2026-07-27T19:34:22Z"},
    }

    def test_moneyline_rows_survive(self):
        rows = odds_history.snapshot_rows(EVENT, "h2h", self.ML)
        assert len(rows) == 2
        assert {r["player"] for r in rows} == {"Athletics", "Boston Red Sox"}

    def test_moneyline_line_is_nan_not_a_number(self):
        rows = odds_history.snapshot_rows(EVENT, "h2h", self.ML)
        assert all(r["line"] != r["line"] for r in rows)      # NaN

    def test_a_prop_without_a_line_is_still_dropped(self):
        """The original guard must survive: this one really is a parse failure."""
        broken = {"Someone": {"line": None, "over_odds": -110, "under_odds": -110}}
        assert odds_history.snapshot_rows(EVENT, "pitcher_strikeouts", broken) == []

    def test_unmoved_moneyline_does_not_report_movement(self):
        """
        NaN != NaN is True, so comparing the raw line cells reported every
        moneyline as having moved on every single build.
        """
        first = odds_history.snapshot_rows(EVENT, "h2h", self.ML,
                                           captured_at="2026-07-25T18:00:00+00:00")
        second = odds_history.snapshot_rows(EVENT, "h2h", self.ML,
                                            captured_at="2026-07-25T20:00:00+00:00")
        history = pd.DataFrame(first + second).reindex(columns=odds_history.COLUMNS)
        mv = odds_history.line_movement(history, "evt-1", "h2h", "Athletics")
        assert mv is not None
        assert mv["snapshots"] == 2
        assert mv["moved"] is False

    def test_moved_moneyline_is_detected(self):
        first = odds_history.snapshot_rows(EVENT, "h2h", self.ML,
                                           captured_at="2026-07-25T18:00:00+00:00")
        drifted = {**self.ML, "Athletics": {**self.ML["Athletics"], "over_odds": 158}}
        second = odds_history.snapshot_rows(EVENT, "h2h", drifted,
                                            captured_at="2026-07-25T20:00:00+00:00")
        history = pd.DataFrame(first + second).reindex(columns=odds_history.COLUMNS)
        mv = odds_history.line_movement(history, "evt-1", "h2h", "Athletics")
        assert mv["moved"] is True
        assert mv["opened_over_odds"] == 148
        assert mv["current_over_odds"] == 158
