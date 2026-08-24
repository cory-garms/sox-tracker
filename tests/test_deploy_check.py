"""
The check that would have caught 2026-08-23.

A build failed on a schema change and Render kept serving the previous deploy.
Every page returned 200, the tests passed, the data was committed on schedule,
and the site silently stopped updating for a day. Every check in the repo ran
against the repo, and the repo was fine.

Two failures live here and they are reported separately because they mean
different things and have different fixes: an old commit serving fresh-looking
pages is a broken build, and the right commit serving old data is a broken
refresh.
"""

from __future__ import annotations

from datetime import date

from scripts.check_deploy import OK, STALE, data_age_days, evaluate

TODAY = date(2026, 8, 24)
HEAD = "52485b4c0ffee1234567890abcdef0123456789a"
OLD = "78499ffdeadbeef1234567890abcdef012345678"


def health(commit=HEAD, data_through="2026-08-24"):
    return {"status": "ok", "app": "dirtywater", "version": "2026.1",
            "commit": commit, "data_through": data_through}


class TestTheAugust23Failure:
    def test_an_old_commit_serving_fine_pages_is_caught(self):
        """
        The exact shape: healthy 200s, current-looking site, previous build.
        Nothing else in the repo could see this.
        """
        code, problems = evaluate(health(commit=OLD), expect_commit=HEAD,
                                  commit_age_minutes=1440, today=TODAY)
        assert code == STALE
        assert any("STALE DEPLOY" in p for p in problems)

    def test_a_current_deploy_passes(self):
        code, problems = evaluate(health(), expect_commit=HEAD,
                                  commit_age_minutes=1440, today=TODAY)
        assert code == OK
        assert problems == []

    def test_a_short_commit_matches_a_long_one(self):
        """Render reports a full SHA; a caller may pass an abbreviated one."""
        code, _ = evaluate(health(commit=HEAD), expect_commit=HEAD[:7],
                           commit_age_minutes=1440, today=TODAY)
        assert code == OK


class TestDeployInFlightIsNotAFailure:
    def test_a_just_pushed_commit_is_given_grace(self):
        """
        Render free-plan builds take minutes. Without a grace window every
        check inside the build would fail, and a check that cries wolf hourly
        is a check nobody reads -- which is how the original failure survived.
        """
        code, _ = evaluate(health(commit=OLD), expect_commit=HEAD,
                           commit_age_minutes=3, grace_minutes=45, today=TODAY)
        assert code == OK

    def test_past_the_grace_window_it_is_a_failure(self):
        code, _ = evaluate(health(commit=OLD), expect_commit=HEAD,
                           commit_age_minutes=90, grace_minutes=45, today=TODAY)
        assert code == STALE

    def test_unknown_age_is_treated_as_old(self):
        """Absent evidence of a fresh push, a mismatch is a real mismatch."""
        code, _ = evaluate(health(commit=OLD), expect_commit=HEAD,
                           commit_age_minutes=None, today=TODAY)
        assert code == STALE


class TestStaleData:
    def test_fresh_data_passes(self):
        code, _ = evaluate(health(data_through="2026-08-23"), expect_commit=HEAD,
                           commit_age_minutes=1440, today=TODAY)
        assert code == OK

    def test_an_off_day_is_not_staleness(self):
        """Two days of slack: an off day is normal, so is a late finish."""
        code, _ = evaluate(health(data_through="2026-08-22"), expect_commit=HEAD,
                           commit_age_minutes=1440, today=TODAY)
        assert code == OK

    def test_a_week_of_no_updates_is_caught(self):
        code, problems = evaluate(health(data_through="2026-08-17"), expect_commit=HEAD,
                                  commit_age_minutes=1440, today=TODAY)
        assert code == STALE
        assert any("STALE DATA" in p for p in problems)

    def test_missing_data_through_is_caught_not_ignored(self):
        """A field that silently went missing must not read as healthy."""
        code, problems = evaluate(health(data_through=None), expect_commit=HEAD,
                                  commit_age_minutes=1440, today=TODAY)
        assert code == STALE
        assert any("STALE DATA" in p for p in problems)

    def test_the_two_failures_are_reported_separately(self):
        code, problems = evaluate(health(commit=OLD, data_through="2026-08-01"),
                                  expect_commit=HEAD, commit_age_minutes=1440,
                                  today=TODAY)
        assert code == STALE
        assert any("STALE DEPLOY" in p for p in problems)
        assert any("STALE DATA" in p for p in problems)


class TestOlderBuildsThatReportNoCommit:
    def test_unknown_commit_is_stale_not_a_pass(self):
        """
        A build predating this endpoint reports "unknown". That is exactly the
        situation being detected, so it must not be waved through.
        """
        code, problems = evaluate(health(commit="unknown"), expect_commit=HEAD,
                                  commit_age_minutes=1440, today=TODAY)
        assert code == STALE
        assert any("no commit" in p for p in problems)

    def test_without_an_expected_commit_only_data_is_judged(self):
        """Run locally with no --expect-commit, the deploy half is skipped."""
        code, _ = evaluate(health(commit="unknown"), expect_commit="", today=TODAY)
        assert code == OK


class TestDataAgeArithmetic:
    def test_ages_are_days(self):
        assert data_age_days("2026-08-24", today=TODAY) == 0
        assert data_age_days("2026-08-17", today=TODAY) == 7

    def test_junk_is_none_rather_than_a_crash(self):
        assert data_age_days("not-a-date", today=TODAY) is None
        assert data_age_days(None, today=TODAY) is None
