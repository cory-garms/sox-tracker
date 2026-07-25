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
    MAX_PLAUSIBLE_EDGE_K,
    _match_prop_line,
    _poisson_over_push,
    _prop_ev,
    batter_total_bases_model,
    nrfi_yrfi_tracker,
    pitcher_strikeout_model,
)
from conftest import FakeMLBClient, game, games_df, linescore


def pitching_df(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def start(player_id: int, name: str, game_date: str, ip: float, so: int,
          *, game_pk: int = 1, ip_outs: int | None = None) -> dict:
    return {
        "game_pk": game_pk, "game_date": game_date, "season": 2026,
        "team_id": 111, "player_id": player_id, "player_name": name,
        "is_starter": True, "ip": ip,
        "ip_outs": int(ip * 3) if ip_outs is None else ip_outs,
        "h": 5, "r": 2,
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


class FakeOddsClient:
    """Stands in for OddsAPIClient, serving one canned prop map."""

    configured = True

    def __init__(self, lines: dict[str, dict]) -> None:
        self.lines = lines

    def find_event(self, team_name: str) -> dict:
        return {"id": "evt-1"}

    def pitcher_strikeout_lines(self, event_id: str) -> dict:
        return self.lines


def book(line: float, *, over: int = -110, under: int = -110,
         name: str = "Sonny Gray", last_update: str = "2026-07-25T15:01:12Z") -> dict:
    return {name: {"line": line, "over_odds": over, "under_odds": under,
                   "book": "DraftKings", "last_update": last_update}}


def model_with_line(pitching: pd.DataFrame, lines: dict) -> pd.Series:
    df = pitcher_strikeout_model(pitching, pd.DataFrame(), games_df([]),
                                 odds_client=FakeOddsClient(lines))
    return df.iloc[0]


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


class TestInningsNotation:
    """
    `ip` is baseball notation: 6.1 is six and one *third*, not six and one
    tenth. Summing that column as a decimal quietly lost a third of an inning
    per partial start and inflated every K/9.
    """

    def test_partial_innings_are_thirds_not_tenths(self):
        # Three starts of 6.1 IP = 19 outs each = 19.0 innings, not 18.3.
        starts = pitching_df([
            start(1, "P", f"2026-07-0{i}", 6.1, 9, game_pk=i, ip_outs=19)
            for i in range(1, 4)
        ])

        row = pitcher_strikeout_model(starts, pd.DataFrame(), games_df([])).iloc[0]

        # 27 K over 19.0 IP = 12.79 K/9. Reading 6.1 as a decimal gives 18.3 IP
        # and an inflated 13.28.
        assert row["season_k9"] == pytest.approx(12.79, abs=0.01)

    def test_projected_innings_use_real_thirds(self):
        starts = pitching_df([
            start(1, "P", f"2026-07-0{i}", 6.2, 6, game_pk=i, ip_outs=20)
            for i in range(1, 4)
        ])

        row = pitcher_strikeout_model(starts, pd.DataFrame(), games_df([])).iloc[0]

        assert row["avg_ip_start"] == pytest.approx(20 / 3, abs=0.01)


class TestProjectionDoesNotCompoundRecency:
    """
    The model blended K/9 across season and last-5, then multiplied by the
    last-5 innings *alone*. A pitcher who was both striking out more and going
    deeper had two hot streaks multiplied together — which is how a starter
    averaging 5.0 K a start came to be projected for 6.50 against a 4.5 line.
    """

    def _hot_finish(self) -> pd.DataFrame:
        """13 quiet starts (5.0 IP, 4 K), then 5 hot ones (7.0 IP, 9 K)."""
        quiet = [start(1, "Sonny Gray", f"2026-05-{i:02d}", 5.0, 4, game_pk=i)
                 for i in range(1, 14)]
        hot = [start(1, "Sonny Gray", f"2026-07-{i:02d}", 7.0, 9, game_pk=100 + i)
               for i in range(1, 6)]
        return pitching_df(quiet + hot)

    def test_projected_innings_are_blended_not_last_5_only(self):
        row = pitcher_strikeout_model(self._hot_finish(), pd.DataFrame(),
                                      games_df([])).iloc[0]

        # Season is 5.0 IP/start, last 5 are 7.0. The projection must sit
        # between them — taking the last-5 figure alone was the bug.
        assert 5.0 < row["avg_ip_start"] < 7.0

    def test_five_start_sample_gets_less_weight_than_the_season(self):
        row = pitcher_strikeout_model(self._hot_finish(), pd.DataFrame(),
                                      games_df([])).iloc[0]

        season_k9, l5_k9, blended = row["season_k9"], row["l5_k9"], row["blended_k9"]
        assert season_k9 < blended < l5_k9
        # ~35 innings behind the split, against a 60-inning regression constant.
        assert abs(blended - season_k9) < abs(blended - l5_k9)

    def test_projects_lower_than_the_old_compounding_formula(self):
        row = pitcher_strikeout_model(self._hot_finish(), pd.DataFrame(),
                                      games_df([])).iloc[0]

        # The formula this replaced, spelled out: a flat 0.6 on the last-5 K/9,
        # multiplied by the last-5 innings alone.
        old = ((row["season_k9"] * 0.4) + (row["l5_k9"] * 0.6)) * (7.0 / 9.0)

        assert old == pytest.approx(8.12, abs=0.01)
        assert row["proj_k"] < old - 1.0

    def test_projection_lands_between_the_season_and_hot_streak_rates(self):
        """5.39 K/start across the season, 9.0 over the hot five."""
        row = pitcher_strikeout_model(self._hot_finish(), pd.DataFrame(),
                                      games_df([])).iloc[0]

        assert 5.39 < row["proj_k"] < 9.0


class TestPlausibilityGuard:
    """
    A model that disagrees with a liquid market by more than its own error bar
    is reporting a bug, not an edge. It must say so rather than shout OVER.
    """

    def test_implausible_edge_is_flagged_for_review(self):
        row = model_with_line(five_starts(ip=7.0, so=12), book(3.5))

        assert row["edge"] > MAX_PLAUSIBLE_EDGE_K
        assert row["flagged"]
        assert "REVIEW" in row["recommendation"]

    def test_implausible_edge_recommends_no_side(self):
        row = model_with_line(five_starts(ip=7.0, so=12), book(3.5))

        assert "OVER" not in row["recommendation"]
        assert "UNDER" not in row["recommendation"]

    def test_implausible_edge_publishes_no_ev(self):
        """Publishing EV we have just called untrustworthy is the failure mode."""
        row = model_with_line(five_starts(ip=7.0, so=12), book(3.5))

        assert row["ev_pct"] is None

    def test_guard_fires_on_large_negative_edges_too(self):
        row = model_with_line(five_starts(ip=5.0, so=2), book(9.5))

        assert row["edge"] < -MAX_PLAUSIBLE_EDGE_K
        assert row["flagged"]
        assert "REVIEW" in row["recommendation"]

    def test_review_row_still_reports_the_line_and_edge(self):
        """Flagging suppresses the call, not the evidence behind it."""
        row = model_with_line(five_starts(ip=7.0, so=12), book(3.5))

        assert row["has_line"]
        assert row["prop_line"] == 3.5
        assert row["edge"] is not None

    def test_plausible_edge_still_recommends_a_side(self):
        """The guard must not swallow ordinary edges."""
        row = model_with_line(five_starts(ip=6.0, so=7), book(6.0))

        assert not row["flagged"]
        assert "REVIEW" not in row["recommendation"]

    def test_small_edge_is_neutral_and_unflagged(self):
        row = model_with_line(five_starts(ip=6.0, so=7), book(7.0))

        assert not row["flagged"]
        assert row["recommendation"] == "NEUTRAL ⚖️"


class TestStrikeoutProbability:
    """
    EV used to come from a hand-picked 0.12 win-probability-per-strikeout
    sensitivity that was never fitted to anything. It now comes from a Poisson
    distribution around the projection.
    """

    def test_over_probability_rises_with_the_projection(self):
        low, _ = _poisson_over_push(4.0, 5.5)
        high, _ = _poisson_over_push(7.0, 5.5)

        assert low < high

    def test_half_point_lines_cannot_push(self):
        _, p_push = _poisson_over_push(6.0, 5.5)

        assert p_push == 0.0

    def test_whole_number_lines_can_push(self):
        _, p_push = _poisson_over_push(6.0, 6.0)

        assert p_push > 0.0

    def test_probabilities_stay_in_range(self):
        for mean in (0.0, 1.0, 6.0, 20.0):
            p_over, p_push = _poisson_over_push(mean, 5.5)
            assert 0.0 <= p_over <= 1.0
            assert 0.0 <= p_push <= 1.0
            assert p_over + p_push <= 1.0

    def test_model_probability_is_independent_of_the_book_price(self):
        """
        The old formula anchored on the book's own de-vigged price, so the
        model could never truly disagree with it. Same projection and line at
        two different prices must yield the same model probability.
        """
        cheap = model_with_line(five_starts(), book(6.5, over=-200, under=+160))
        rich = model_with_line(five_starts(), book(6.5, over=+160, under=-200))

        assert cheap["model_over_prob"] == rich["model_over_prob"]

    def test_ev_reduces_to_the_plain_formula_without_a_push(self):
        # 60% at +100 is a 20% edge.
        assert _prop_ev(0.6, 0.0, 100) == pytest.approx(20.0)

    def test_push_probability_is_not_counted_as_a_loss(self):
        with_push = _prop_ev(0.5, 0.2, 100)
        without_push = _prop_ev(0.5, 0.0, 100)

        assert with_push > without_push


class TestLineTimestamp:
    """
    A statically built page can only show odds as of its last build, so it has
    to carry the moment the book last moved them.
    """

    def test_last_update_is_carried_onto_the_row(self):
        row = model_with_line(five_starts(), book(6.5))

        assert row["line_last_update"] == "2026-07-25T15:01:12Z"

    def test_no_timestamp_without_a_line(self):
        df = pitcher_strikeout_model(five_starts(), pd.DataFrame(), games_df([]))

        assert df.iloc[0]["line_last_update"] is None


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
