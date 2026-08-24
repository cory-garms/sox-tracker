"""
Propped hitters, cross-checked against the posted batting order.

Nick Kurtz carried a live +117 total-bases prop on 2026-07-27 while not in the
posted lineup, and nothing on the page flagged it. A prop on a hitter who never
bats is voided by the book rather than lost, but the projection printed beside
it describes nobody.

The trap in fixing it is the opposite error. MLB posts a lineup roughly 2-4
hours before first pitch, so three of the four daily builds run with no lineup
at all. Treating "not announced yet" as "not starting" would flag the whole
board every morning -- louder than the bug it replaces, and it would train the
reader to ignore the badge by the time it carries information. Hence three
states rather than a boolean.
"""

from __future__ import annotations

from analysis.matchup import (
    LINEUP_IN,
    LINEUP_OUT,
    LINEUP_UNPOSTED,
    _parse_single_preview,
    lineup_status,
)

BOS = 111


def _raw_game(home_ids=None, away_ids=None, is_home=True, game_pk=1):
    """A schedule payload shaped like the one get_game_previews() hydrates."""
    lineups = {}
    if home_ids is not None:
        lineups["homePlayers"] = [{"id": i} for i in home_ids]
    if away_ids is not None:
        lineups["awayPlayers"] = [{"id": i} for i in away_ids]
    bos = {"team": {"id": BOS}}
    opp = {"team": {"id": 147}}
    return {
        "gamePk": game_pk,
        "officialDate": "2026-08-24",
        "teams": {"home": bos if is_home else opp, "away": opp if is_home else bos},
        "lineups": lineups,
        "status": {},
    }


class TestLineupIsCarriedThroughTheParser:
    def test_home_side_is_ours_when_we_are_home(self):
        p = _parse_single_preview(_raw_game(home_ids=[1, 2], away_ids=[9]), BOS, "2026-08-24")
        assert p["our_lineup_ids"] == {1, 2}
        assert p["opp_lineup_ids"] == {9}
        assert p["lineup_posted"] is True

    def test_away_side_is_ours_when_we_are_away(self):
        """The sides swap, and getting this backwards would flag every starter."""
        p = _parse_single_preview(
            _raw_game(home_ids=[9], away_ids=[1, 2], is_home=False), BOS, "2026-08-24"
        )
        assert p["our_lineup_ids"] == {1, 2}
        assert p["opp_lineup_ids"] == {9}

    def test_no_lineup_block_is_not_an_empty_lineup(self):
        p = _parse_single_preview(_raw_game(), BOS, "2026-08-24")
        assert p["lineup_posted"] is False
        assert p["our_lineup_ids"] == set()

    def test_players_without_ids_are_dropped_not_crashed_on(self):
        raw = _raw_game(home_ids=[1])
        raw["lineups"]["homePlayers"].append({"fullName": "No Id"})
        p = _parse_single_preview(raw, BOS, "2026-08-24")
        assert p["our_lineup_ids"] == {1}


class TestUnpostedIsNotAbsent:
    """The regression that would make this feature worse than the bug."""

    def test_no_lineup_posted_yields_unposted_not_out(self):
        previews = [_parse_single_preview(_raw_game(), BOS, "2026-08-24")]
        assert lineup_status(previews, 1) == LINEUP_UNPOSTED

    def test_no_previews_at_all_yields_unposted(self):
        assert lineup_status([], 1) == LINEUP_UNPOSTED

    def test_a_game_with_no_lineup_does_not_veto_one_that_has_it(self):
        """Doubleheader where only game one is posted: game one still decides."""
        previews = [
            _parse_single_preview(_raw_game(home_ids=[1, 2], game_pk=1), BOS, "2026-08-24"),
            _parse_single_preview(_raw_game(game_pk=2), BOS, "2026-08-24"),
        ]
        assert lineup_status(previews, 1) == LINEUP_IN
        assert lineup_status(previews, 3) == LINEUP_OUT


class TestStartingAndBenched:
    def test_player_in_the_order_is_in(self):
        previews = [_parse_single_preview(_raw_game(home_ids=[1, 2, 3]), BOS, "2026-08-24")]
        assert lineup_status(previews, 2) == LINEUP_IN

    def test_player_absent_from_a_posted_order_is_out(self):
        previews = [_parse_single_preview(_raw_game(home_ids=[1, 2, 3]), BOS, "2026-08-24")]
        assert lineup_status(previews, 77) == LINEUP_OUT

    def test_the_opposing_lineup_does_not_count_as_starting(self):
        """Matching against the wrong side would silently pass every prop."""
        previews = [
            _parse_single_preview(_raw_game(home_ids=[1], away_ids=[77]), BOS, "2026-08-24")
        ]
        assert lineup_status(previews, 77) == LINEUP_OUT

    def test_rested_in_game_one_but_starting_the_nightcap_is_starting(self):
        previews = [
            _parse_single_preview(_raw_game(home_ids=[1, 2], game_pk=1), BOS, "2026-08-24"),
            _parse_single_preview(_raw_game(home_ids=[3, 4], game_pk=2), BOS, "2026-08-24"),
        ]
        assert lineup_status(previews, 4) == LINEUP_IN
        assert lineup_status(previews, 9) == LINEUP_OUT

    def test_ids_compare_across_string_and_int(self):
        """The odds path and the batting frame do not agree on the type."""
        previews = [_parse_single_preview(_raw_game(home_ids=[1]), BOS, "2026-08-24")]
        assert lineup_status(previews, "1") == LINEUP_IN

    def test_a_missing_player_id_is_unposted_rather_than_out(self):
        previews = [_parse_single_preview(_raw_game(home_ids=[1]), BOS, "2026-08-24")]
        assert lineup_status(previews, None) == LINEUP_UNPOSTED


class TestWhatThePageSays:
    """
    The badge and the note. Silence is only correct for one of the three
    states, and the note exists so the reader can tell "checked, all fine"
    apart from "could not check yet".
    """

    @staticmethod
    def _tb(states, has_line=None):
        import pandas as pd
        n = len(states)
        has_line = [True] * n if has_line is None else has_line
        return pd.DataFrame({
            "player_id": list(range(1, n + 1)),
            "player_name": [f"Hitter {i}" for i in range(1, n + 1)],
            "has_line": has_line,
            "lineup_state": states,
        })

    def test_only_a_propped_absent_hitter_renders_a_badge(self):
        from betting_report import _lineup_badge
        assert _lineup_badge({"lineup_state": LINEUP_OUT, "has_line": True})
        assert _lineup_badge({"lineup_state": LINEUP_IN, "has_line": True}) == ""
        assert _lineup_badge({"lineup_state": LINEUP_UNPOSTED, "has_line": True}) == ""

    def test_an_unpropped_bench_bat_is_not_badged(self):
        """
        These tables rank the top ten by projection across the roster, so four
        or five bench bats sit in them every night. Badging those lights up half
        the table daily and teaches the reader to skip the badge before it ever
        means anything. Only a live price on a non-starter is the defect.
        """
        from betting_report import _lineup_badge
        assert _lineup_badge({"lineup_state": LINEUP_OUT, "has_line": False}) == ""

    def test_benched_propped_hitter_is_named(self):
        import pandas as pd
        from betting_report import _lineup_note
        tb = self._tb([LINEUP_IN, LINEUP_OUT])
        note = _lineup_note(tb, [_parse_single_preview(
            _raw_game(home_ids=[1]), BOS, "2026-08-24")])
        assert "Hitter 2" in note
        assert "Hitter 1" not in note

    def test_a_benched_hitter_with_no_line_is_not_named(self):
        """No line means no position to void; flagging it is noise."""
        import pandas as pd
        from betting_report import _lineup_note
        tb = self._tb([LINEUP_OUT], has_line=[False])
        note = _lineup_note(tb, [_parse_single_preview(
            _raw_game(home_ids=[9]), BOS, "2026-08-24")])
        assert note == ""

    def test_unposted_says_so_rather_than_claiming_all_clear(self):
        import pandas as pd
        from betting_report import _lineup_note
        tb = self._tb([LINEUP_UNPOSTED, LINEUP_UNPOSTED])
        note = _lineup_note(tb, [_parse_single_preview(
            _raw_game(), BOS, "2026-08-24")])
        assert "not posted" in note.lower()
        assert "Hitter" not in note

    def test_all_clear_is_stated_explicitly(self):
        import pandas as pd
        from betting_report import _lineup_note
        tb = self._tb([LINEUP_IN, LINEUP_IN])
        note = _lineup_note(tb, [_parse_single_preview(
            _raw_game(home_ids=[1, 2]), BOS, "2026-08-24")])
        assert "Every propped hitter" in note

    def test_no_propped_hitters_says_nothing(self):
        import pandas as pd
        from betting_report import _lineup_note
        assert _lineup_note(pd.DataFrame(), []) == ""
