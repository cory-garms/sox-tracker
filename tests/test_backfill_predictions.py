"""
Retroactive prediction replay.

The regression this guards is **lookahead**. A backfill that lets the model see
results from after the date it is projecting produces a track record that looks
excellent and means nothing — and it fails silently, because the numbers all
still compute. Every guard in the replay path is pinned here.

The load-bearing property is the first test: replaying date D against the full
season must give the same answer as replaying it against a cache truncated to
D. If those ever diverge, something downstream of the truncation is reading the
future.
"""

from __future__ import annotations

import pandas as pd
import pytest

from scripts.backfill_predictions import game_date_of, opponent_id_of, replay

BOS = 111
SF = 137


def _pitching(dates, so=6, ip_outs=18, player_id=700, name="Test Starter"):
    return pd.DataFrame([
        {"player_id": player_id, "player_name": name, "game_date": d,
         "is_starter": True, "ip_outs": ip_outs, "so": so, "game_pk": 900 + i}
        for i, d in enumerate(dates)
    ])


def _batting(dates, player_id=800, name="Test Hitter"):
    return pd.DataFrame([
        {"player_id": player_id, "player_name": name, "game_date": d,
         "batting_order": 3, "ab": 4, "pa": 4, "h": 1,
         "doubles": 0, "triples": 0, "hr": 0, "game_pk": 800 + i}
        for i, d in enumerate(dates)
    ])


def _odds(game_date="2026-08-20", market="pitcher_strikeouts",
          player="Test Starter", line=4.5, captured="2026-08-20T15:00:00+00:00"):
    return pd.DataFrame([{
        "captured_at": captured,
        "event_id": "e1",
        # 23:10 UTC on the game date -> 19:10 ET the same day
        "commence_time": f"{game_date}T23:10:00Z",
        "home_team": "Boston Red Sox", "away_team": "San Francisco Giants",
        "market": market, "player": player, "line": line,
        "over_odds": -120, "under_odds": 100,
        "book": "DraftKings", "last_update": captured,
    }])


EMPTY = pd.DataFrame()


class TestNoLookahead:
    """The property everything else rests on."""

    def test_replaying_a_date_ignores_everything_after_it(self):
        before = ["2026-08-02", "2026-08-08", "2026-08-14"]
        after = ["2026-08-26", "2026-09-01", "2026-09-07"]

        # A wildly different future: 15 K per start instead of 6.
        full = pd.concat([_pitching(before, so=6), _pitching(after, so=15)],
                         ignore_index=True)
        truncated = _pitching(before, so=6)

        odds = _odds(game_date="2026-08-20")

        from_full = replay(odds, full, EMPTY, EMPTY, EMPTY, BOS)
        from_truncated = replay(odds, truncated, EMPTY, EMPTY, EMPTY, BOS)

        assert from_full and from_truncated
        assert from_full[0]["projection"] == from_truncated[0]["projection"], (
            "the replay saw games played after the date it was projecting"
        )

    def test_the_same_holds_for_total_bases(self):
        before = ["2026-08-0%d" % d for d in range(1, 9)] + ["2026-08-1%d" % d for d in range(0, 5)]
        after = ["2026-08-2%d" % d for d in range(6, 9)]

        quiet = _batting(before)
        loud = _batting(after)
        loud["h"], loud["hr"] = 4, 3          # a monstrous future
        full = pd.concat([quiet, loud], ignore_index=True)

        odds = _odds(game_date="2026-08-20", market="batter_total_bases",
                     player="Test Hitter", line=1.5)

        from_full = replay(odds, EMPTY, full, EMPTY, EMPTY, BOS)
        from_truncated = replay(odds, EMPTY, quiet, EMPTY, EMPTY, BOS)

        assert from_full and from_truncated
        assert from_full[0]["projection"] == from_truncated[0]["projection"]

    def test_a_date_with_no_prior_games_produces_nothing(self):
        """Opening day has no history to project from; it must not invent one."""
        odds = _odds(game_date="2026-03-26")
        assert replay(odds, _pitching(["2026-08-02"]), EMPTY, EMPTY, EMPTY, BOS) == []


class TestGameDateResolution:
    @pytest.mark.parametrize("utc,expected", [
        ("2026-08-20T23:10:00Z", "2026-08-20"),   # 19:10 ET, same day
        ("2026-08-21T02:40:00Z", "2026-08-20"),   # 22:40 ET, previous day
        ("2026-08-20T17:35:00Z", "2026-08-20"),   # 13:35 ET afternoon
    ])
    def test_utc_first_pitch_maps_to_the_eastern_game_date(self, utc, expected):
        """
        A late game crossing UTC midnight still belongs to the previous
        Eastern date, which is what the games cache keys on.
        """
        assert game_date_of(utc) == expected

    def test_a_missing_or_unparseable_time_yields_nothing(self):
        assert game_date_of(None) is None
        assert game_date_of("") is None
        assert game_date_of("not a timestamp") is None


class TestOpponentResolution:
    def test_picks_the_other_team(self):
        row = pd.Series({"home_team": "Boston Red Sox", "away_team": "San Francisco Giants"})
        assert opponent_id_of(row, BOS) == SF

    def test_works_when_we_are_the_away_side(self):
        row = pd.Series({"home_team": "San Francisco Giants", "away_team": "Boston Red Sox"})
        assert opponent_id_of(row, BOS) == SF

    def test_an_unknown_team_name_yields_none_rather_than_a_wrong_id(self):
        row = pd.Series({"home_team": "Boston Red Sox", "away_team": "Some Other Club"})
        assert opponent_id_of(row, BOS) is None


class TestReplayedRowsAreLabelled:
    def _row(self):
        rows = replay(_odds(), _pitching(["2026-08-02", "2026-08-08", "2026-08-14"]),
                      EMPTY, EMPTY, EMPTY, BOS)
        assert rows
        return rows[0]

    def test_carry_a_replay_suffix(self):
        """A reconstruction must never be mistaken for what was published."""
        assert self._row()["model_version"].endswith("-replay")

    def test_carry_the_capture_time_they_were_rebuilt_for(self):
        assert self._row()["captured_at"] == "2026-08-20T15:00:00+00:00"

    def test_carry_the_line_that_was_on_the_board_then(self):
        assert self._row()["line"] == 4.5

    def test_start_ungraded(self):
        row = self._row()
        assert row["outcome"] == ""
        assert pd.isna(row["actual"])


class TestMarketFiltering:
    def test_moneylines_are_not_replayed(self):
        """h2h has no player projection to reconstruct."""
        odds = _odds(market="h2h", player="Boston Red Sox", line=float("nan"))
        assert replay(odds, _pitching(["2026-08-02", "2026-08-08", "2026-08-14"]),
                      EMPTY, EMPTY, EMPTY, BOS) == []

    def test_a_capture_with_no_usable_line_is_skipped(self):
        odds = _odds(line=float("nan"))
        assert replay(odds, _pitching(["2026-08-02", "2026-08-08", "2026-08-14"]),
                      EMPTY, EMPTY, EMPTY, BOS) == []

    def test_since_filters_by_game_date(self):
        pitching = _pitching(["2026-08-02", "2026-08-08", "2026-08-14"])
        odds = _odds(game_date="2026-08-20")
        assert replay(odds, pitching, EMPTY, EMPTY, EMPTY, BOS, since="2026-08-25") == []
        assert replay(odds, pitching, EMPTY, EMPTY, EMPTY, BOS, since="2026-08-01")
