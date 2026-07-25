"""
Betting models — chiefly that they refuse to invent numbers.

The regression these guard: the strikeout model used to derive the prop line
from its own projection, pinning the edge within ±0.25 so it could never reach
the ±0.3 recommendation threshold, and then computed an "EV" against a hardcoded
-115 that no book had quoted.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.betting import (
    _match_prop_line,
    batter_total_bases_model,
    nrfi_yrfi_tracker,
    pitcher_strikeout_model,
)
from conftest import FakeMLBClient, game, games_df, linescore


def pitching_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def start(player_id: int, name: str, game_date: str, ip: float, so: int,
          *, game_pk: int = 1) -> dict:
    return {
        "game_pk": game_pk, "game_date": game_date, "season": 2026,
        "team_id": 111, "player_id": player_id, "player_name": name,
        "is_starter": True, "ip": ip, "ip_outs": int(ip * 3), "h": 5, "r": 2,
        "er": 2, "bb": 1, "so": so, "hr": 1, "hbp": 0, "bf": 24,
        "pitches": 95, "strikes": 62, "era": 3.5, "whip": 1.1,
        "k_per_9": 9.0, "bb_per_9": 2.0, "win": 1, "loss": 0, "save": 0,
        "hold": 0, "blown_save": 0, "game_score": 58,
    }


def five_starts(player_id=1, name="Sonny Gray", ip=6.0, so=7) -> pd.DataFrame:
    return pitching_df([
        start(player_id, name, f"2026-07-{i:02d}", ip, so, game_pk=100 + i)
        for i in range(1, 6)
    ])


class TestStrikeoutModelWithoutLines:
    def test_reports_no_line_rather_than_inventing_one(self):
        df = pitcher_strikeout_model(five_starts(), pd.DataFrame(), games_df([]))

        row = df.iloc[0]
        assert not row["has_line"]          # pandas boxes this as np.bool_
        assert row["prop_line"] is None
        assert row["american_odds"] is None
        assert "NO LINE" in row["recommendation"]

    def test_produces_no_edge_or_ev_without_a_line(self):
        """Edge and EV are meaningless with nothing real to compare against."""
        df = pitcher_strikeout_model(five_starts(), pd.DataFrame(), games_df([]))

        assert df.iloc[0]["edge"] is None
        assert df.iloc[0]["ev_pct"] is None

    def test_still_publishes_a_projection(self):
        """The projection is honest work — it just isn't an edge."""
        df = pitcher_strikeout_model(five_starts(), pd.DataFrame(), games_df([]))

        assert df.iloc[0]["proj_k"] > 0

    def test_never_emits_the_old_placeholder_odds(self):
        df = pitcher_strikeout_model(five_starts(), pd.DataFrame(), games_df([]))

        assert "-115" not in str(df["american_odds"].tolist())


class TestStrikeoutModelMinimumStarts:
    def test_pitcher_below_the_minimum_is_excluded(self):
        """One-start relievers were being listed as prop targets."""
        df = pitcher_strikeout_model(
            pitching_df([start(9, "Jovani Morán", "2026-07-01", 1.0, 2)]),
            pd.DataFrame(), games_df([]),
        )

        assert df.empty

    def test_minimum_is_configurable(self):
        one_start = pitching_df([start(9, "Opener", "2026-07-01", 1.0, 2)])

        assert not pitcher_strikeout_model(one_start, pd.DataFrame(),
                                          games_df([]), min_starts=1).empty

    def test_empty_input_returns_empty_frame(self):
        assert pitcher_strikeout_model(pd.DataFrame(), pd.DataFrame(),
                                      games_df([])).empty

    def test_frame_with_no_starters_returns_empty(self):
        relief = pitching_df([start(1, "Reliever", "2026-07-01", 1.0, 1)])
        relief["is_starter"] = False

        assert pitcher_strikeout_model(relief, pd.DataFrame(), games_df([])).empty


class TestPropLineMatching:
    def test_exact_name_matches(self):
        book = {"Sonny Gray": {"line": 6.5, "over_odds": -115}}

        assert _match_prop_line("Sonny Gray", book)["line"] == 6.5

    def test_accented_name_matches_unaccented_book_entry(self):
        """MLB says "Jovani Morán"; books usually say "Jovani Moran"."""
        book = {"Jovani Moran": {"line": 4.5}}

        assert _match_prop_line("Jovani Morán", book) is not None

    def test_unknown_pitcher_returns_none(self):
        assert _match_prop_line("Nobody At All", {"Sonny Gray": {"line": 6.5}}) is None

    def test_empty_book_returns_none(self):
        assert _match_prop_line("Sonny Gray", {}) is None


class TestNRFITracker:
    def test_unavailable_without_a_client(self):
        """
        It used to approximate first-inning runs from full-game totals
        (`total <= 7`), producing a confident number from nothing.
        """
        result = nrfi_yrfi_tracker(
            games_df([game(1, "2026-04-01", 5, 3)]), pd.DataFrame(), client=None,
        )

        assert result["available"] is False
        assert result["total_games"] == 0
        assert result["nrfi_pct"] == 0.0

    def test_counts_first_inning_runs_from_linescores(self):
        df = games_df([
            game(1, "2026-04-01", 5, 3),
            game(2, "2026-04-02", 2, 1),
        ])
        client = FakeMLBClient({1: linescore(0, 0), 2: linescore(1, 0)})

        result = nrfi_yrfi_tracker(df, pd.DataFrame(), client=client)

        assert result["available"] is True
        assert result["total_games"] == 2
        assert result["nrfi_count"] == 1
        assert result["nrfi_pct"] == 50.0

    def test_failed_linescore_is_dropped_not_counted_as_nrfi(self):
        """
        A bare `except: pass` left r1 at 0, so every failed fetch inflated the
        NRFI rate. The game must be excluded instead.
        """
        df = games_df([
            game(1, "2026-04-01", 5, 3),
            game(2, "2026-04-02", 2, 1),
        ])
        client = FakeMLBClient({1: linescore(1, 1)}, fail_for={2})

        result = nrfi_yrfi_tracker(df, pd.DataFrame(), client=client)

        assert result["total_games"] == 1
        assert result["nrfi_count"] == 0
        assert result["nrfi_pct"] == 0.0

    def test_all_linescores_failing_reports_unavailable(self):
        df = games_df([game(1, "2026-04-01", 5, 3)])
        client = FakeMLBClient(fail_for={1})

        assert nrfi_yrfi_tracker(df, pd.DataFrame(), client=client)["available"] is False

    def test_empty_games_reports_unavailable(self):
        assert nrfi_yrfi_tracker(pd.DataFrame(), pd.DataFrame(),
                                 client=FakeMLBClient())["available"] is False


class TestBatterTotalBases:
    def _batting(self, n_games=12, h=2, doubles=1, hr=0):
        return pd.DataFrame([{
            "game_pk": i, "game_date": f"2026-07-{i:02d}", "season": 2026,
            "team_id": 111, "player_id": 7, "player_name": "Wilyer Abreu",
            "batting_order": 3, "position": "RF", "ab": 4, "pa": 4,
            "h": h, "doubles": doubles, "triples": 0, "hr": hr, "rbi": 1,
            "r": 1, "bb": 0, "ibb": 0, "so": 1, "hbp": 0, "sb": 0, "cs": 0,
            "sac_bunt": 0, "sac_fly": 0, "gidp": 0,
            "avg": .280, "obp": .350, "slg": .480, "ops": .830,
        } for i in range(1, n_games + 1)])

    def test_total_bases_formula(self):
        """TB = H + 2B + 2*3B + 3*HR — here 2 hits incl. 1 double = 3."""
        df = batter_total_bases_model(self._batting(h=2, doubles=1, hr=0))

        assert df.iloc[0]["season_tb_g"] == pytest.approx(3.0)

    def test_home_run_counts_as_four_bases(self):
        df = batter_total_bases_model(self._batting(h=1, doubles=0, hr=1))

        assert df.iloc[0]["season_tb_g"] == pytest.approx(4.0)

    def test_batters_below_the_pa_floor_are_excluded(self):
        assert batter_total_bases_model(self._batting(n_games=2)).empty

    def test_empty_input_returns_empty_frame(self):
        assert batter_total_bases_model(pd.DataFrame()).empty
