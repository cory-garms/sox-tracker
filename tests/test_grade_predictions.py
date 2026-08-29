"""
Outcome grading.

The regression this guards: nothing ever scored a prediction against what
happened, so the models' NO CALL discipline was unfalsifiable.

The traps this pins down, in order of how badly they would corrupt the record:

1. **Doubleheaders.** A prop is per game, not per date. Summing both ends of
   2026-07-22 invents a player who batted nine times, and every calibration
   number downstream inherits the lie.
2. **Postponements.** A game that was never played must never settle a
   prediction.
3. **Pushes.** An actual landing exactly on a whole-number line is refunded by
   the book; scoring it as a miss understates the model.
"""

from __future__ import annotations

import pandas as pd
import pytest

from analysis.grading import grade_frame, resolve_appearance, total_bases
from data import predictions_history as ph


def prediction(**kwargs):
    base = {
        "captured_at": "2026-08-22T15:00:00+00:00",
        "game_date": "2026-08-22", "commence_time": None, "event_id": "e1",
        "game_pk": pd.NA, "market": "pitcher_strikeouts",
        "player_id": 700, "player": "Test Starter",
        "line": 4.5, "projection": 5.1, "model_over_prob": 0.61,
        "book_over_prob": 0.52, "edge": 0.6, "model_error": 0.45,
        "recommendation": "OVER 🔥", "model_version": "v1.2",
        "opponent_name": "SF", "opponent_factor": 1.0,
        "actual": float("nan"), "outcome": "", "settled_at": "",
    }
    base.update(kwargs)
    return base


def pitching_log(**kwargs):
    base = {"player_id": 700, "player_name": "Test Starter",
            "game_date": "2026-08-22", "game_pk": 500, "so": 6, "is_starter": True}
    base.update(kwargs)
    return pd.DataFrame([base])


def batting_log(rows):
    return pd.DataFrame(rows)


EMPTY_BAT = pd.DataFrame(columns=["player_id", "player_name", "game_date", "game_pk",
                                  "h", "doubles", "triples", "hr"])
EMPTY_PIT = pd.DataFrame(columns=["player_id", "player_name", "game_date", "game_pk", "so"])


class TestTotalBases:
    @pytest.mark.parametrize("h,d,t,hr,expected", [
        (0, 0, 0, 0, 0),
        (1, 0, 0, 0, 1),      # single
        (1, 1, 0, 0, 2),      # the hit *is* the double
        (1, 0, 1, 0, 3),
        (1, 0, 0, 1, 4),
        (3, 1, 0, 1, 7),      # 1B + 2B + HR = 1+2+4
    ])
    def test_reduces_correctly(self, h, d, t, hr, expected):
        """TB = H + 2B + 2·3B + 3·HR, since a hit already counts its own base."""
        assert total_bases(pd.Series({"h": h, "doubles": d, "triples": t, "hr": hr})) == expected

    def test_missing_columns_count_as_zero(self):
        assert total_bases(pd.Series({"h": 2})) == 2


class TestGrading:
    def test_settles_a_strikeout_prediction(self):
        frame = pd.DataFrame([prediction()])
        out, stats = grade_frame(frame, pitching_log(so=6), EMPTY_BAT)
        assert stats["graded"] == 1
        assert out.loc[0, "actual"] == 6.0
        assert out.loc[0, "outcome"] == "over"
        assert out.loc[0, "game_pk"] == 500

    def test_settles_a_total_bases_prediction(self):
        frame = pd.DataFrame([prediction(market="batter_total_bases", player_id=800,
                                         player="Test Hitter", line=1.5)])
        bat = batting_log([{"player_id": 800, "player_name": "Test Hitter",
                            "game_date": "2026-08-22", "game_pk": 500,
                            "h": 2, "doubles": 1, "triples": 0, "hr": 0}])
        out, stats = grade_frame(frame, EMPTY_PIT, bat)
        assert stats["graded"] == 1
        assert out.loc[0, "actual"] == 3.0
        assert out.loc[0, "outcome"] == "over"

    def test_an_actual_on_a_whole_number_line_pushes(self):
        frame = pd.DataFrame([prediction(line=6.0)])
        out, _ = grade_frame(frame, pitching_log(so=6), EMPTY_BAT)
        assert out.loc[0, "outcome"] == "push"

    def test_records_when_it_settled(self):
        frame = pd.DataFrame([prediction()])
        out, _ = grade_frame(frame, pitching_log(), EMPTY_BAT, now="2026-08-23T04:00:00+00:00")
        assert out.loc[0, "settled_at"] == "2026-08-23T04:00:00+00:00"

    def test_an_already_settled_row_is_untouched(self):
        frame = pd.DataFrame([prediction(actual=9.0, outcome="over", settled_at="earlier")])
        out, stats = grade_frame(frame, pitching_log(so=2), EMPTY_BAT)
        assert stats["graded"] == 0
        assert stats["already"] == 1
        assert out.loc[0, "actual"] == 9.0      # not overwritten by the new log
        assert out.loc[0, "settled_at"] == "earlier"

    def test_a_prediction_for_an_unplayed_game_waits(self):
        """Tonight's projection simply stays ungraded until tonight finishes."""
        frame = pd.DataFrame([prediction(game_date="2026-09-01")])
        out, stats = grade_frame(frame, pitching_log(), EMPTY_BAT)
        assert stats["graded"] == 0
        assert out.loc[0, "outcome"] == ""

    def test_a_postponed_game_never_settles(self):
        """
        The cache only holds games that were actually played, so a postponement
        leaves no row to join to and the prediction stays open.
        """
        frame = pd.DataFrame([prediction(game_date="2026-08-22")])
        out, stats = grade_frame(frame, EMPTY_PIT, EMPTY_BAT)
        assert stats["graded"] == 0
        assert out.loc[0, "outcome"] == ""

    def test_a_player_who_did_not_appear_is_not_settled(self):
        frame = pd.DataFrame([prediction(player_id=999, player="Someone Else")])
        out, stats = grade_frame(frame, pitching_log(), EMPTY_BAT)
        assert stats["graded"] == 0

    def test_an_unknown_market_is_skipped(self):
        frame = pd.DataFrame([prediction(market="team_totals")])
        _, stats = grade_frame(frame, pitching_log(), EMPTY_BAT)
        assert stats["skipped"] == 1


class TestDoubleheaders:
    """
    2026-07-22 is a real doubleheader in the cache, and the date whose game 1
    carries the *higher* gamePk — the case that has already broken this project
    once.
    """

    def test_a_starter_resolves_cleanly(self):
        """A pitcher starts one end of a doubleheader, so there is no ambiguity."""
        logs = pd.DataFrame([
            {"player_id": 700, "player_name": "SP", "game_date": "2026-07-22",
             "game_pk": 824735, "so": 7},
        ])
        row, reason = resolve_appearance(logs, 700, "SP", "2026-07-22")
        assert reason == "ok"
        assert row["game_pk"] == 824735

    def test_a_batter_in_both_games_is_refused_not_guessed(self):
        logs = pd.DataFrame([
            {"player_id": 800, "player_name": "BAT", "game_date": "2026-07-22",
             "game_pk": 824735, "h": 2, "doubles": 0, "triples": 0, "hr": 0},
            {"player_id": 800, "player_name": "BAT", "game_date": "2026-07-22",
             "game_pk": 824732, "h": 1, "doubles": 1, "triples": 0, "hr": 0},
        ])
        row, reason = resolve_appearance(logs, 800, "BAT", "2026-07-22")
        assert row is None
        assert "ambiguous" in reason

    def test_totals_are_never_summed_across_a_doubleheader(self):
        """
        The failure mode: 2 TB in game one plus 3 in game two graded as a
        5-total-base day against a 1.5 line.
        """
        frame = pd.DataFrame([prediction(market="batter_total_bases", player_id=800,
                                         player="BAT", game_date="2026-07-22", line=1.5)])
        bat = batting_log([
            {"player_id": 800, "player_name": "BAT", "game_date": "2026-07-22",
             "game_pk": 824735, "h": 2, "doubles": 0, "triples": 0, "hr": 0},
            {"player_id": 800, "player_name": "BAT", "game_date": "2026-07-22",
             "game_pk": 824732, "h": 1, "doubles": 1, "triples": 0, "hr": 0},
        ])
        out, stats = grade_frame(frame, EMPTY_PIT, bat)
        assert stats["graded"] == 0
        assert out.loc[0, "outcome"] == ""
        assert pd.isna(out.loc[0, "actual"])

    def test_a_single_appearance_on_a_doubleheader_date_still_grades(self):
        """A bench bat used in only one end resolves fine."""
        frame = pd.DataFrame([prediction(market="batter_total_bases", player_id=801,
                                         player="BENCH", game_date="2026-07-22", line=0.5)])
        bat = batting_log([
            {"player_id": 801, "player_name": "BENCH", "game_date": "2026-07-22",
             "game_pk": 824732, "h": 1, "doubles": 0, "triples": 0, "hr": 0},
        ])
        out, stats = grade_frame(frame, EMPTY_PIT, bat)
        assert stats["graded"] == 1
        assert out.loc[0, "actual"] == 1.0


class TestPredictionsWithNoBookLine:
    """
    Most logged projections never had a line matched to them. They still settle
    — the actual measures projection error — but they carry no over/under, so
    they must stay out of calibration and must not return to the queue forever.
    """

    def _graded_once(self):
        frame = pd.DataFrame([prediction(line=float("nan"))])
        return grade_frame(frame, pitching_log(so=6), EMPTY_BAT)

    def test_the_actual_is_still_recorded(self):
        out, stats = self._graded_once()
        assert stats["graded"] == 1
        assert out.loc[0, "actual"] == 6.0

    def test_it_is_marked_settled_rather_than_left_blank(self):
        out, _ = self._graded_once()
        assert out.loc[0, "outcome"] == ph.OUTCOME_NO_LINE

    def test_it_does_not_come_back_around_on_the_next_run(self):
        out, _ = self._graded_once()
        _, stats = grade_frame(out, pitching_log(so=6), EMPTY_BAT)
        assert stats["graded"] == 0
        assert stats["already"] == 1

    def test_it_is_excluded_from_scoring(self):
        out, _ = self._graded_once()
        assert ph.graded(out).empty

    def test_but_is_available_for_projection_error(self):
        out, _ = self._graded_once()
        assert len(ph.with_actuals(out)) == 1


class TestGradedRowsAreUsable:
    def test_every_graded_row_has_a_line(self):
        """
        The Phase 1 regression, restated as a property of the output: a row with
        no line cannot be scored and must not appear graded.
        """
        frame = pd.DataFrame([prediction(), prediction(player="No Line", line=float("nan"),
                                                       captured_at="2026-08-22T16:00:00+00:00")])
        logs = pd.DataFrame([
            {"player_id": 700, "player_name": "Test Starter", "game_date": "2026-08-22",
             "game_pk": 500, "so": 6},
            {"player_id": 700, "player_name": "No Line", "game_date": "2026-08-22",
             "game_pk": 500, "so": 6},
        ])
        out, _ = grade_frame(frame, logs, EMPTY_BAT)
        settled = ph.graded(out)
        assert not settled.empty
        assert settled["line"].notna().all()


class TestTheDoubleheaderNowResolves:
    """
    Refusing a doubleheader was correct only while the reason held.

    Both resolvers declined these dates and both gave the same reason: the
    cache carried no first-pitch time to match the odds event's commence_time
    against. It carries one now (`game_start`, stored by the Fetcher), and
    every archived prediction has always carried a commence_time. So the end of
    the doubleheader a prediction was about is a lookup, not a guess.

    2026-08-29 is the first doubleheader date this project will have logged
    predictions for -- the two earlier ones, 2026-07-17 and 2026-07-22, predate
    the archive. Its two games start at 17:05Z and 23:15Z.
    """

    DATE = "2026-08-29"
    G1, G2 = 823539, 823501           # note: game 2 carries the *lower* pk
    STARTS = {G1: "2026-08-29T17:05:00Z", G2: "2026-08-29T23:15:00Z"}

    def logs(self):
        return pd.DataFrame([
            {"player_id": 800, "player_name": "BAT", "game_date": self.DATE,
             "game_pk": self.G1, "h": 2, "doubles": 0, "triples": 0, "hr": 0},
            # Deliberately different totals: 2 bases in the opener, 3 in the
            # nightcap, so a test that grades the wrong end says so.
            {"player_id": 800, "player_name": "BAT", "game_date": self.DATE,
             "game_pk": self.G2, "h": 2, "doubles": 1, "triples": 0, "hr": 0},
        ])

    def test_a_prediction_on_the_opener_grades_against_the_opener(self):
        row, reason = resolve_appearance(
            self.logs(), 800, "BAT", self.DATE,
            commence_time="2026-08-29T17:05:00Z", starts=self.STARTS,
        )
        assert reason == "ok"
        assert row["game_pk"] == self.G1

    def test_a_prediction_on_the_nightcap_grades_against_the_nightcap(self):
        row, reason = resolve_appearance(
            self.logs(), 800, "BAT", self.DATE,
            commence_time="2026-08-29T23:15:00Z", starts=self.STARTS,
        )
        assert reason == "ok"
        assert row["game_pk"] == self.G2

    def test_the_match_survives_a_book_quoting_a_few_minutes_off(self):
        """The two ends are six hours apart; nobody's clock is that wrong."""
        row, _ = resolve_appearance(
            self.logs(), 800, "BAT", self.DATE,
            commence_time="2026-08-29T23:09:00Z", starts=self.STARTS,
        )
        assert row["game_pk"] == self.G2

    def test_without_first_pitch_times_it_still_refuses(self):
        """A cache written before game_start existed must not start guessing."""
        row, reason = resolve_appearance(
            self.logs(), 800, "BAT", self.DATE,
            commence_time="2026-08-29T23:15:00Z", starts=None,
        )
        assert row is None
        assert "ambiguous" in reason

    def test_one_missing_start_poisons_the_whole_match(self):
        """Nearest-of-what-we-know is a guess wearing arithmetic."""
        row, reason = resolve_appearance(
            self.logs(), 800, "BAT", self.DATE,
            commence_time="2026-08-29T23:15:00Z",
            starts={self.G1: "2026-08-29T17:05:00Z"},
        )
        assert row is None
        assert "ambiguous" in reason

    def test_a_quote_matching_neither_game_is_refused(self):
        """
        Two games equidistant from the quote is not a doubleheader we know.

        Once the game check landed this stopped reading "ambiguous" and started
        reading "no appearance in the game this prediction is about", which is
        the better description: a 20:10Z quote is not three hours from the right
        game, it is nowhere near either. Both refuse, and the refusal is what
        this test is for -- so it asserts that, not the sentence.
        """
        row, reason = resolve_appearance(
            self.logs(), 800, "BAT", self.DATE,
            commence_time="2026-08-29T20:10:00Z",
            starts={self.G1: "2026-08-29T17:05:00Z", self.G2: "2026-08-29T23:15:00Z"},
        )
        assert row is None
        assert reason != "ok"
        assert reason != "player did not appear", "must not settle terminally"

    def test_totals_are_still_never_summed(self):
        """The original trap, re-checked now that the date resolves at all."""
        frame = pd.DataFrame([prediction(
            market="batter_total_bases", player_id=800, player="BAT",
            game_date=self.DATE, commence_time="2026-08-29T23:15:00Z", line=1.5,
        )])
        out, stats = grade_frame(
            frame, pd.DataFrame(), self.logs(), starts=self.STARTS,
        )
        assert stats["graded"] == 1
        assert out.iloc[0]["actual"] == 3.0        # the nightcap's 3, not the opener's 2
        assert out.iloc[0]["game_pk"] == self.G2


class TestFirstPitchSurvivesToTheCache:
    """
    The schema is an allowlist, and a column it omits is dropped silently.

    game_start was added to the Fetcher and verified against parse_schedule's
    output, which was the wrong thing to check: enforce_schema runs afterwards
    and kept only the declared columns, so the parquet had no first-pitch time
    and every doubleheader would have gone on being refused with the resolver
    sitting right there ready to use it. Checked here at the schema, which is
    where the drop happened.
    """

    def test_the_games_schema_declares_a_first_pitch(self):
        from data.schema import GAMES_SCHEMA
        assert "game_start" in GAMES_SCHEMA

    def test_the_fetcher_emits_what_the_schema_declares(self):
        """Neither half is useful without the other."""
        from data.fetcher import parse_schedule
        from data.schema import GAMES_SCHEMA
        raw = [{
            "gamePk": 824735, "officialDate": "2026-07-22", "gameNumber": 1,
            "gameDate": "2026-07-22T17:35:00Z",
            "status": {"abstractGameState": "Final", "detailedState": "Final"},
            "teams": {
                "home": {"team": {"id": 147}, "score": 2,
                         "leagueRecord": {"wins": 70, "losses": 55}},
                "away": {"team": {"id": 111}, "score": 5,
                         "leagueRecord": {"wins": 71, "losses": 54}},
            },
        }]
        rows = parse_schedule(raw, 111, 2026)
        assert rows and rows[0]["game_start"] == "2026-07-22T17:35:00Z"
        assert set(rows[0]) <= set(GAMES_SCHEMA), (
            f"emitted but undeclared: {set(rows[0]) - set(GAMES_SCHEMA)}"
        )


class TestOneGameOnTheDateIsNotTheRightGame:
    """
    The failure the doubleheader fix did not cover, found live on 2026-08-29.

    The opener finished 6-0 and was cached. The nightcap had not started. A
    prediction about the nightcap looked for its player on that date, found the
    opener's line sitting there alone, and matched it -- because the ambiguity
    check only ran when a player had two appearances, and here he had one.

    89 rows settled hours before their game began: 36 took the opener's totals
    as their own, and 53 were settled "did not appear" for a game nobody had
    played. The second half is the worse one, because DNP is terminal.

    The date was never the question. The game was.
    """

    DATE = "2026-08-29"
    G1, G2 = 823539, 823501
    STARTS = {G1: "2026-08-29T17:05:00Z", G2: "2026-08-29T23:15:00Z"}
    OPENER_ONLY = {G1: "2026-08-29T17:05:00Z"}      # the cache mid-afternoon

    def logs(self):
        """One appearance: the opener, which is all that has been played."""
        return pd.DataFrame([
            {"player_id": 800, "player_name": "BAT", "game_date": self.DATE,
             "game_pk": self.G1, "h": 2, "doubles": 0, "triples": 0, "hr": 0},
        ])

    def test_a_nightcap_prediction_is_not_settled_by_the_opener(self):
        row, reason = resolve_appearance(
            self.logs(), 800, "BAT", self.DATE,
            commence_time="2026-08-29T23:16:00Z", starts=self.OPENER_ONLY,
        )
        assert row is None, "the nightcap was graded against the opener"
        assert "game this prediction is about" in reason

    def test_an_opener_prediction_still_settles_normally(self):
        row, reason = resolve_appearance(
            self.logs(), 800, "BAT", self.DATE,
            commence_time="2026-08-29T17:06:00Z", starts=self.OPENER_ONLY,
        )
        assert reason == "ok"
        assert row["game_pk"] == self.G1

    def test_a_single_game_day_is_untouched(self):
        """The clock check must not start refusing ordinary Tuesdays."""
        logs = pd.DataFrame([
            {"player_id": 800, "player_name": "BAT", "game_date": "2026-08-25",
             "game_pk": 823826, "h": 1, "doubles": 0, "triples": 0, "hr": 0},
        ])
        row, reason = resolve_appearance(
            logs, 800, "BAT", "2026-08-25",
            commence_time="2026-08-25T22:41:00Z",
            starts={823826: "2026-08-25T22:40:00Z"},
        )
        assert reason == "ok"

    def test_without_start_times_it_behaves_as_it_always_did(self):
        """A cache written before game_start existed must not start refusing."""
        row, reason = resolve_appearance(
            self.logs(), 800, "BAT", self.DATE,
            commence_time="2026-08-29T23:16:00Z", starts=None,
        )
        assert reason == "ok"

    def test_a_dnp_is_not_invented_for_a_game_not_yet_played(self):
        """
        The half that does the lasting damage: DNP is terminal, so a hitter
        settled that way for tonight's game never gets asked about again.
        """
        empty = pd.DataFrame(columns=["player_id", "player_name", "game_date",
                                      "game_pk", "h", "doubles", "triples", "hr"])
        row, reason = resolve_appearance(
            empty, 800, "BAT", self.DATE,
            commence_time="2026-08-29T23:16:00Z", starts=self.OPENER_ONLY,
        )
        assert row is None
        assert reason != "player did not appear", "would settle DNP terminally"


class TestADnpNeedsTheGameToHaveHappened:
    """
    "Did not appear" is terminal, so it must never be said about a game we are
    not actually looking at.

    The rollover bug files some rows under the following day's date while their
    event is the night before's game. Grading looked for those players on the
    written date, found nothing, and settled them DNP -- permanently, for a game
    they may well have played in. 26 such rows on 2026-08-29.
    """

    STARTS = {823539: "2026-08-29T17:05:00Z"}      # only today's opener is known

    def logs(self):
        """Somebody else played today. An empty frame short-circuits earlier."""
        return pd.DataFrame([
            {"player_id": 999, "player_name": "OTHER", "game_date": "2026-08-29",
             "game_pk": 823539, "h": 1, "doubles": 0, "triples": 0, "hr": 0},
        ])

    def test_a_row_about_another_days_game_is_not_settled_dnp(self):
        row, reason = resolve_appearance(
            self.logs(), 800, "BAT", "2026-08-29",
            commence_time="2026-08-28T23:16:00Z",   # last night's game
            starts=self.STARTS,
        )
        assert row is None
        assert reason != "player did not appear"

    def test_a_genuine_absence_from_today_still_settles_dnp(self):
        """The bench bat this outcome exists for."""
        row, reason = resolve_appearance(
            self.logs(), 800, "BAT", "2026-08-29",
            commence_time="2026-08-29T17:06:00Z",   # the game we do know
            starts=self.STARTS,
        )
        assert reason == "player did not appear"
