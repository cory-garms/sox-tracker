"""
Bullpen availability.

The regression this guards: the matchup page listed the starting rotation as
available relief. `bullpen_availability` took its row list straight from the
caller's roster-derived name set, and the roster is no help — MLB tags every
pitcher on the 26-man with position_group "SP". Only *today's* starter was
subtracted, so the other four rotation arms got rows.

Worse, pitch counts were summed from relief appearances only, so a starter who
threw 95 pitches yesterday showed "0 pitches, FRESH" — the least available arm
in the organisation, rendered as the most.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.matchup import bullpen_availability

REF = "2026-08-23"


def _app(name, date, is_starter, pitches):
    return {
        "player_name": name,
        "game_date": date,
        "is_starter": is_starter,
        "pitches": pitches,
        "game_pk": abs(hash((name, date))) % 10**6,
    }


@pytest.fixture
def staff():
    """
    A staff with one of every case the role rule has to separate:

      Gray     — pure rotation, started 2 days ago
      Bello    — opened the season starting, relief-only since July (swingman)
      Weissert — pure relief
      Promoted — relieved early, moved *into* the rotation recently
      Rested   — a reliever who has not appeared inside the role window
    """
    rows = []
    for d in ("2026-07-28", "2026-08-03", "2026-08-09", "2026-08-15", "2026-08-21"):
        rows.append(_app("Gray", d, True, 95))

    for d in ("2026-04-06", "2026-05-17", "2026-06-04"):
        rows.append(_app("Bello", d, True, 90))
    for d in ("2026-07-31", "2026-08-06", "2026-08-17"):
        rows.append(_app("Bello", d, False, 60))

    for d in ("2026-08-14", "2026-08-18", "2026-08-22"):
        rows.append(_app("Weissert", d, False, 18))

    for d in ("2026-04-10", "2026-05-02", "2026-06-01"):
        rows.append(_app("Promoted", d, False, 20))
    for d in ("2026-08-05", "2026-08-11", "2026-08-16", "2026-08-22"):
        rows.append(_app("Promoted", d, True, 88))

    for d in ("2026-05-01", "2026-05-06", "2026-05-11"):
        rows.append(_app("Rested", d, False, 15))

    return pd.DataFrame(rows)


class TestWhoGetsARow:
    def test_a_pure_starter_is_not_listed_as_a_relief_option(self, staff):
        names = set(bullpen_availability(staff, ref_date_str=REF)["player_name"])
        assert "Gray" not in names

    def test_a_starter_stays_out_even_when_the_roster_vouches_for_him(self, staff):
        """The original bug: the caller's name set overrode the usage filter."""
        every_pitcher = {"Gray", "Bello", "Weissert", "Promoted", "Rested"}
        names = set(
            bullpen_availability(
                staff, ref_date_str=REF, active_pitcher_names=every_pitcher
            )["player_name"]
        )
        assert "Gray" not in names

    def test_a_starter_turned_reliever_is_listed(self, staff):
        """Bello opened 2026 in the rotation; his recent role is what counts."""
        names = set(bullpen_availability(staff, ref_date_str=REF)["player_name"])
        assert "Bello" in names

    def test_a_reliever_turned_starter_is_dropped(self, staff):
        """The mirror case: a season-long 'has he ever relieved?' rule keeps him."""
        names = set(bullpen_availability(staff, ref_date_str=REF)["player_name"])
        assert "Promoted" not in names

    def test_a_reliever_who_has_not_pitched_recently_still_appears(self, staff):
        """No recent role to read falls back to the season split, not exclusion."""
        names = set(bullpen_availability(staff, ref_date_str=REF)["player_name"])
        assert "Rested" in names

    def test_the_active_roster_filter_only_removes(self, staff):
        names = set(
            bullpen_availability(
                staff, ref_date_str=REF, active_pitcher_names={"Weissert"}
            )["player_name"]
        )
        assert names == {"Weissert"}

    def test_no_pitching_data_yields_no_table(self):
        empty = pd.DataFrame(
            columns=["player_name", "game_date", "is_starter", "pitches", "game_pk"]
        )
        assert bullpen_availability(empty, ref_date_str=REF).empty


class TestPitchCounts:
    def test_a_start_inside_the_window_counts_against_availability(self):
        """
        A swingman who started yesterday reported 0 pitches and FRESH, because
        only relief appearances were summed.
        """
        rows = [_app("Swing", d, False, 20) for d in ("2026-07-28", "2026-08-04")]
        rows.append(_app("Swing", "2026-08-22", True, 95))
        df = bullpen_availability(pd.DataFrame(rows), ref_date_str=REF)

        row = df[df["player_name"] == "Swing"].iloc[0]
        assert row["d1_pitches"] == 95
        assert "HEAVY" in row["status"]

    def test_pitches_land_in_the_day_column_they_were_thrown(self, staff):
        row = bullpen_availability(staff, ref_date_str=REF)
        weissert = row[row["player_name"] == "Weissert"].iloc[0]
        assert weissert["d1_pitches"] == 18   # 08-22
        assert weissert["d2_pitches"] == 0    # 08-21, idle
        assert weissert["d3_pitches"] == 0    # 08-20, idle
        assert weissert["tot_3d"] == 18

    def test_an_arm_idle_for_three_days_reads_fresh(self, staff):
        df = bullpen_availability(staff, ref_date_str=REF)
        bello = df[df["player_name"] == "Bello"].iloc[0]
        assert bello["tot_3d"] == 0          # last outing 08-17
        assert "FRESH" in bello["status"]
