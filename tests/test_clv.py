"""
Did the market move toward the model?

The one scoreboard that does not wait on outcomes, and the measurement the
handbook has been gating model work on -- "accumulate CLV to n approximately
20" -- while the bet log sat at eleven hand-logged positions.

Two traps, and the first one produced a fully plausible wrong answer before
these tests existed.

1. **Comparing a price to itself.** predictions_history keeps only the last
   pre-game capture per player-game, and that is the same capture that becomes
   the close. Reading the quote off the projection log and the close off the
   odds log therefore differences a number against itself: the real archive
   reported 180 rows whose quote and close agreed to four decimals, a mean of
   -0.000 and a standard deviation of 0.003. Both ends must come from the odds
   log.

2. **Taking the side at the close.** The side has to be fixed against the
   opening price. Fixing it against the close scores the model on the very
   number it is being tested against, and every row wins.
"""

from __future__ import annotations

import pandas as pd

from analysis import clv


def odds_rows(*captures, event="e1", market="batter_total_bases",
              player="Wilyer Abreu", line=1.5, commence="2026-08-24T22:41:00Z",
              book="DraftKings"):
    """captures: (captured_at, over_odds, under_odds)"""
    return pd.DataFrame([
        {"captured_at": c, "event_id": event, "commence_time": commence,
         "home_team": "H", "away_team": "A", "market": market, "player": player,
         "line": line, "over_odds": o, "under_odds": u,
         "book": book, "last_update": c}
        for c, o, u in captures
    ])


def prediction(model_over_prob=0.55, line=1.5, event="e1",
               market="batter_total_bases", player="Wilyer Abreu",
               captured="2026-08-24T21:00:00+00:00", version="v1.1"):
    return pd.DataFrame([{
        "captured_at": captured, "game_date": "2026-08-24", "commence_time": None,
        "event_id": event, "game_pk": pd.NA, "market": market, "player_id": 1,
        "player": player, "lineup_slot": 3, "line": line, "projection": 1.8,
        "model_over_prob": model_over_prob, "book_over_prob": 0.40, "edge": 0.1,
        "model_error": 0.05, "recommendation": "NO CALL", "model_version": version,
        "opponent_name": "", "opponent_factor": float("nan"),
        "actual": float("nan"), "outcome": "", "settled_at": "",
    }])


class TestBothEndsComeFromTheOddsLog:
    def test_a_single_capture_yields_nothing(self):
        """One price is not a movement, and pretending otherwise is the bug."""
        odds = odds_rows(("2026-08-24T19:00:00+00:00", 128, -171))
        assert clv.attach_clv(prediction(), odds).empty

    def test_two_captures_use_first_and_last(self):
        odds = odds_rows(
            ("2026-08-24T11:00:00+00:00", 100, -120),
            ("2026-08-24T15:00:00+00:00", 110, -130),
            ("2026-08-24T19:00:00+00:00", 150, -190),
        )
        f = clv.attach_clv(prediction(), odds)
        assert len(f) == 1
        assert f["opened_at"][0].startswith("2026-08-24T11")
        assert f["closed_at"][0].startswith("2026-08-24T19")

    def test_the_quote_is_not_the_close(self):
        """The regression: open and close must be able to differ."""
        odds = odds_rows(
            ("2026-08-24T11:00:00+00:00", 100, -120),
            ("2026-08-24T19:00:00+00:00", 180, -240),
        )
        f = clv.attach_clv(prediction(), odds)
        assert f["open_fair_over"][0] != f["close_fair_over"][0]


class TestTheSideIsFixedAtTheOpen:
    def test_side_follows_the_opening_price_not_the_close(self):
        """
        Model at 55%. Opens at 48% -- model is over. Closes at 62%, which if it
        set the side would flip it to under and manufacture a win.
        """
        odds = odds_rows(
            ("2026-08-24T11:00:00+00:00", 108, -108),     # ~50/50
            ("2026-08-24T19:00:00+00:00", -200, 170),     # heavily over
        )
        f = clv.attach_clv(prediction(model_over_prob=0.95), odds)
        assert f["side"][0] == clv.SIDE_OVER
        assert f["clv_points"][0] > 0            # market came to the model

    def test_a_model_agreeing_with_the_book_has_no_side(self):
        assert clv.model_side(0.5, 0.5) is None

    def test_under_movement_scores_like_over_movement(self):
        """Signed by side: an under the market moves toward is a win too."""
        assert clv.clv_points(clv.SIDE_UNDER, 0.50, 0.40) > 0
        assert clv.clv_points(clv.SIDE_OVER, 0.50, 0.40) < 0


class TestItRefusesToCompareDifferentMarkets:
    def test_a_moved_line_is_excluded(self):
        """4.5 K and 5.5 K are not two prices for one question."""
        odds = pd.concat([
            odds_rows(("2026-08-24T11:00:00+00:00", 100, -120), line=4.5,
                      market="pitcher_strikeouts", player="Ranger Suarez"),
            odds_rows(("2026-08-24T19:00:00+00:00", 100, -120), line=5.5,
                      market="pitcher_strikeouts", player="Ranger Suarez"),
        ])
        f = clv.attach_clv(
            prediction(line=4.5, market="pitcher_strikeouts", player="Ranger Suarez"),
            odds)
        assert f.empty

    def test_in_play_prices_are_not_a_close(self):
        """The log keeps in-play prices on purpose; they know the game."""
        odds = odds_rows(
            ("2026-08-24T11:00:00+00:00", 100, -120),
            ("2026-08-24T23:30:00+00:00", 300, -400),   # after first pitch
        )
        assert clv.attach_clv(prediction(), odds).empty


class TestSummary:
    def test_empty_reports_zero_not_a_number(self):
        assert clv.summarise(pd.DataFrame())["n"] == 0

    def test_the_interval_is_reported(self):
        """A mean without one invites reading noise as a finding."""
        f = pd.DataFrame({"clv_points": [1.0, -1.0, 2.0, -2.0, 0.5]})
        s = clv.summarise(f)
        assert s["n"] == 5
        assert s["ci_low"] < s["mean_points"] < s["ci_high"]

    def test_beat_close_counts_strict_wins(self):
        f = pd.DataFrame({"clv_points": [1.0, 0.0, -1.0, 2.0]})
        assert clv.summarise(f)["beat_close_pct"] == 50.0


class TestBooksAreNotMixed:
    """
    The log stored one book until 2026-08-24 and now stores the whole market,
    so a new way to be wrong appeared: differencing one book's opening price
    against another's close measures the gap *between the books* and reports it
    as the market moving toward the model.
    """

    def test_each_book_is_its_own_observation(self):
        odds = pd.concat([
            odds_rows(("2026-08-24T11:00:00+00:00", 100, -120),
                      ("2026-08-24T19:00:00+00:00", 120, -150), book="DraftKings"),
            odds_rows(("2026-08-24T11:00:00+00:00", 105, -125),
                      ("2026-08-24T19:00:00+00:00", 130, -165), book="FanDuel"),
        ])
        f = clv.attach_clv(prediction(), odds)
        assert len(f) == 2
        assert set(f["book"]) == {"DraftKings", "FanDuel"}

    def test_an_open_is_never_differenced_against_another_books_close(self):
        """
        DraftKings opens and never prices again; FanDuel only prices at the
        close. Neither book moved, so there is nothing to measure, and the
        cross-book pairing must not invent a movement out of their spread.
        """
        odds = pd.concat([
            odds_rows(("2026-08-24T11:00:00+00:00", 100, -120), book="DraftKings"),
            odds_rows(("2026-08-24T19:00:00+00:00", 180, -240), book="FanDuel"),
        ])
        assert clv.attach_clv(prediction(), odds).empty

    def test_a_books_movement_is_its_own(self):
        """One book moves toward the model, the other away. Both are recorded."""
        odds = pd.concat([
            odds_rows(("2026-08-24T11:00:00+00:00", 108, -108),
                      ("2026-08-24T19:00:00+00:00", -200, 170), book="DraftKings"),
            odds_rows(("2026-08-24T11:00:00+00:00", 108, -108),
                      ("2026-08-24T19:00:00+00:00", 170, -200), book="FanDuel"),
        ])
        f = clv.attach_clv(prediction(model_over_prob=0.95), odds)
        pts = dict(zip(f["book"], f["clv_points"]))
        assert pts["DraftKings"] > 0
        assert pts["FanDuel"] < 0
