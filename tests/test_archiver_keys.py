"""
Archiver / model column agreement.

The regression this guards: the archiver read column names the models never
emitted — `book_line` where the model says `prop_line`, `edge_prob` where it
says `prob_edge`, plus `model_under_prob`, `proj_ip`, `opponent_k_factor` and
`proj_pa`, none of which exist on either frame.

Nothing failed, because `row.get(missing)` returns None. So the archive filled
with rows whose `line` was NULL — and a prediction without its line cannot be
graded at all, since there is no over/under to score it against. Months of
archival were unusable and no test noticed.

These tests drive the *real* models rather than a fixture, so if a model
renames an output column the archiver's read of it fails here rather than
silently degrading to None in production.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.betting import (
    MODEL_ERROR_K,
    MODEL_ERROR_TB_PROB,
    batter_total_bases_model,
    pitcher_strikeout_model,
)
from backend.services import archiver
from backend.services.archiver import _K_FIELDS, _TB_FIELDS, _num


# --- minimal frames that clear the models' own minimums -------------------
# MIN_STARTS_FOR_PROP = 3, MIN_PA_FOR_TB_PROP = 20.

def _pitching_frame():
    rows = []
    for i, date in enumerate(("2026-07-01", "2026-07-07", "2026-07-13", "2026-07-19")):
        rows.append({
            "player_id": 700, "player_name": "Test Starter", "game_date": date,
            "is_starter": True, "ip_outs": 18, "so": 6, "pitches": 90,
            "game_pk": 900 + i,
        })
    return pd.DataFrame(rows)


def _batting_frame():
    rows = []
    for i in range(12):
        rows.append({
            "player_id": 800, "player_name": "Test Hitter",
            "game_date": f"2026-07-{i + 1:02d}", "batting_order": 3,
            "ab": 4, "pa": 4, "h": 1, "doubles": 0, "triples": 0, "hr": 0,
            "game_pk": 800 + i,
        })
    return pd.DataFrame(rows)


K_LINES = {"Test Starter": {"line": 4.5, "over_odds": -120, "under_odds": 100}}
TB_LINES = {"Test Hitter": {"line": 1.5, "over_odds": 110, "under_odds": -130}}


@pytest.fixture
def capture(monkeypatch):
    """
    Run an archive_* function and hand back the rows it tried to persist,
    without touching a database.
    """
    def run(archive_fn, frame, **kwargs):
        recorded: list[dict] = []

        def fake_insert(session, predictions):
            recorded.extend(predictions)
            return len(predictions)

        monkeypatch.setattr(archiver, "insert_model_predictions", fake_insert)
        archive_fn(None, frame, **kwargs)
        return recorded

    return run


@pytest.fixture(scope="module")
def k_frame():
    df = pitcher_strikeout_model(_pitching_frame(), None, None, book_lines=K_LINES)
    assert not df.empty, "fixture no longer produces a projection"
    return df


@pytest.fixture(scope="module")
def tb_frame():
    df = batter_total_bases_model(_batting_frame(), book_lines=TB_LINES)
    assert not df.empty, "fixture no longer produces a projection"
    return df


class TestTheArchiverReadsColumnsThatExist:
    @pytest.mark.parametrize("field,column", sorted(_K_FIELDS.items()))
    def test_strikeout_columns_exist(self, k_frame, field, column):
        assert column in k_frame.columns, (
            f"archiver reads {column!r} for the K model's {field}; "
            f"model emits {sorted(k_frame.columns)}"
        )

    @pytest.mark.parametrize("field,column", sorted(_TB_FIELDS.items()))
    def test_total_bases_columns_exist(self, tb_frame, field, column):
        assert column in tb_frame.columns, (
            f"archiver reads {column!r} for the TB model's {field}; "
            f"model emits {sorted(tb_frame.columns)}"
        )

    @pytest.mark.parametrize("column", ["model_over_prob", "book_over_prob", "recommendation"])
    def test_shared_columns_exist_on_both(self, k_frame, tb_frame, column):
        assert column in k_frame.columns
        assert column in tb_frame.columns


class TestArchivedRowsCarryTheirLine:
    """The specific failure: line archived as None on every row."""

    def test_strikeout_rows_have_a_line(self, k_frame, capture):
        rows = capture(archiver.archive_strikeout_projections,
                       k_frame, game_date="2026-07-20")
        assert rows, "nothing archived"
        assert all(r["line"] == 4.5 for r in rows), [r["line"] for r in rows]

    def test_total_bases_rows_have_a_line(self, tb_frame, capture):
        rows = capture(archiver.archive_total_bases_projections,
                       tb_frame, game_date="2026-07-20")
        assert rows
        assert all(r["line"] == 1.5 for r in rows), [r["line"] for r in rows]

    def test_strikeout_rows_carry_projection_and_edge(self, k_frame, capture):
        row = capture(archiver.archive_strikeout_projections,
                      k_frame, game_date="2026-07-20")[0]
        assert row["projection"] > 0
        assert row["edge"] is not None
        assert row["details_json"] and "proj_ip" in row["details_json"]

    def test_total_bases_rows_carry_their_probability_edge(self, tb_frame, capture):
        rows = capture(archiver.archive_total_bases_projections,
                       tb_frame, game_date="2026-07-20")
        assert rows[0]["edge"] is not None


class TestTheErrorBarIsTheOneInForce:
    """Hardcoded 0.45 / 0.049 would silently diverge from analysis.betting."""

    def test_strikeout_error_matches_the_constant(self, k_frame, capture):
        rows = capture(archiver.archive_strikeout_projections, k_frame)
        assert all(r["model_error"] == MODEL_ERROR_K for r in rows)

    def test_total_bases_error_matches_the_constant(self, tb_frame, capture):
        rows = capture(archiver.archive_total_bases_projections, tb_frame)
        assert all(r["model_error"] == MODEL_ERROR_TB_PROB for r in rows)


class TestNumericReads:
    def test_zero_is_a_value_not_a_missing_cell(self):
        """`row.get(a) or row.get(b)` treated a legitimate 0.0 as absent."""
        assert _num(pd.Series({"edge": 0.0}), "edge") == 0.0

    def test_nan_reads_as_none(self):
        assert _num(pd.Series({"edge": float("nan")}), "edge") is None

    def test_absent_column_reads_as_none(self):
        assert _num(pd.Series({"other": 1.0}), "edge") is None


class TestUnderProbability:
    def test_is_the_complement_of_over(self, k_frame, capture):
        """Neither model emits model_under_prob; it was archived as None."""
        row = capture(archiver.archive_strikeout_projections, k_frame)[0]
        assert row["model_under_prob"] is not None
        assert row["model_over_prob"] + row["model_under_prob"] == pytest.approx(1.0)
