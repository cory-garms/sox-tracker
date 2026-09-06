"""
The all-time saves cache.

The regression this guards is the one the notebook exists to prevent: a post
that asserts "he would be the ninth man to 400" and is wrong the next morning
because somebody else got there. The club is counted from fetched data every
build, so the only way it goes stale is if this module quietly serves an old
file, which is what the staleness path below is for.
"""

from __future__ import annotations

import pandas as pd
import pytest

from data import career_saves as cs


class _Client:
    """Returns one canned /stats/leaders payload and counts the calls."""

    def __init__(self, payload=None, boom=False):
        self.payload = payload if payload is not None else _payload()
        self.boom = boom
        self.calls = 0

    def _get(self, path, params=None):
        self.calls += 1
        if self.boom:
            raise RuntimeError("provider down")
        return self.payload


def _payload(rows=((1, 1, "Mariano Rivera", 652), (2, 2, "Trevor Hoffman", 601),
                   (3, 3, "Aroldis Chapman", 399), (4, 4, "Joe Nathan", 377))):
    return {"leagueLeaders": [{"leaderCategory": "saves", "leaders": [
        {"rank": r, "person": {"id": i, "fullName": n}, "value": v}
        for r, i, n, v in rows]}]}


class TestFetch:
    def test_parses_the_leaderboard(self):
        frame = cs.fetch_leaders(_Client())
        assert list(frame.columns) == cs.COLUMNS
        assert frame.iloc[0]["player_name"] == "Mariano Rivera"
        assert frame.iloc[0]["saves"] == 652

    def test_orders_by_saves_regardless_of_the_ranks_given(self):
        """Rank is the provider's; the ordering this file promises is its own."""
        shuffled = _payload(((9, 3, "Aroldis Chapman", 399),
                             (1, 1, "Mariano Rivera", 652)))
        frame = cs.fetch_leaders(_Client(shuffled))
        assert list(frame["saves"]) == [652, 399]

    def test_a_row_with_an_unreadable_value_is_dropped_not_zeroed(self):
        """A None save total must not become a 0-save leader."""
        bad = {"leagueLeaders": [{"leaders": [
            {"rank": 1, "person": {"id": 1, "fullName": "A"}, "value": None},
            {"rank": 2, "person": {"id": 2, "fullName": "B"}, "value": 400}]}]}
        frame = cs.fetch_leaders(_Client(bad))
        assert list(frame["player_name"]) == ["B"]

    def test_an_empty_payload_is_an_empty_frame_with_columns(self):
        frame = cs.fetch_leaders(_Client({"leagueLeaders": []}))
        assert frame.empty
        assert list(frame.columns) == cs.COLUMNS


class TestLoadAndStaleness:
    def test_a_fresh_cache_is_not_refetched(self, tmp_path, monkeypatch):
        path = tmp_path / "s.parquet"
        monkeypatch.setattr(cs, "cache_path", lambda: path)
        client = _Client()
        cs.load_leaders(client=client)
        assert client.calls == 1
        cs.load_leaders(client=client)
        assert client.calls == 1, "refetched a cache that was still fresh"

    def test_a_stale_cache_is_refetched(self, tmp_path, monkeypatch):
        path = tmp_path / "s.parquet"
        monkeypatch.setattr(cs, "cache_path", lambda: path)
        client = _Client()
        cs.load_leaders(client=client)
        cs.load_leaders(client=client, max_age_hours=0.0000001)
        assert client.calls == 2

    def test_a_failed_refresh_serves_the_cached_copy(self, tmp_path, monkeypatch):
        """
        Loudly degraded, never fatal. A provider outage must not take the
        notebook page down with it.
        """
        path = tmp_path / "s.parquet"
        monkeypatch.setattr(cs, "cache_path", lambda: path)
        cs.load_leaders(client=_Client())
        out = cs.load_leaders(client=_Client(boom=True), max_age_hours=0.0000001)
        assert not out.empty
        assert out.iloc[0]["saves"] == 652

    def test_no_client_and_no_cache_is_empty_rather_than_an_exception(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cs, "cache_path", lambda: tmp_path / "nope.parquet")
        out = cs.load_leaders(client=None)
        assert out.empty
        assert list(out.columns) == cs.COLUMNS


class TestTheClubIsCountedNotListed:
    def test_counts_only_those_past_the_threshold(self):
        frame = cs.fetch_leaders(_Client())
        assert list(cs.club_at(frame, 400)["player_name"]) == [
            "Mariano Rivera", "Trevor Hoffman"]

    def test_the_club_grows_when_the_data_does(self):
        """
        The whole reason it is counted. Chapman at 400 makes the club three,
        with no edit to any post.
        """
        after = cs.fetch_leaders(_Client(_payload((
            (1, 1, "Mariano Rivera", 652), (2, 2, "Trevor Hoffman", 601),
            (3, 3, "Aroldis Chapman", 400)))))
        assert len(cs.club_at(after, 400)) == 3

    def test_an_empty_frame_has_an_empty_club(self):
        assert cs.club_at(pd.DataFrame(columns=cs.COLUMNS), 400).empty


class TestNextMilestone:
    @pytest.mark.parametrize("saves,expected", [
        (399, 400), (350, 400), (401, 450), (0, 50),
    ])
    def test_finds_the_next_round_number(self, saves, expected):
        assert cs.next_milestone(saves, 50) == expected

    def test_a_total_already_on_a_milestone_is_chasing_the_next_one(self):
        """
        400 saves has arrived at 400. A post that says "0 from 400" reads as a
        countdown that never ends.
        """
        assert cs.next_milestone(400, 50) == 450


class TestRateLeaders:
    """
    data/pitching_leaders.py. The trap here is qualification: MLB's rate boards
    hold only pitchers past one inning per team game, so a young starter on an
    innings limit is absent from a list he would place well inside. Reading that
    absence as "not good enough" is the error; rank_for exists so a post can say
    where a number *would* fall and then say plainly that it does not count.
    """

    def _frame(self):
        from data import pitching_leaders as pl
        return pd.DataFrame(
            [{"rank": i + 1, "player_id": i + 1, "player_name": f"P{i}",
              "value": v} for i, v in enumerate([6.34, 5.00, 4.10, 3.75, 1.55])]
        )[pl.COLUMNS]

    def test_finds_where_a_value_would_slot(self):
        from data import pitching_leaders as pl
        assert pl.rank_for(self._frame(), 3.97) == (4, 5)

    def test_a_value_better_than_the_field_leads_it(self):
        from data import pitching_leaders as pl
        assert pl.rank_for(self._frame(), 7.0)[0] == 1

    def test_a_value_below_the_field_is_last(self):
        from data import pitching_leaders as pl
        assert pl.rank_for(self._frame(), 1.0) == (6, 5)

    def test_an_empty_board_yields_no_claim_rather_than_first_place(self):
        """The failure this guards: ranking first against nothing at all."""
        from data import pitching_leaders as pl
        assert pl.rank_for(pd.DataFrame(), 3.97) == (0, 0)
        assert pl.rank_for(None, 3.97) == (0, 0)

    def test_the_board_is_ordered_by_value_not_the_given_rank(self):
        from data import pitching_leaders as pl

        class C:
            def _get(self, path, params=None):
                return {"leagueLeaders": [{"leaders": [
                    {"rank": 9, "person": {"id": 2, "fullName": "B"}, "value": 3.0},
                    {"rank": 1, "person": {"id": 1, "fullName": "A"}, "value": 6.0}]}]}

        assert list(pl.fetch_leaders(C(), 2026)["value"]) == [6.0, 3.0]


class TestNearestMilestone:
    """
    The bug this fixes shipped and was caught by the event it was written for.
    Chapman recorded his 400th save; next_milestone(400) is 450, so the post
    announced a man fifty short of a number nobody was discussing, on the
    evening he reached the one everybody was. Under a headline about the 400
    club.
    """

    @pytest.mark.parametrize("saves,expected", [
        (399, 400),     # one away: about 400
        (400, 400),     # the day he gets there: still about 400
        (401, 400),
        (424, 400),     # just under halfway: still the achievement
        (425, 400),     # the midpoint stays with the one he has
        (430, 450),     # past it: now he is chasing
        (449, 450),
        (450, 450),
    ])
    def test_tracks_the_number_the_total_is_about(self, saves, expected):
        from data import career_saves as cs
        assert cs.nearest_milestone(saves, 50) == expected

    def test_it_differs_from_next_exactly_where_it_should(self):
        from data import career_saves as cs
        assert cs.next_milestone(400, 50) == 450       # what he is chasing
        assert cs.nearest_milestone(400, 50) == 400    # what he just did

    def test_the_club_counts_him_once_he_is_in_it(self):
        from data import career_saves as cs
        board = pd.DataFrame([
            {"rank": 1, "player_id": 1, "player_name": "A", "saves": 652},
            {"rank": 2, "player_id": 2, "player_name": "B", "saves": 422},
            {"rank": 3, "player_id": 3, "player_name": "C", "saves": 400},
        ])
        target = cs.nearest_milestone(400, 50)
        assert len(cs.club_at(board, target)) == 3
