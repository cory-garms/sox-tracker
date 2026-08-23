"""
Probable-starter card.

Two regressions this guards.

1. **Innings notation.** MLB writes innings as "80.2" meaning eighty and two
   *thirds*. Read as a decimal it silently skews every rate: the matchup page
   published Jake Bennett at 6.85 K/9 while the strikeout model — which
   aggregates ip_outs — published 6.81 for the same pitcher on the models page.
   Two pages, one pitcher, different numbers.

2. **Rates off a handful of innings.** The page showed an opposing starter at
   "ERA 0.00, WHIP 0.50" off 2.0 innings, which reads as the best pitcher in
   baseball rather than as a reliever who has barely pitched.
"""

from __future__ import annotations

import pytest

from analysis.matchup import MIN_IP_FOR_RATES, innings_to_decimal, starter_season_summary


class TestInningsNotation:
    @pytest.mark.parametrize("written,real", [
        (0.0, 0.0),
        (5.0, 5.0),
        (5.1, 5 + 1 / 3),      # five and a third
        (5.2, 5 + 2 / 3),      # five and two thirds
        (80.2, 80 + 2 / 3),
        (6.1, 6 + 1 / 3),      # the value the project's own notes cite
    ])
    def test_thirds_are_decoded_not_read_as_decimals(self, written, real):
        assert innings_to_decimal(written) == pytest.approx(real)

    def test_the_k9_discrepancy_between_the_two_pages_is_gone(self):
        """61 K in 80.2 IP: 6.85 read as a decimal, 6.81 read correctly."""
        so = 61
        assert so * 9 / innings_to_decimal(80.2) == pytest.approx(6.81, abs=0.005)

    @pytest.mark.parametrize("bad", [None, "", "-", "not a number"])
    def test_unusable_input_is_zero_rather_than_an_exception(self, bad):
        assert innings_to_decimal(bad) == 0.0

    def test_a_malformed_fraction_is_left_alone_rather_than_invented(self):
        """.4 is not a valid thirds notation; do not silently make one up."""
        assert innings_to_decimal(5.4) == 5.4


class FakeClient:
    """Minimal stand-in for MLBClient."""

    def __init__(self, ip, so=20, bb=5, era="0.00", whip="0.50"):
        self._ip, self._so, self._bb, self._era, self._whip = ip, so, bb, era, whip

    def get_player_info(self, pid):
        return {"fullName": "Matt Wilkinson", "pitchHand": {"code": "L"}}

    def get_player_season_stats(self, pid, season, group="pitching"):
        return {
            "inningsPitched": self._ip, "strikeOuts": self._so,
            "baseOnBalls": self._bb, "era": self._era, "whip": self._whip,
            "wins": 0, "losses": 0,
        }


class TestThinSamples:
    def test_rates_are_withheld_under_the_innings_floor(self):
        s = starter_season_summary(FakeClient(2.0), 12345)
        assert s["era"] == "-"
        assert s["whip"] == "-"
        assert s["k9"] == "-"
        assert s["bb9"] == "-"
        assert s["thin_sample"] is True

    def test_the_innings_themselves_are_still_shown(self):
        """Withholding the rate is not withholding the evidence for withholding it."""
        s = starter_season_summary(FakeClient(2.0), 12345)
        assert s["ip"] == 2.0

    def test_a_full_season_keeps_its_rates(self):
        s = starter_season_summary(FakeClient(80.2, so=61, era="3.46", whip="1.07"), 12345)
        assert s["thin_sample"] is False
        assert s["era"] == "3.46"
        assert float(s["k9"]) == pytest.approx(6.81, abs=0.005)

    def test_the_floor_is_applied_on_decoded_innings(self):
        """
        9.2 IP is 9 2/3, still under the 10-inning floor. Read as a decimal it
        would look like 9.2 — also under — but 9.1 vs 9 1/3 style cases sit
        either side of thresholds elsewhere, so decode first, compare second.
        """
        assert innings_to_decimal(9.2) < MIN_IP_FOR_RATES
        assert starter_season_summary(FakeClient(9.2), 1)["thin_sample"] is True

    def test_no_pitcher_yields_a_tbd_card_rather_than_an_error(self):
        s = starter_season_summary(FakeClient(50.0), None)
        assert s["name"] == "TBD"
