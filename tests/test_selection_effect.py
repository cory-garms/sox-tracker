"""
analysis/selection_effect.py — the postgame log used for more than grading.

The regression this guards is a documentation failure that had already
happened: the track record page carried the selection-effect table as six
numbers typed into the HTML from a measurement run on 2026-08-23. By 2026-09-07
the priced recalibration slope had moved from -0.014 to -0.822 and the hitter
count from 54 to 22, on a page whose argument is that it measures rather than
asserts. Nothing recomputed it because nothing could.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from analysis import selection_effect as se


def _log(rows):
    base = dict(captured_at="2026-08-01T15:00:00+00:00", game_date="2026-08-01",
                commence_time="2026-08-01T23:00:00Z", event_id="e1", game_pk=1,
                market="batter_total_bases", player_id=1, player="P",
                lineup_slot=None, line=None, projection=1.0, model_over_prob=0.5,
                book_over_prob=0.5, edge=0.0, model_error=0.4, recommendation="",
                model_version="v1", opponent_name="", opponent_factor=1.0,
                actual=None, outcome="", settled_at=None)
    # latest_per_game keys on the player *name*, so rows that mean different
    # players must carry different names or they collapse into one and the
    # fixture quietly tests something else.
    out = []
    for r in rows:
        row = {**base, **r}
        row.setdefault("player", f"P{row['player_id']}")
        if "player" not in r:
            row["player"] = f"P{row['player_id']}"
        out.append(row)
    return pd.DataFrame(out)


class TestProjectionAccuracy:
    def test_splits_priced_from_unpriced(self):
        frame = _log([
            {"player_id": 1, "game_date": "2026-08-01", "line": 1.5,
             "projection": 2.0, "actual": 2.0, "outcome": "over"},
            {"player_id": 2, "game_date": "2026-08-02", "game_pk": 2,
             "projection": 1.0, "actual": 1.0, "outcome": "no_line"},
        ])
        rows = se.projection_accuracy(frame)
        assert {r["population"] for r in rows} == {"priced", "unpriced"}
        assert {r["n"] for r in rows} == {1}

    def test_rows_without_an_actual_are_not_scored(self):
        """A player who did not appear has nothing to be right or wrong about."""
        frame = _log([
            {"player_id": 1, "projection": 2.0, "actual": None, "outcome": "dnp"},
            {"player_id": 2, "game_date": "2026-08-02", "game_pk": 2,
             "projection": 1.0, "actual": 1.0, "outcome": "no_line"},
        ])
        rows = se.projection_accuracy(frame)
        assert sum(r["n"] for r in rows) == 1

    def test_reports_the_graded_subset_alongside_the_scored_one(self):
        """The point of the section: n is larger than the gradeable count."""
        frame = _log([
            {"player_id": i, "game_date": f"2026-08-{i:02d}", "game_pk": i,
             "line": 1.5 if i <= 2 else None, "projection": float(i),
             "actual": float(i), "outcome": "over" if i <= 2 else "no_line"}
            for i in range(1, 7)
        ])
        rows = se.projection_accuracy(frame)
        assert sum(r["n"] for r in rows) == 6
        assert sum(r["graded"] for r in rows) == 2

    def test_an_empty_log_yields_nothing_rather_than_raising(self):
        assert se.projection_accuracy(pd.DataFrame()) == []
        assert se.projection_accuracy(None) == []


class TestCorrelationInterval:
    def test_a_perfect_relationship_is_reported_without_a_bogus_interval(self):
        r, lo, hi = se._corr_ci([1, 2, 3, 4], [1, 2, 3, 4])
        assert r == pytest.approx(1.0)
        assert np.isnan(lo) and np.isnan(hi)

    def test_a_constant_column_has_no_correlation_to_report(self):
        """The failure this avoids: numpy returning nan and it reaching a page."""
        r, lo, hi = se._corr_ci([1, 1, 1, 1], [1, 2, 3, 4])
        assert np.isnan(r)

    def test_too_few_points_is_refused(self):
        assert np.isnan(se._corr_ci([1, 2], [1, 2])[0])

    def test_a_wider_sample_gives_a_tighter_interval(self):
        small = se._corr_ci(np.arange(10), np.arange(10) + np.arange(10) % 3)
        large = se._corr_ci(np.arange(200), np.arange(200) + np.arange(200) % 3)
        assert (large[2] - large[1]) < (small[2] - small[1])


class TestGapZ:
    def _rows(self, r_priced, n_priced, r_unpriced, n_unpriced):
        return [
            {"market": "m", "population": "priced", "r": r_priced, "n": n_priced},
            {"market": "m", "population": "unpriced", "r": r_unpriced, "n": n_unpriced},
        ]

    def test_a_real_gap_on_a_real_sample_is_significant(self):
        assert se.gap_z(self._rows(-0.10, 180, 0.12, 231), "m") > 1.96

    def test_the_same_gap_on_a_tiny_sample_is_not(self):
        """The whole reason it is tested rather than eyeballed."""
        assert abs(se.gap_z(self._rows(-0.10, 8, 0.12, 8), "m")) < 1.96

    def test_no_gap_is_near_zero(self):
        assert abs(se.gap_z(self._rows(0.20, 100, 0.20, 100), "m")) < 1e-9

    def test_a_missing_population_yields_no_claim(self):
        rows = [{"market": "m", "population": "priced", "r": 0.1, "n": 50}]
        assert np.isnan(se.gap_z(rows, "m"))


class TestSelectionTable:
    def _held(self, n=200, seed=0):
        rng = np.random.default_rng(seed)
        p = rng.uniform(0.2, 0.7, n)
        return pd.DataFrame({
            "player_id": rng.integers(1, 12, n),
            "game_date": ["2026-08-01"] * n,
            "p_over": p,
            "cleared": rng.binomial(1, p),
        })

    def test_returns_a_row_per_population(self):
        held = self._held()
        priced = {(int(p), "2026-08-01") for p in held["player_id"].unique()[:4]}
        rows = se.selection_table(held, priced)
        assert [r["population"] for r in rows] == [
            "All hitter-starts", "Only those a book priced"]

    def test_the_priced_row_is_a_subset(self):
        held = self._held()
        priced = {(int(p), "2026-08-01") for p in held["player_id"].unique()[:4]}
        rows = se.selection_table(held, priced)
        assert rows[1]["n"] < rows[0]["n"]
        assert rows[1]["hitters"] <= 4

    def test_no_priced_games_yields_only_the_full_population(self):
        assert len(se.selection_table(self._held(), set())) == 1

    def test_an_empty_walk_forward_yields_nothing(self):
        assert se.selection_table(pd.DataFrame(), set()) == []


class TestPricedKeys:
    def test_only_rows_with_a_line_count_as_priced(self):
        frame = _log([
            {"player_id": 1, "game_date": "2026-08-01", "line": 1.5},
            {"player_id": 2, "game_date": "2026-08-01", "game_pk": 2, "line": None},
        ])
        assert se.priced_keys(frame) == {(1, "2026-08-01")}

    def test_another_market_does_not_leak_in(self):
        frame = _log([
            {"player_id": 3, "game_date": "2026-08-01",
             "market": "pitcher_strikeouts", "line": 5.5},
        ])
        assert se.priced_keys(frame, "batter_total_bases") == set()

    def test_an_empty_log_has_no_priced_games(self):
        assert se.priced_keys(pd.DataFrame()) == set()
