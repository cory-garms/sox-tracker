"""
Betting models — chiefly that they refuse to invent numbers.

The regression these guard: the strikeout model used to derive the prop line
from its own projection, pinning the edge within ±0.25 so it could never reach
the ±0.3 recommendation threshold, and then computed an "EV" against a hardcoded
-115 that no book had quoted. The same disease was still loose elsewhere on the
page long after the strikeout model was cured — an assumed 1.5 total-bases line,
a hardcoded 4.5 for first-five runs, a home-run badge on invented thresholds —
so most of what follows exists to keep any of it from coming back.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis import betting
from analysis.betting import (
    MAX_PLAUSIBLE_EDGE_K,
    MAX_PLAUSIBLE_EDGE_TB_PROB,
    MIN_EDGE_K,
    MIN_EDGE_TB_PROB,
    MODEL_ERROR_K,
    MODEL_ERROR_TB_PROB,
    _match_prop_line,
    _pmf_over_push,
    _poisson_over_push,
    _prop_ev,
    _tb_pmf,
    batter_hr_rbi_props,
    batter_total_bases_model,
    fetch_book_lines,
    first_5_innings_analysis,
    nrfi_yrfi_tracker,
    pitcher_strikeout_model,
    probable_starters,
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
    """Stands in for OddsAPIClient, serving canned prop maps for both markets."""

    configured = True

    def __init__(self, lines: dict[str, dict] | None = None,
                 tb_lines: dict[str, dict] | None = None,
                 event: dict | None = {"id": "evt-1"},
                 fail_markets: set[str] | None = None) -> None:
        self.lines = lines or {}
        self.tb_lines = tb_lines or {}
        self.event = event
        self.fail_markets = fail_markets or set()
        self.calls: list[str] = []

    # fetch_book_lines now asks for the raw payload and parses it itself, so
    # that the same one-credit request can yield both the book we bet at and
    # the consensus of the others. The fake therefore has to serve payloads
    # rather than pre-parsed maps.
    bookmaker = "draftkings"

    def find_event(self, team_name: str) -> dict | None:
        self.calls.append("find_event")
        return self.event

    @staticmethod
    def _payload(market: str, lines: dict[str, dict]) -> dict:
        """Re-nest a parsed map back into The Odds API's wire shape."""
        outcomes = []
        for player, entry in lines.items():
            for side, key in (("Over", "over_odds"), ("Under", "under_odds")):
                if entry.get(key) is None:
                    continue
                outcome = {"description": player, "name": side, "price": entry[key]}
                if entry.get("line") is not None:
                    outcome["point"] = entry["line"]
                outcomes.append(outcome)
        return {
            "bookmakers": [{
                "title": "DraftKings",
                "last_update": next(
                    (e.get("last_update") for e in lines.values() if e.get("last_update")),
                    None,
                ),
                "markets": [{"key": market, "outcomes": outcomes}],
            }]
        }

    def get_event_props(self, event_id: str, markets: str = "", **kwargs) -> dict:
        self.calls.append(markets)
        if markets in self.fail_markets:
            raise RuntimeError("simulated provider failure")
        if markets == "pitcher_strikeouts":
            return self._payload(markets, self.lines)
        if markets == "batter_total_bases":
            return self._payload(markets, self.tb_lines)
        return {}


def book(line: float, *, over: int = -110, under: int = -110,
         name: str = "Sonny Gray", last_update: str = "2026-07-25T15:01:12Z") -> dict:
    return {name: {"line": line, "over_odds": over, "under_odds": under,
                   "book": "DraftKings", "last_update": last_update}}


def model_with_line(pitching: pd.DataFrame, lines: dict) -> pd.Series:
    df = pitcher_strikeout_model(pitching, pd.DataFrame(), games_df([]),
                                 book_lines=lines)
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

    def test_the_hot_streak_does_not_pull_the_projection_at_all(self):
        """
        Stronger than the guarantee this replaced. The model used to blend the
        last five starts in at reduced weight; measured over 2,347 league starts
        that term earned nothing over a plain season rate (95% CI on the MSE gap
        [-0.018, +0.058]), so it is gone. A five-start heater must now move the
        projected rate by exactly zero.
        """
        row = pitcher_strikeout_model(self._hot_finish(), pd.DataFrame(),
                                      games_df([])).iloc[0]

        # l5_k9 is still reported - a reader wants to see the streak - but the
        # projection must not have used it.
        assert row["l5_k9"] > row["season_k9"]
        assert row["blended_k9"] == pytest.approx(row["season_k9"], abs=0.01)

    def test_projects_lower_than_the_old_compounding_formula(self):
        row = pitcher_strikeout_model(self._hot_finish(), pd.DataFrame(),
                                      games_df([])).iloc[0]

        # The formula this replaced, spelled out: a flat 0.6 on the last-5 K/9,
        # multiplied by the last-5 innings alone.
        old = ((row["season_k9"] * 0.4) + (row["l5_k9"] * 0.6)) * (7.0 / 9.0)

        assert old == pytest.approx(8.12, abs=0.01)
        assert row["proj_k"] < old - 1.0

    def test_projection_stays_at_the_season_rate_not_the_hot_streak(self):
        """
        5.39 K/start across the season, 9.0 over the hot five. With no league
        rate to regress toward the projection is the season rate exactly, and
        must not drift up toward the streak.
        """
        row = pitcher_strikeout_model(self._hot_finish(), pd.DataFrame(),
                                      games_df([])).iloc[0]

        assert row["proj_k"] == pytest.approx(5.39, abs=0.01)


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

    def test_edge_inside_the_band_is_not_flagged(self):
        """The guard must not swallow edges it was never meant to catch."""
        row = model_with_line(five_starts(ip=6.0, so=7), book(6.0))

        assert not row["flagged"]
        assert "REVIEW" not in row["recommendation"]


class TestNoiseFloor:
    """
    An edge smaller than the model's own error bar cannot be told apart from
    zero. Calling a side on it would dress up noise as a read.
    """

    def test_edge_inside_the_error_bar_calls_no_side(self):
        """Projection 7.0 against a 6.75 line — a +0.25 edge, under the floor."""
        row = model_with_line(five_starts(ip=6.0, so=7), book(6.75))

        assert 0 < row["edge"] < MIN_EDGE_K
        assert row["recommendation"] == "NO CALL ⚖️"

    def test_no_call_publishes_no_ev(self):
        row = model_with_line(five_starts(ip=6.0, so=7), book(6.75))

        assert row["ev_pct"] is None

    def test_no_call_still_shows_the_projection_line_and_edge(self):
        """Withholding the bet is not withholding the evidence."""
        row = model_with_line(five_starts(ip=6.0, so=7), book(6.0))

        assert row["proj_k"] == pytest.approx(7.0)
        assert row["prop_line"] == 6.0
        assert row["edge"] == pytest.approx(1.0)

    def test_negative_edge_inside_the_error_bar_calls_no_side(self):
        row = model_with_line(five_starts(ip=6.0, so=7), book(7.25))

        assert -MIN_EDGE_K < row["edge"] < 0
        assert row["recommendation"] == "NO CALL ⚖️"

    def test_floor_and_ceiling_leave_real_room_to_recommend(self):
        """
        The inverse of what this test asserted until 2026-08-04.

        For as long as MODEL_ERROR_K was 1.39 the floor and the 1.5 ceiling were
        a 0.11 K sliver apart, so the page recommended nothing and this test
        pinned the window shut. Re-measuring on 2,347 league starts instead of 73
        Boston ones put the error at 0.45 K, and the band opened on its own.

        It is asserted from the constants rather than hardcoded, so re-measuring
        the model still drives it. What it now guards is the opposite failure:
        the page silently going mute again because a future error estimate
        crept back up toward the ceiling. If that is genuinely what was
        measured, widen this deliberately - never move the measurement to
        satisfy the bound.
        """
        assert MIN_EDGE_K == MODEL_ERROR_K
        window = MAX_PLAUSIBLE_EDGE_K - MIN_EDGE_K
        assert window > 0.5, (
            f"recommendation window is {window:.2f} K - the band has closed "
            f"back up and the page can no longer call any side. Confirm that "
            f"is what the backtest measured before accepting it."
        )

    def test_an_edge_inside_the_narrow_band_would_still_recommend(self):
        """
        The band is near-empty, not switched off — the machinery still works, so
        recommendations resume on their own once the model earns a smaller error
        bar. Derived from the constants so it survives them being retuned.
        """
        proj = 7.0
        line = round(proj - (MIN_EDGE_K + MAX_PLAUSIBLE_EDGE_K) / 2, 2)

        row = model_with_line(five_starts(ip=6.0, so=7), book(line))

        assert "OVER" in row["recommendation"]
        assert row["ev_pct"] is not None


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


class FakePreviewClient:
    """Serves canned MLB schedule previews for probable-starter lookups."""

    def __init__(self, previews: list[dict] | None = None,
                 fail: bool = False) -> None:
        self.previews = previews or []
        self.fail = fail

    def get_game_previews(self, team_id: int, date_str: str) -> list[dict]:
        if self.fail:
            raise RuntimeError("simulated schedule failure")
        return self.previews


def preview(pitcher_id: int | None, name: str = "Sonny Gray",
            *, game_pk: int = 1) -> dict:
    """One raw schedule game with the Red Sox at home."""
    probable = ({"id": pitcher_id, "fullName": name, "pitchHand": {"code": "R"}}
                if pitcher_id else {})
    return {
        "gamePk": game_pk,
        "officialDate": "2026-07-25",
        "teams": {
            "home": {"team": {"id": 111}, "probablePitcher": probable},
            "away": {"team": {"id": 141},
                     "probablePitcher": {"id": 99, "fullName": "Dylan Cease"}},
        },
    }


class TestProbableStarters:
    def test_returns_the_listed_starter(self):
        found = probable_starters(FakePreviewClient([preview(1)]),
                                  team_id=111, date_str="2026-07-25")

        assert found == [{"id": 1, "name": "Sonny Gray"}]

    def test_doubleheader_returns_both_starters(self):
        """
        Dropping game two's starter is the doubleheader bug this repo keeps
        re-learning. Both probables must come back.
        """
        client = FakePreviewClient([
            preview(1, "Sonny Gray", game_pk=1),
            preview(2, "Payton Tolle", game_pk=2),
        ])

        found = probable_starters(client, team_id=111, date_str="2026-07-25")

        assert [p["name"] for p in found] == ["Sonny Gray", "Payton Tolle"]

    def test_unannounced_starter_yields_nothing(self):
        found = probable_starters(FakePreviewClient([preview(None)]),
                                  team_id=111, date_str="2026-07-25")

        assert found == []

    def test_schedule_failure_yields_nothing_rather_than_raising(self):
        found = probable_starters(FakePreviewClient(fail=True),
                                  team_id=111, date_str="2026-07-25")

        assert found == []

    def test_no_client_or_no_date_yields_nothing(self):
        assert probable_starters(None, team_id=111, date_str="2026-07-25") == []
        assert probable_starters(FakePreviewClient([preview(1)]),
                                 team_id=111, date_str=None) == []


class TestTableCoversOnlyTodaysStarter:
    """
    The table used to list every arm that had ever started — openers and long
    relievers included, none of whom would pitch or had a prop line.
    """

    def _rotation(self) -> pd.DataFrame:
        gray = [start(1, "Sonny Gray", f"2026-07-{i:02d}", 6.0, 7, game_pk=i)
                for i in range(1, 6)]
        tolle = [start(2, "Payton Tolle", f"2026-07-{i:02d}", 5.0, 6, game_pk=20 + i)
                 for i in range(1, 6)]
        opener = [start(3, "Jovani Morán", f"2026-07-{i:02d}", 1.0, 2, game_pk=40 + i)
                  for i in range(1, 6)]
        return pitching_df(gray + tolle + opener)

    def test_only_the_named_starter_appears(self):
        df = pitcher_strikeout_model(self._rotation(), pd.DataFrame(), games_df([]),
                                     only_player_ids={1})

        assert df["player_name"].tolist() == ["Sonny Gray"]

    def test_openers_and_the_rest_of_the_rotation_are_excluded(self):
        df = pitcher_strikeout_model(self._rotation(), pd.DataFrame(), games_df([]),
                                     only_player_ids={1})

        assert "Jovani Morán" not in df["player_name"].tolist()
        assert "Payton Tolle" not in df["player_name"].tolist()

    def test_doubleheader_shows_both_starters(self):
        df = pitcher_strikeout_model(self._rotation(), pd.DataFrame(), games_df([]),
                                     only_player_ids={1, 2})

        assert sorted(df["player_name"].tolist()) == ["Payton Tolle", "Sonny Gray"]

    def test_empty_filter_shows_nobody_rather_than_the_whole_rotation(self):
        """
        An unresolved probable must produce an empty table the page can explain
        — never a silent fallback to everyone who has ever started.
        """
        df = pitcher_strikeout_model(self._rotation(), pd.DataFrame(), games_df([]),
                                     only_player_ids=set())

        assert df.empty

    def test_omitting_the_filter_keeps_every_starter(self):
        df = pitcher_strikeout_model(self._rotation(), pd.DataFrame(), games_df([]))

        assert len(df) == 3


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


def batter_game(i: int, *, h=2, doubles=1, triples=0, hr=0, pa=4,
                player_id=7, name="Wilyer Abreu", batting_order=3) -> dict:
    return {
        "game_pk": i, "game_date": f"2026-07-{i:02d}", "season": 2026,
        "team_id": 111, "player_id": player_id, "player_name": name,
        "batting_order": batting_order, "position": "RF", "ab": pa, "pa": pa,
        "h": h, "doubles": doubles, "triples": triples, "hr": hr, "rbi": 1,
        "r": 1, "bb": 0, "ibb": 0, "so": 1, "hbp": 0, "sb": 0, "cs": 0,
        "sac_bunt": 0, "sac_fly": 0, "gidp": 0,
        "avg": .280, "obp": .350, "slg": .480, "ops": .830,
    }


def batting_df(n_games=12, **kwargs) -> pd.DataFrame:
    return pd.DataFrame([batter_game(i, **kwargs) for i in range(1, n_games + 1)])


def tb_book(line: float = 1.5, *, over: int = -110, under: int = -110,
            name: str = "Wilyer Abreu",
            last_update: str = "2026-07-25T15:01:12Z") -> dict:
    return {name: {"line": line, "over_odds": over, "under_odds": under,
                   "book": "DraftKings", "last_update": last_update}}


def _american(prob: float) -> int:
    """The American price a book would post for a fair probability."""
    return int(round(-100 * prob / (1 - prob))) if prob > 0.5 \
        else int(round(100 * (1 - prob) / prob))


def priced_at(fair_over: float, line: float = 1.5, **kwargs) -> dict:
    """
    A vig-free two-sided market at a chosen fair probability.

    Tests about the edge have to control what the *book* thinks, not what the
    model thinks — otherwise they only assert that the fixture hitter is good.
    """
    return tb_book(line, over=_american(fair_over),
                   under=_american(1 - fair_over), **kwargs)


class TestBatterTotalBasesWithoutLines:
    """
    The table used to price every hitter against an assumed 1.5, calling
    "OVER 1.5 🔥" whenever a projection cleared 1.65 or a ten-game hit rate
    cleared 60% — a line no book had quoted and two thresholds nobody had
    measured. It was the same bug the strikeout model had been cured of.
    """

    def test_reports_no_line_rather_than_assuming_one_point_five(self):
        row = batter_total_bases_model(batting_df()).iloc[0]

        assert not row["has_line"]
        assert row["prop_line"] is None
        assert "NO LINE" in row["recommendation"]

    def test_publishes_no_probability_or_ev_without_a_line(self):
        row = batter_total_bases_model(batting_df()).iloc[0]

        assert row["book_over_prob"] is None
        assert row["prob_edge"] is None
        assert row["ev_pct"] is None

    def test_never_recommends_a_side_against_a_line_nobody_quoted(self):
        for hot in (batting_df(h=4, doubles=2, hr=1), batting_df(h=0, doubles=0)):
            rec = batter_total_bases_model(hot).iloc[0]["recommendation"]

            assert "OVER" not in rec and "UNDER" not in rec

    def test_still_publishes_a_projection(self):
        assert batter_total_bases_model(batting_df()).iloc[0]["proj_tb"] > 0

    def test_batters_below_the_pa_floor_are_excluded(self):
        assert batter_total_bases_model(batting_df(n_games=2)).empty

    def test_empty_input_returns_empty_frame(self):
        assert batter_total_bases_model(pd.DataFrame()).empty


class TestBatterTotalBasesAgainstRealLines:
    def test_line_price_and_book_timestamp_are_carried_through(self):
        row = batter_total_bases_model(batting_df(), tb_book(1.5)).iloc[0]

        assert row["has_line"]
        assert row["prop_line"] == 1.5
        assert row["line_last_update"] == "2026-07-25T15:01:12Z"
        assert "DraftKings" in row["line_source"]

    def test_market_probability_is_de_vigged(self):
        """-110 both ways is a 50/50 market once the vig comes out, not 52.4%."""
        row = batter_total_bases_model(batting_df(), tb_book(1.5)).iloc[0]

        assert row["book_over_prob"] == pytest.approx(0.5, abs=1e-6)

    def test_model_probability_is_independent_of_the_price(self):
        """
        Same hitter, same line, opposite prices. If the model's own number moves
        with the book's, it is reading the price back to itself — the bug that
        made the old strikeout EV meaningless.
        """
        cheap = batter_total_bases_model(batting_df(), tb_book(over=-200, under=+160)).iloc[0]
        rich = batter_total_bases_model(batting_df(), tb_book(over=+160, under=-200)).iloc[0]

        assert cheap["model_over_prob"] == rich["model_over_prob"]

    def test_edge_is_measured_in_probability_not_bases(self):
        """
        Every hitter is posted at 1.5, so "projection minus line" would rank
        hitters by quality the price already reflects. The edge is the gap
        between the model's over-probability and the book's de-vigged one.
        """
        row = batter_total_bases_model(batting_df(), tb_book(1.5)).iloc[0]

        assert row["prob_edge"] == pytest.approx(
            row["model_over_prob"] - row["book_over_prob"], abs=1e-4)

    def test_unpriced_hitters_still_appear_without_a_line(self):
        both = pd.concat([batting_df(), batting_df(player_id=9, name="Trevor Story")])

        df = batter_total_bases_model(both, tb_book(name="Wilyer Abreu"))

        assert set(df["player_name"]) == {"Wilyer Abreu", "Trevor Story"}
        assert df.iloc[0]["player_name"] == "Wilyer Abreu"      # priced rows first
        assert not df[df["player_name"] == "Trevor Story"].iloc[0]["has_line"]


class TestBatterTotalBasesNoiseFloor:
    """
    Measured by walk-forward backtest (scripts/backtest_batter_tb.py): the
    model's own over-probability moves ±4.9 points on resampling its inputs,
    while the whole spread of opinion it has been shown to hold is 5.1 points.
    An edge it cannot tell apart from that noise is not an edge.
    """

    def _hitter(self) -> pd.DataFrame:
        """A .250 hitter with a single a game — around 26% to clear 1.5 bases,
        which leaves room to move the book's price either side of the model."""
        return batting_df(h=1, doubles=1, pa=5)

    def _model_prob(self) -> float:
        row = batter_total_bases_model(self._hitter(), tb_book()).iloc[0]
        return float(row["model_over_prob"])

    def test_a_small_probability_edge_calls_no_side(self):
        """The book two points below the model — inside its own error bar."""
        row = batter_total_bases_model(
            self._hitter(), priced_at(self._model_prob() - 0.02)).iloc[0]

        assert 0 < row["prob_edge"] < MIN_EDGE_TB_PROB
        assert row["recommendation"] == "NO CALL ⚖️"
        assert row["ev_pct"] is None

    def test_a_small_negative_edge_calls_no_side_either(self):
        row = batter_total_bases_model(
            self._hitter(), priced_at(self._model_prob() + 0.02)).iloc[0]

        assert -MIN_EDGE_TB_PROB < row["prob_edge"] < 0
        assert row["recommendation"] == "NO CALL ⚖️"

    def test_no_call_still_shows_the_line_and_both_probabilities(self):
        """Withholding the bet is not withholding the evidence."""
        row = batter_total_bases_model(
            self._hitter(), priced_at(self._model_prob() - 0.02)).iloc[0]

        assert row["prop_line"] == 1.5
        assert row["model_over_prob"] is not None
        assert row["book_over_prob"] is not None

    def test_an_implausible_edge_is_flagged_for_review_with_no_ev(self):
        """Twenty points clear of a liquid market is a bug report, not a gift."""
        row = batter_total_bases_model(
            self._hitter(), priced_at(self._model_prob() - 0.20)).iloc[0]

        assert row["prob_edge"] > MAX_PLAUSIBLE_EDGE_TB_PROB
        assert row["flagged"]
        assert "REVIEW" in row["recommendation"]
        assert row["ev_pct"] is None

    def test_the_guard_fires_on_large_negative_edges_too(self):
        row = batter_total_bases_model(
            self._hitter(), priced_at(self._model_prob() + 0.20)).iloc[0]

        assert row["prob_edge"] < -MAX_PLAUSIBLE_EDGE_TB_PROB
        assert row["flagged"]
        assert "OVER" not in row["recommendation"]
        assert "UNDER" not in row["recommendation"]

    def test_the_band_has_closed_completely(self):
        """
        The 2026-08-23 re-measurement over 935 held-out starts brought the
        ceiling down onto the floor: noise 0.0481, demonstrated information
        0.710 x 0.0682 = 0.048. Two tenths of a point used to separate them;
        now nothing does.

        This is the finding, not a bug. The model's entire demonstrated
        information is the same size as its own noise, so there is no width of
        edge it could honestly recommend from. If a sharper model ever
        separates these two constants, this assertion is the thing to revisit.
        """
        assert MIN_EDGE_TB_PROB == MODEL_ERROR_TB_PROB
        assert MAX_PLAUSIBLE_EDGE_TB_PROB <= MIN_EDGE_TB_PROB

    def test_no_edge_of_any_size_can_be_recommended(self):
        """
        The consequence, stated directly: below the floor is NO CALL, above the
        ceiling is REVIEW, and the two now meet. Every side is refused.
        """
        model_prob = self._model_prob()
        for offset in (0.005, 0.02, 0.048, 0.10, 0.20):
            for signed in (offset, -offset):
                rec = batter_total_bases_model(
                    self._hitter(), priced_at(model_prob - signed)).iloc[0]["recommendation"]
                assert "OVER" not in rec and "UNDER" not in rec, (
                    f"a {signed:+.3f} edge produced {rec!r} from a closed band"
                )

    def test_the_machinery_is_closed_by_measurement_not_switched_off(self, monkeypatch):
        """
        Recommendations resume on their own if a future model re-measures the
        constants apart. Widening the ceiling here — and nothing else — must be
        enough to make a side appear, or the band is not what is silencing the
        model.
        """
        monkeypatch.setattr(betting, "MAX_PLAUSIBLE_EDGE_TB_PROB", 0.25)
        model_prob = self._model_prob()
        gap = MIN_EDGE_TB_PROB + 0.02

        over = batter_total_bases_model(
            self._hitter(), priced_at(model_prob - gap)).iloc[0]
        under = batter_total_bases_model(
            self._hitter(), priced_at(model_prob + gap)).iloc[0]

        assert "OVER" in over["recommendation"]
        assert over["ev_pct"] is not None
        assert "UNDER" in under["recommendation"]


class TestTotalBasesDistribution:
    """
    Total bases are not Poisson — a home run delivers four at once — so the
    model convolves per-plate-appearance outcomes instead of reusing the
    strikeout machinery.
    """

    def _mix(self, single=0.15, double=0.05, triple=0.005, homer=0.03):
        return (single, double, triple, homer)

    def test_distribution_sums_to_one(self):
        pmf = _tb_pmf(self._mix(), {4: 8, 5: 2})

        assert pmf.sum() == pytest.approx(1.0)

    def test_a_better_hitter_clears_the_line_more_often(self):
        weak, _ = _pmf_over_push(_tb_pmf(self._mix(0.10, 0.02, 0.0, 0.01), {4: 10}), 1.5)
        strong, _ = _pmf_over_push(_tb_pmf(self._mix(0.20, 0.08, 0.01, 0.06), {4: 10}), 1.5)

        assert weak < strong

    def test_more_plate_appearances_clear_the_line_more_often(self):
        few, _ = _pmf_over_push(_tb_pmf(self._mix(), {2: 10}), 1.5)
        many, _ = _pmf_over_push(_tb_pmf(self._mix(), {5: 10}), 1.5)

        assert few < many

    def test_half_point_lines_cannot_push(self):
        assert _pmf_over_push(_tb_pmf(self._mix(), {4: 10}), 1.5)[1] == 0.0

    def test_whole_number_lines_can_push(self):
        assert _pmf_over_push(_tb_pmf(self._mix(), {4: 10}), 2.0)[1] > 0.0

    def test_probabilities_stay_in_range(self):
        pmf = _tb_pmf(self._mix(), {3: 4, 4: 6})
        for line in (0.5, 1.5, 2.0, 4.5, 40.5):
            p_over, p_push = _pmf_over_push(pmf, line)
            assert 0.0 <= p_over <= 1.0
            assert 0.0 <= p_push <= 1.0
            assert p_over + p_push <= 1.0 + 1e-9

    def test_a_home_run_is_worth_four_bases_in_the_mean(self):
        """One PA, homers only: the mean has to be 4 x the homer rate."""
        pmf = _tb_pmf((0.0, 0.0, 0.0, 0.25), {1: 1})

        assert float((pmf * range(len(pmf))).sum()) == pytest.approx(1.0)


class TestTotalBasesUsesStartsOnly:
    """
    A total-bases prop is offered on a hitter who is in the lineup. Averaging
    over pinch-hit and bench games divided every regular's production by games
    they never batted in.
    """

    def _regular_who_sits(self) -> pd.DataFrame:
        played = [batter_game(i) for i in range(1, 13)]
        benched = [batter_game(i, h=0, doubles=0, pa=0, batting_order=0)
                   for i in range(13, 25)]
        return pd.DataFrame(played + benched)

    def test_bench_games_do_not_dilute_the_projection(self):
        sat = batter_total_bases_model(self._regular_who_sits()).iloc[0]
        never_sat = batter_total_bases_model(batting_df()).iloc[0]

        assert sat["proj_tb"] == pytest.approx(never_sat["proj_tb"], abs=1e-9)

    def test_the_start_count_reports_starts_not_appearances(self):
        assert batter_total_bases_model(self._regular_who_sits()).iloc[0]["starts"] == 12


class TestHomeRunLeaderboardMakesNoCalls:
    """
    The home-run table ended in a HIGH / MODERATE / LOW badge keyed off "2 in
    the last 10" or "one per 18 PA" — invented thresholds, rendered like a pick,
    against a market this page never fetched.
    """

    def test_no_rating_badge_is_produced(self):
        df = batter_hr_rbi_props(batting_df(hr=1))

        assert "hr_rating" not in df.columns

    def test_the_underlying_rates_survive(self):
        row = batter_hr_rbi_props(batting_df(hr=1)).iloc[0]

        assert row["tot_hr"] == 12
        assert row["l10_hr"] == 10


class FakeF5Client(FakePreviewClient):
    """A preview client that can also answer season-stat lookups."""

    def __init__(self, previews, stats: dict | None = None) -> None:
        super().__init__(previews)
        self.stats = stats if stats is not None else {"era": "3.50", "whip": "1.10",
                                                      "inningsPitched": 100.0,
                                                      "strikeOuts": 100, "baseOnBalls": 30}

    def get_player_info(self, pid: int) -> dict:
        return {"fullName": f"Pitcher {pid}", "pitchHand": {"code": "R"}}

    def get_player_season_stats(self, pid: int, season: int, group: str = "pitching") -> dict:
        return self.stats


class TestFirstFiveInningsMakesNoCalls:
    """
    The F5 card called OVER or UNDER against a hardcoded 4.5 that no book had
    quoted, using full-start ERA divided down to five innings — which the code
    comment itself said was not a real first-five split. Both halves of the call
    were invented.
    """

    def _pitching(self) -> pd.DataFrame:
        return pitching_df([start(1, "Sonny Gray", f"2026-07-{i:02d}", 6.0, 7, game_pk=i)
                            for i in range(1, 6)])

    def test_no_recommendation_against_a_hardcoded_line(self):
        result = first_5_innings_analysis(
            self._pitching(), games_df([]), FakeF5Client([preview(1)]),
            date_str="2026-07-25")

        assert "f5_line_recommendation" not in result["matchup"]

    def test_a_missing_era_reports_nothing_rather_than_four_point_zero(self):
        """An unreadable ERA used to fall back to a flat 4.00 — a made-up number
        produced in exactly the situation where the page knew nothing."""
        result = first_5_innings_analysis(
            self._pitching(), games_df([]),
            FakeF5Client([preview(1)], stats={"era": "-", "whip": "-"}),
            date_str="2026-07-25")

        assert result["matchup"]["our_f5_exp_runs"] is None
        assert result["matchup"]["f5_total_proj"] is None

    def test_the_estimate_is_still_published_when_it_can_be_made(self):
        result = first_5_innings_analysis(
            self._pitching(), games_df([]), FakeF5Client([preview(1)]),
            date_str="2026-07-25")

        # 3.50 ERA over five innings is 1.94 earned runs, each side.
        assert result["matchup"]["our_f5_exp_runs"] == pytest.approx(1.94, abs=0.01)
        assert result["matchup"]["f5_total_proj"] == pytest.approx(3.88, abs=0.01)


class TestFetchBookLines:
    """
    Both models used to look the event up and fetch their own market, which
    repeated the lookup and left nowhere to log the snapshot from.
    """

    def test_returns_both_markets_from_one_event_lookup(self):
        client = FakeOddsClient(book(4.5), tb_book(1.5))

        result = fetch_book_lines(client)

        assert result["event"]["id"] == "evt-1"
        assert result["pitcher_strikeouts"] == book(4.5)
        assert result["batter_total_bases"] == tb_book(1.5)
        assert client.calls.count("find_event") == 1

    def test_unconfigured_client_yields_empty_markets_not_an_error(self):
        class Unconfigured:
            configured = False

        result = fetch_book_lines(Unconfigured())

        assert result == {"event": None, "pitcher_strikeouts": {}, "batter_total_bases": {}}

    def test_no_client_at_all_yields_empty_markets(self):
        assert fetch_book_lines(None)["event"] is None

    def test_one_failing_market_does_not_take_the_other_down(self):
        client = FakeOddsClient(book(4.5), tb_book(1.5),
                                fail_markets={"batter_total_bases"})

        result = fetch_book_lines(client)

        assert result["pitcher_strikeouts"] == book(4.5)
        assert result["batter_total_bases"] == {}

    def test_no_upcoming_event_yields_empty_markets(self):
        assert fetch_book_lines(FakeOddsClient(book(4.5), event=None))["pitcher_strikeouts"] == {}
