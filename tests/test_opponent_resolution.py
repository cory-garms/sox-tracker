"""
Which opponent tonight's projection is adjusted for.

The bug. `betting_report` read the opponent off the game preview as
`preview["opponent"]["id"]`, a nested dict that `_parse_single_preview` has
never produced - the key is `opponent_id`, flat. So the lookup returned None on
every build since it was written, and control fell through to the "no preview"
branch, which adjusts tonight's starter for the opponent of the *last game in
the games cache*.

That is invisible for as long as a series is in progress, because last night's
opponent is tonight's opponent. It is wrong on exactly the days that matter -
the first game of a new series - and it stayed hidden because the strikeout
model was too blunt to recommend anything eiher way. On 2026-08-05, the first
night it could recommend, it applied a Dodgers K rate (factor 0.933) to a White
Sox game (1.066) and produced an UNDER call at +18.2% EV that the correct
factor does not support.

Both tests here are about the same rule: the opponent must come from tonight's
schedule, and the fallback must be the last game genuinely *played*.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.matchup import _parse_single_preview
from analysis.streaks import played_in_order


def raw_game(home_id: int, away_id: int, game_pk: int = 1) -> dict:
    return {
        "gamePk": game_pk,
        "officialDate": "2026-08-05",
        "gameDate": "2026-08-05T23:10:00Z",
        "status": {"detailedState": "Scheduled"},
        "venue": {"name": "Fenway Park"},
        "teams": {
            "home": {"team": {"id": home_id}, "probablePitcher": {"id": 9, "fullName": "P"}},
            "away": {"team": {"id": away_id}, "probablePitcher": {"id": 8, "fullName": "Q"}},
        },
    }


class TestPreviewExposesOpponentFlat:
    """
    Pins the shape of the contract that was misread. If the preview ever grows a
    nested `opponent` dict, this test is where the two readers get reconciled -
    rather than one of them silently returning None again.
    """

    def test_opponent_id_is_a_flat_key(self):
        preview = _parse_single_preview(raw_game(home_id=111, away_id=145), 111,
                                        "2026-08-05")

        assert preview["opponent_id"] == 145

    def test_there_is_no_nested_opponent_dict_to_read(self):
        """The exact expression that silently returned None on every build."""
        preview = _parse_single_preview(raw_game(home_id=111, away_id=145), 111,
                                        "2026-08-05")

        assert preview.get("opponent") is None

    def test_opponent_is_the_other_team_when_boston_is_away(self):
        preview = _parse_single_preview(raw_game(home_id=145, away_id=111), 111,
                                        "2026-08-05")

        assert preview["opponent_id"] == 145
        assert preview["is_home"] is False


class TestFallbackUsesTheLastGamePlayed:
    """
    The fallback only runs when there is no preview at all, but when it runs it
    must not sort by date alone: a doubleheader nightcap shares game 1's date,
    so the last row by date can be the wrong game of the two.
    """

    # `status` is load-bearing: played_in_order filters to Final and returns the
    # frame untouched when the column is absent. A fixture without it silently
    # tests nothing.
    GAMES = pd.DataFrame([
        {"game_pk": 10, "game_date": "2026-08-04", "game_number": 1,
         "opponent_id": 119, "result": "W", "status": "Final"},
        {"game_pk": 11, "game_date": "2026-08-05", "game_number": 2,
         "opponent_id": 145, "result": "L", "status": "Final"},
        {"game_pk": 12, "game_date": "2026-08-05", "game_number": 1,
         "opponent_id": 145, "result": "W", "status": "Final"},
    ])

    def test_last_played_is_the_nightcap_not_the_last_row(self):
        last = played_in_order(self.GAMES).iloc[-1]

        assert last["game_pk"] == 11
        assert last["game_number"] == 2

    def test_naive_date_sort_would_pick_the_wrong_game(self):
        """Documents why played_in_order is used rather than sort_values."""
        naive = self.GAMES.sort_values("game_date").iloc[-1]

        assert naive["game_pk"] == 12          # game 1, played first
        assert naive["game_pk"] != played_in_order(self.GAMES).iloc[-1]["game_pk"]
