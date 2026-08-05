"""
Cache staleness, and the silent wrong answer it produced.

Both league-wide loaders were written as "if the file exists, return it", with
no notion of age. On 2026-08-02 the opponent K factor was found to have been
computing from team hitting logs last written 2026-07-27 - six days and roughly
ninety games out of date. Nothing failed. The page built, the factor looked
plausible, and it was simply wrong.

Two properties matter here and they pull against each other: a stale cache must
be refreshed, and a failed refresh must never take a page down. So the rule is
refetch when old, fall back to what is on disk when that fails, and say so in
the log either way.
"""

from __future__ import annotations

import time
from pathlib import Path

import pandas as pd
import pytest

from data import cache_freshness, league_pitching, opponent


class FakeClock:
    """A cache file whose mtime can be set to any age."""

    def __init__(self, path: Path):
        self.path = path

    def age(self, hours: float) -> None:
        old = time.time() - hours * 3600
        import os
        os.utime(self.path, (old, old))


@pytest.fixture
def cached(tmp_path, monkeypatch):
    """A populated hitting-log cache, plus a handle to age it."""
    path = tmp_path / "team_hitting_logs_2026.parquet"
    frame = pd.DataFrame([
        {"team_id": 1, "team_name": "T1", "game_date": "2026-04-01",
         "pa": 100, "so": 25},
    ])
    frame.to_parquet(path, index=False)
    monkeypatch.setattr(opponent, "cache_path", lambda season: path)
    return FakeClock(path)


class FakeClient:
    """Returns a distinguishable frame, or raises."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0

    def refreshed(self) -> pd.DataFrame:
        return pd.DataFrame([
            {"team_id": 1, "team_name": "T1", "game_date": "2026-08-01",
             "pa": 200, "so": 50},
        ])


class TestStaleness:
    def test_a_fresh_cache_is_read_without_refetching(self, cached, monkeypatch):
        cached.age(1)
        called = []
        monkeypatch.setattr(opponent, "fetch_team_hitting_logs",
                            lambda c, s: called.append(1) or pd.DataFrame())

        frame = opponent.load_team_hitting_logs(2026, client=FakeClient())

        assert not called
        assert frame.iloc[0]["game_date"] == "2026-04-01"

    def test_a_stale_cache_is_refetched(self, cached, monkeypatch):
        """The bug: this used to return the April row forever."""
        cached.age(48)
        client = FakeClient()
        monkeypatch.setattr(opponent, "fetch_team_hitting_logs",
                            lambda c, s: client.refreshed())

        frame = opponent.load_team_hitting_logs(2026, client=client)

        assert frame.iloc[0]["game_date"] == "2026-08-01"

    def test_a_failed_refresh_falls_back_to_the_stale_copy(self, cached,
                                                           monkeypatch):
        """
        A page must still build. Returning an empty frame here would silently
        drop the opponent adjustment altogether, which is worse than using
        slightly old logs.
        """
        cached.age(48)

        def boom(client, season):
            raise RuntimeError("MLB API down")

        monkeypatch.setattr(opponent, "fetch_team_hitting_logs", boom)

        frame = opponent.load_team_hitting_logs(2026, client=FakeClient())

        assert len(frame) == 1
        assert frame.iloc[0]["game_date"] == "2026-04-01"

    def test_max_age_zero_disables_the_check(self, cached, monkeypatch):
        """What a backtest of a finished season needs: never refetch."""
        cached.age(24 * 365)
        called = []
        monkeypatch.setattr(opponent, "fetch_team_hitting_logs",
                            lambda c, s: called.append(1) or pd.DataFrame())

        opponent.load_team_hitting_logs(2026, client=FakeClient(), max_age_hours=0)

        assert not called

    def test_no_client_still_returns_the_stale_cache(self, cached):
        """Offline, old data beats no data - the tests themselves rely on it."""
        cached.age(48)

        frame = opponent.load_team_hitting_logs(2026, client=None)

        assert len(frame) == 1


class TestIsStale:
    def test_a_missing_file_is_stale(self, tmp_path):
        assert cache_freshness.is_stale(tmp_path / "nope.parquet")

    def test_zero_max_age_never_reports_stale(self, tmp_path):
        assert not cache_freshness.is_stale(tmp_path / "nope.parquet",
                                            max_age_hours=0)


class TestLeagueRateIsDateBounded:
    """
    The same leakage rule the opponent factor follows. The league rate a start
    is regressed toward must come only from games before it - a rate that
    includes the game being projected lets the model see its own future and
    makes the measured error bar optimistic.
    """

    LOGS = pd.DataFrame([
        {"player_id": 1, "game_date": "2026-04-01", "ip_outs": 27, "so": 9,
         "is_start": True},
        {"player_id": 2, "game_date": "2026-09-01", "ip_outs": 27, "so": 27,
         "is_start": True},
    ])

    def test_later_games_are_excluded(self):
        early = league_pitching.league_k_per_9(self.LOGS, before="2026-05-01")
        assert early == pytest.approx(9.0)

    def test_without_a_bound_every_game_counts(self):
        both = league_pitching.league_k_per_9(self.LOGS)
        assert both == pytest.approx(18.0)

    def test_relief_appearances_do_not_set_the_starter_rate(self):
        frame = pd.concat([
            self.LOGS.head(1),
            pd.DataFrame([{"player_id": 3, "game_date": "2026-04-01",
                           "ip_outs": 3, "so": 3, "is_start": False}]),
        ])
        assert league_pitching.league_k_per_9(frame) == pytest.approx(9.0)
