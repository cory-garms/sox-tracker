"""
The other team's starter, projected by the same model as ours.

His line arrives in the request that bought ours -- the strikeout market comes
back with both starters priced -- and the board projected only our own, so half
of every night's priced strikeout sample was paid for and thrown away.

Same estimator as our starter: k_projections.project_marcel, the shipped
marcel+opp. The risk is the backfill's risk, lookahead: a projection that can
see the game it is projecting looks brilliant and is worthless, and it fails
silently because the numbers still compute.
"""

from __future__ import annotations

import pandas as pd

from analysis.betting import opposing_starter_k_model

TEAM = 111


def logs_for(pid=645261, n=20, so=6, outs=18, upto="2026-08-24"):
    """n prior starts, one every other day, ending before `upto`."""
    dates = pd.date_range(end=pd.Timestamp(upto) - pd.Timedelta(days=1),
                          periods=n, freq="2D").strftime("%Y-%m-%d")
    return pd.DataFrame([{"player_id": pid, "player_name": "Test Starter",
                          "game_date": d, "game_pk": 1000 + i, "team_id": 146,
                          "opponent_id": TEAM, "ip_outs": outs, "so": so,
                          "bf": 24, "is_start": True} for i, d in enumerate(dates)])


class TestItProjects:
    def test_a_starter_with_history_gets_a_projection(self):
        df = opposing_starter_k_model(logs_for(), pd.DataFrame(), 645261,
                                      "Test Starter", TEAM, league_k9=8.4)
        assert len(df) == 1
        assert df["proj_k"][0] > 0
        assert bool(df["is_opposing_starter"][0])

    def test_no_history_projects_nothing(self):
        assert opposing_starter_k_model(logs_for(n=0), pd.DataFrame(), 645261,
                                        "Test Starter", TEAM, league_k9=8.4).empty

    def test_no_starter_id_projects_nothing(self):
        assert opposing_starter_k_model(logs_for(), pd.DataFrame(), None,
                                        "", TEAM, league_k9=8.4).empty

    def test_relief_appearances_are_excluded(self):
        logs = logs_for()
        logs.loc[logs.index[:10], "is_start"] = False
        df = opposing_starter_k_model(logs, pd.DataFrame(), 645261,
                                      "Test Starter", TEAM, league_k9=8.4)
        assert int(df["starts"][0]) == 10


class TestItCannotSeeTheFuture:
    def test_starts_are_truncated_to_before_the_date(self):
        logs = logs_for(n=20, upto="2026-08-24")
        early = opposing_starter_k_model(logs, pd.DataFrame(), 645261, "Test Starter",
                                         TEAM, as_of_date="2026-08-01", league_k9=8.4)
        late = opposing_starter_k_model(logs, pd.DataFrame(), 645261, "Test Starter",
                                        TEAM, as_of_date="2026-08-24", league_k9=8.4)
        assert int(early["starts"][0]) < int(late["starts"][0])

    def test_a_future_blowup_cannot_change_a_past_projection(self):
        """
        The load-bearing one. Same replay date, wildly different future in
        between, and the answer must not move.
        """
        base = logs_for(n=10, upto="2026-07-01")
        future = logs_for(n=10, upto="2026-08-24", so=15)   # 15 K a start after
        asof = "2026-07-01"
        a = opposing_starter_k_model(base, pd.DataFrame(), 645261, "Test Starter",
                                     TEAM, as_of_date=asof, league_k9=8.4)
        b = opposing_starter_k_model(pd.concat([base, future]), pd.DataFrame(),
                                     645261, "Test Starter", TEAM,
                                     as_of_date=asof, league_k9=8.4)
        assert a["proj_k"][0] == b["proj_k"][0]
        assert int(a["starts"][0]) == int(b["starts"][0])


class TestItPricesAgainstTheBook:
    LINES = {"Test Starter": {"line": 4.5, "over_odds": -104, "under_odds": -122,
                              "book": "DraftKings", "last_update": "x"}}

    def test_a_matched_line_produces_probabilities(self):
        df = opposing_starter_k_model(logs_for(), pd.DataFrame(), 645261, "Test Starter",
                                      TEAM, book_lines=self.LINES, league_k9=8.4)
        assert bool(df["has_line"][0])
        assert 0 < df["model_over_prob"][0] < 1
        assert 0 < df["book_over_prob"][0] < 1

    def test_no_line_still_logs_a_projection(self):
        """Unpriced rows are most of the sample and grade for projection error."""
        df = opposing_starter_k_model(logs_for(), pd.DataFrame(), 645261, "Test Starter",
                                      TEAM, book_lines={}, league_k9=8.4)
        assert not bool(df["has_line"][0])
        assert df["proj_k"][0] > 0

    def test_a_negative_ev_side_is_never_named(self):
        """The EV gate applies here too -- same _side_call."""
        df = opposing_starter_k_model(logs_for(so=12), pd.DataFrame(), 645261,
                                      "Test Starter", TEAM,
                                      book_lines={"Test Starter": {
                                          "line": 4.5, "over_odds": -100000,
                                          "under_odds": 100, "book": "DK",
                                          "last_update": "x"}},
                                      league_k9=8.4)
        assert not str(df["recommendation"][0]).startswith("OVER")
