"""
The doubleheader board.

A prop is per game. The board was one event end to end -- one lookup, one set
of lines, one movement history, one position -- so on a doubleheader date it
could only ever be about one of the two games, and silently: nothing on the
page said the other existed.

2026-08-29 at Yankee Stadium is the first one this project has to render, games
at 17:05Z and 23:15Z. What these pin down:

1. **Cost.** Two games is two purchases, and the only thing keeping that inside
   a 500-credit cycle is refusing to buy a game already under way. That refusal
   is a correctness property as much as a budget one: by then the book is
   quoting the game in play, which is a different market from the one these
   models project.
2. **The single-game day cannot regress.** 95% of dates have one game, and a
   doubleheader feature that changed what those dates buy or show would be a
   bad trade at any price.
3. **The two boards must not blur into each other** on a phone, which is where
   this is read.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from analysis.betting import MARKET_H2H, MARKET_K, MARKET_TB, find_team_events
from betting_report import (
    _dh_strip,
    _extra_game_board,
    _game_heading,
    _game_subtitle,
    _has_started,
    _price_the_day,
)

G1 = {"id": "evt-g1", "commence_time": "2026-08-29T17:05:00Z",
      "home_team": "New York Yankees", "away_team": "Boston Red Sox"}
G2 = {"id": "evt-g2", "commence_time": "2026-08-29T23:15:00Z",
      "home_team": "New York Yankees", "away_team": "Boston Red Sox"}
OTHER = {"id": "evt-x", "commence_time": "2026-08-29T23:11:00Z",
         "home_team": "New York Mets", "away_team": "Milwaukee Brewers"}
NEXT_DAY = {"id": "evt-sun", "commence_time": "2026-08-30T17:35:00Z",
            "home_team": "New York Yankees", "away_team": "Boston Red Sox"}


class FakeOddsClient:
    """Counts what it would have been billed for."""

    configured = True
    bookmaker = "draftkings"

    def __init__(self, events):
        self._events = events
        self.event_lookups = 0
        self.priced_event_ids: list[str] = []

    def get_events(self):
        self.event_lookups += 1          # free, per the provider's docs
        return list(self._events)

    def find_event(self, team_name, events=None, upcoming_only=False, now=None):
        pool = events if events is not None else self._events
        for ev in pool:
            if "Red Sox" in ev["home_team"] or "Red Sox" in ev["away_team"]:
                return ev
        return None

    def get_event_props(self, event_id, markets=MARKET_K, **kwargs):
        self.priced_event_ids.append(event_id)   # one credit each
        return {}

    @property
    def credits_spent(self):
        return len(self.priced_event_ids)


class TestFindingTheDaysGames:
    def test_a_doubleheader_is_two_events_in_schedule_order(self):
        client = FakeOddsClient([G2, G1, OTHER])       # provider order not assumed
        found = find_team_events(client, "Boston Red Sox", "2026-08-29")
        assert [e["id"] for e in found] == ["evt-g1", "evt-g2"]

    def test_other_teams_games_are_not_ours(self):
        client = FakeOddsClient([G1, OTHER])
        assert [e["id"] for e in find_team_events(client, "Boston Red Sox")] == ["evt-g1"]

    def test_another_date_is_a_different_day(self):
        client = FakeOddsClient([G1, G2, NEXT_DAY])
        found = find_team_events(client, "Boston Red Sox", "2026-08-29")
        assert [e["id"] for e in found] == ["evt-g1", "evt-g2"]

    def test_discovering_the_doubleheader_costs_nothing(self):
        """The whole design rests on this: get_events() is free."""
        client = FakeOddsClient([G1, G2])
        find_team_events(client, "Boston Red Sox", "2026-08-29")
        assert client.credits_spent == 0

    def test_an_unconfigured_client_yields_no_games_rather_than_raising(self):
        class NoKey:
            configured = False
        assert find_team_events(NoKey(), "Boston Red Sox") == []


class TestWhatTheDayCosts:
    """Three credits a game, and only for a game that has not started."""

    BEFORE_BOTH = datetime(2026, 8, 29, 15, 0, tzinfo=timezone.utc)
    BETWEEN = datetime(2026, 8, 29, 19, 0, tzinfo=timezone.utc)   # the 15:00 ET build

    def test_both_games_are_priced_while_both_are_ahead(self, monkeypatch):
        client = FakeOddsClient([G1, G2])
        monkeypatch.setattr("betting_report._has_started",
                            lambda ev, now=None: False)
        book, extras = _price_the_day(client, 111, [G1, G2])
        assert book["event"]["id"] == "evt-g1"
        assert [ev["id"] for ev, _ in extras] == ["evt-g2"]
        assert set(client.priced_event_ids) == {"evt-g1", "evt-g2"}

    def test_a_game_under_way_is_not_bought(self, monkeypatch):
        """The 15:00 ET build: game 1 is on, and buying it would be in-play."""
        monkeypatch.setattr("betting_report._has_started",
                            lambda ev, now=None: ev["id"] == "evt-g1")
        client = FakeOddsClient([G1, G2])
        book, extras = _price_the_day(client, 111, [G1, G2])
        assert "evt-g1" not in client.priced_event_ids
        assert "evt-g2" in client.priced_event_ids

    def test_the_primary_board_is_the_game_still_to_come(self, monkeypatch):
        monkeypatch.setattr("betting_report._has_started",
                            lambda ev, now=None: ev["id"] == "evt-g1")
        book, extras = _price_the_day(FakeOddsClient([G1, G2]), 111, [G1, G2])
        assert book["event"]["id"] == "evt-g2"
        assert [ev["id"] for ev, _ in extras] == ["evt-g1"]

    def test_the_started_game_carries_no_lines_to_render(self, monkeypatch):
        monkeypatch.setattr("betting_report._has_started",
                            lambda ev, now=None: ev["id"] == "evt-g1")
        _, extras = _price_the_day(FakeOddsClient([G1, G2]), 111, [G1, G2])
        _, book_g1 = extras[0]
        assert book_g1[MARKET_K] == {}
        assert book_g1[MARKET_TB] == {}
        assert book_g1[MARKET_H2H] == {}


class TestTheSingleGameDayIsUnchanged:
    """
    The property that makes the rest of this safe to ship mid-season.

    On one game, no games, or an unreachable provider, _price_the_day must make
    the same call the page has always made and return no extras -- so a
    doubleheader feature cannot alter what a normal Tuesday buys or shows.
    """

    def test_one_game_prices_exactly_that_game_and_nothing_else(self):
        client = FakeOddsClient([G1])
        book, extras = _price_the_day(client, 111, [G1])
        assert extras == []
        assert book["event"]["id"] == "evt-g1"

    def test_one_game_goes_through_the_unchanged_lookup(self, monkeypatch):
        """No event argument, which is what the old call site did."""
        seen = {}

        def fake_fetch(client, team_id=111, event=None):
            seen["event_arg"] = event
            return {"event": G1, MARKET_K: {}, MARKET_TB: {}}

        monkeypatch.setattr("betting_report.fetch_book_lines", fake_fetch)
        _price_the_day(FakeOddsClient([G1]), 111, [G1])
        assert seen["event_arg"] is None

    def test_no_events_at_all_still_returns_a_usable_shape(self):
        book, extras = _price_the_day(FakeOddsClient([]), 111, [])
        assert extras == []
        assert "event" in book

    def test_a_single_game_renders_no_doubleheader_strip(self):
        assert _dh_strip([{"label": "Game 1", "time": "7:15 PM ET",
                           "state": "next", "detail": ""}]) == ""
        assert _dh_strip([]) == ""


class TestTheClock:
    def test_before_first_pitch_has_not_started(self):
        assert _has_started(G2, now=datetime(2026, 8, 29, 22, 0, tzinfo=timezone.utc)) is False

    def test_after_first_pitch_has(self):
        assert _has_started(G1, now=datetime(2026, 8, 29, 19, 0, tzinfo=timezone.utc)) is True

    def test_a_missing_time_is_treated_as_upcoming(self):
        """
        Degrades to the old behaviour -- the game gets priced -- rather than
        dropping a game off the board over a bad field.
        """
        assert _has_started({"id": "x"}) is False
        assert _has_started({"id": "x", "commence_time": "not-a-date"}) is False


class TestWhatTheReaderSees:
    def test_the_strip_lists_both_games_in_order(self):
        html = _dh_strip([
            {"label": "Game 1", "time": "1:05 PM ET", "state": "done", "detail": "Final"},
            {"label": "Game 2", "time": "7:15 PM ET", "state": "next", "detail": "priced below"},
        ])
        assert html.index("Game 1") < html.index("Game 2")
        assert "1:05 PM ET" in html and "7:15 PM ET" in html

    def test_each_board_is_labelled_with_the_game_it_is_about(self):
        head = _game_heading("Game 2", "7:15 PM ET &middot; at NYY")
        assert "Game 2" in head and "7:15 PM ET" in head

    def test_a_subtitle_tells_the_two_ends_apart(self):
        preview = {"game_time_utc": "2026-08-29T17:05:00Z", "opponent_abbr": "NYY",
                   "is_home": False, "our_probable": {"name": "Jake Bennett"},
                   "status": "Scheduled", "start_time_tbd": False}
        sub = _game_subtitle(preview, G1)
        assert "NYY" in sub and "Bennett" in sub

    def test_the_game_under_way_says_why_it_has_no_prices(self):
        """Silence there reads as a broken page, not as a deliberate refusal."""
        html = _extra_game_board(
            event=G1, book={"event": G1, MARKET_K: {}, MARKET_TB: {}, MARKET_H2H: {}},
            preview={}, label="Game 1", history=None, batting=None, pitching=None,
            games=None, client=None, team_id=111, season=2026,
            date_str="2026-08-29", opp_logs=None, league_k9=None,
        )
        assert "Game 1" in html
        assert "not re-priced" in html
        assert "in play" in html.lower()


class TestTheAssembledPage:
    """
    The whole board for 2026-08-29, put together the way the build will.

    The helpers above are individually right; this is the assembly that has to
    hold them in the right order with the right labels, and it is the part that
    only ever runs on a doubleheader date -- so without this it would first run
    in production, on Saturday.
    """

    PREVIEW_G1 = {"game_pk": 823539, "game_time_utc": "2026-08-29T17:05:00Z",
                  "game_number": 1, "opponent_abbr": "NYY", "is_home": False,
                  "our_probable": {"id": 701, "name": "Jake Bennett"},
                  "opp_probable": {"id": 801, "name": "TBD"},
                  "status": "Final", "start_time_tbd": False}
    PREVIEW_G2 = {"game_pk": 823501, "game_time_utc": "2026-08-29T23:15:00Z",
                  "game_number": 2, "opponent_abbr": "NYY", "is_home": False,
                  "our_probable": {"id": 702, "name": "Second Starter"},
                  "opp_probable": {"id": 802, "name": "TBD"},
                  "status": "Scheduled", "start_time_tbd": False}

    def build(self, monkeypatch, primary, extras, started_ids=()):
        monkeypatch.setattr("betting_report._has_started",
                            lambda ev, now=None: ev["id"] in started_ids)
        # The extra game's own board is exercised by its own tests; here the
        # question is order and labelling, so it is stubbed to something
        # identifiable.
        monkeypatch.setattr(
            "betting_report._extra_game_board",
            lambda **kw: f"<!--EXTRA {kw['event']['id']} as {kw['label']}-->",
        )
        from betting_report import _doubleheader_sections
        return _doubleheader_sections(
            primary_event=primary,
            primary_book={"event": primary, MARKET_K: {}, MARKET_TB: {}},
            primary_cards="<!--PRIMARY CARDS-->",
            extra_books=extras,
            previews=[self.PREVIEW_G1, self.PREVIEW_G2],
            history=None, batting=None, pitching=None, games=None, client=None,
            team_id=111, season=2026, date_str="2026-08-29",
            opp_logs=None, league_k9=None,
        )

    def test_the_opener_is_rendered_above_the_nightcap(self, monkeypatch):
        """Even when the nightcap is the game being priced."""
        html = self.build(monkeypatch, G2, [(G1, {"event": G1})],
                          started_ids={"evt-g1"})
        assert html.index("EXTRA evt-g1") < html.index("PRIMARY CARDS")

    def test_each_game_is_numbered_by_schedule_position(self, monkeypatch):
        html = self.build(monkeypatch, G2, [(G1, {"event": G1})],
                          started_ids={"evt-g1"})
        assert "EXTRA evt-g1 as Game 1" in html
        assert "Game 2" in html

    def test_the_morning_build_prices_the_opener_first(self, monkeypatch):
        """Before either game: the opener is primary and still comes first."""
        html = self.build(monkeypatch, G1, [(G2, {"event": G2})])
        assert html.index("PRIMARY CARDS") < html.index("EXTRA evt-g2")
        assert "EXTRA evt-g2 as Game 2" in html

    def test_the_strip_opens_the_page(self, monkeypatch):
        html = self.build(monkeypatch, G1, [(G2, {"event": G2})])
        assert html.index("Doubleheader") < html.index("PRIMARY CARDS")

    def test_a_finished_opener_is_marked_done_not_priced(self, monkeypatch):
        html = self.build(monkeypatch, G2, [(G1, {"event": G1})],
                          started_ids={"evt-g1"})
        strip = html[:html.index("EXTRA")]
        assert "dh-strip-row done" in strip
        assert "Final" in strip

    def test_the_preview_is_matched_by_first_pitch_not_by_position(self, monkeypatch):
        """
        The provider is not obliged to list a doubleheader in MLB's order, and
        pairing by index would put game 1's starter under game 2's board.
        """
        from betting_report import _preview_for_event
        assert _preview_for_event(G2, [self.PREVIEW_G1, self.PREVIEW_G2]) is self.PREVIEW_G2
        assert _preview_for_event(G1, [self.PREVIEW_G2, self.PREVIEW_G1]) is self.PREVIEW_G1

    def test_a_two_word_state_is_one_css_class(self, monkeypatch):
        """'in play' dropped into the attribute as written is two classes."""
        head = _game_heading("Game 1", "1:05 PM ET", "in play")
        assert 'class="dh-state in-play"' in head
        assert "IN PLAY" in head


class TestTheBoardIsAboutOneGame:
    """
    probable_starters answers for a date. A doubleheader has two.

    Harmless while the primary board was always the opener. The moment the
    opener started — 2026-08-29, 17:06Z — game 2 became primary and inherited
    game 1's starter, so the nightcap's event logged a projection for a pitcher
    who had already thrown that afternoon. Caught by reading the log and seeing
    Bennett and Rodón, game 1's pair, filed under game 2's event.

    Grading would not have saved it either: it would have gone looking for
    Bennett in a game he never appeared in and settled him DNP.
    """

    PV1 = {"game_number": 1, "game_time_utc": "2026-08-29T17:05:00Z",
           "our_probable": {"id": 701, "name": "Jake Bennett"},
           "opp_probable": {"id": 801, "name": "Carlos Rodón"}}
    PV2 = {"game_number": 2, "game_time_utc": "2026-08-29T23:15:00Z",
           "our_probable": {"id": None, "name": "TBD"},
           "opp_probable": {"id": 802, "name": "Max Fried"}}

    def test_the_opener_board_takes_the_openers_pair(self):
        from betting_report import _preview_for_event
        pv = _preview_for_event(G1, [self.PV1, self.PV2])
        assert pv["our_probable"]["name"] == "Jake Bennett"
        assert pv["opp_probable"]["name"] == "Carlos Rodón"

    def test_the_nightcap_board_takes_the_nightcaps_pair(self):
        from betting_report import _preview_for_event
        pv = _preview_for_event(G2, [self.PV1, self.PV2])
        assert pv["opp_probable"]["name"] == "Max Fried"

    def test_an_unnamed_starter_yields_nobody_not_the_other_game_s(self):
        """
        The nightcap's starter is unannounced. The honest answer is an empty
        table the page explains, never the pitcher from the game before it.
        """
        from betting_report import _preview_for_event
        pv = _preview_for_event(G2, [self.PV1, self.PV2])
        mine = pv.get("our_probable") or {}
        probables = [mine] if mine.get("id") else []
        assert probables == []
        assert {p["id"] for p in probables} == set()
